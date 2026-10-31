from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from pkgutil import get_data
from typing import Any

from .transcript import Usage
from .util import safe_json, stable_hash

SCHEMA_VERSION = 2
LEASE_SECONDS = 20 * 60
AGENT_TOOLS = frozenset({"Agent", "spawn_agent", "collaboration.spawn_agent"})
WAIT_TOOLS = frozenset(
    {"wait", "write_stdin", "sleep", "wait_agent", "mcp__codex_app__wait_threads"}
)


@dataclass(frozen=True)
class RunConfig:
    max_tokens: int
    warn_ratio: float = 0.80
    block_agents_ratio: float = 0.90
    max_tool_calls: int = 200
    max_agents: int = 4
    max_in_flight: int = 8
    max_tool_output_chars: int = 50_000
    repeat_steer: int = 3
    repeat_halt: int = 5
    fail_closed: bool = True


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    additional_context: str | None = None
    run: dict[str, Any] | None = None


class ObservationHealth:
    """Cross-process observer circuit; failures here never enter budget policy.

    One row contains fixed error categories and counters, never event content.
    Each hook gets at most one attempt. After three failures a single leased
    recovery probe is allowed following the bounded cooldown.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("observer health requires a regular file")
        self.conn = sqlite3.connect(str(path), timeout=0.05, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported observer health schema")
            if version == 0:
                self.conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS health (
                        id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL DEFAULT 'healthy',
                        attempts INTEGER NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
                        failures INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0,
                        suppressed INTEGER NOT NULL DEFAULT 0, epoch INTEGER NOT NULL DEFAULT 0,
                        retry_at REAL NOT NULL DEFAULT 0, last_attempt REAL,
                        last_success REAL, error_code TEXT,
                        gap_since REAL, gap_until REAL
                    );
                    INSERT OR IGNORE INTO health(id) VALUES(1);
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            os.chmod(path, 0o600)
        except BaseException:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def reserve(self) -> dict[str, Any] | None:
        now = time.time()
        with self.transaction():
            row = dict(self.conn.execute("SELECT * FROM health WHERE id=1").fetchone())
            if row["last_attempt"] is not None and now < row["last_attempt"]:
                self.conn.execute(
                    "UPDATE health SET state='open',error_code='clock_discontinuity',"
                    "retry_at=last_attempt,epoch=epoch+1,suppressed=suppressed+1,"
                    "gap_since=COALESCE(gap_since,last_attempt),gap_until=last_attempt WHERE id=1")
                return None
            if row["state"] != "healthy" and (
                    now < row["retry_at"] or now < (row["last_attempt"] or now)):
                self.conn.execute(
                    "UPDATE health SET suppressed=suppressed+1,epoch=epoch+1,"
                    "gap_until=MAX(COALESCE(gap_until,?),?) WHERE id=1", (now, now))
                return None
            probe = row["state"] != "healthy"
            self.conn.execute(
                "UPDATE health SET attempts=attempts+1,last_attempt=?,state=?,retry_at=? "
                "WHERE id=1",
                (now, "probing" if probe else "healthy", now + 2 if probe else 0))
            return {"ticket": row["attempts"] + 1, "epoch": row["epoch"], "at": now,
                    "gap_since": row["gap_since"], "gap_until": row["gap_until"]}

    def finish(self, ticket: dict[str, Any], *, error: Exception | None = None) -> None:
        now = time.time()
        with self.transaction():
            row = dict(self.conn.execute("SELECT * FROM health WHERE id=1").fetchone())
            latest = (ticket["ticket"] >= row["finished"]
                      and (row["state"] != "probing" or ticket["ticket"] == row["attempts"]))
            if error is None:
                if latest:
                    self.conn.execute(
                        "UPDATE health SET state='healthy',failures=0,retry_at=0,finished=?,"
                        "last_success=? WHERE id=1", (ticket["ticket"], now))
                return
            code = ("sqlite_busy" if isinstance(error, sqlite3.OperationalError)
                    and (getattr(error, "sqlite_errorcode", 0) & 0xFF in (5, 6)
                         or str(error) in {"database is locked", "database table is locked"})
                    else "sqlite_error" if isinstance(error, sqlite3.Error)
                    else "storage_error" if isinstance(error, OSError)
                    else "observer_error")
            failures = row["failures"] + 1 if latest else row["failures"]
            delay = min(300, 30 * 2 ** min(max(0, failures - 3), 4)) if failures >= 3 else 0
            gap_since = (min(ticket["at"], row["gap_since"] or ticket["at"])
                         if row["failures"] else ticket["at"])
            self.conn.execute(
                "UPDATE health SET dropped=dropped+1,epoch=epoch+1,error_code=?,gap_since=?,"
                "gap_until=MAX(COALESCE(gap_until,?),?) WHERE id=1",
                (code, gap_since, now, now))
            if latest:
                self.conn.execute(
                    "UPDATE health SET failures=?,state=?,retry_at=?,finished=? WHERE id=1",
                    (failures, "open" if delay else "healthy", now + delay,
                     ticket["ticket"]))

    @staticmethod
    def snapshot(path: Path) -> dict[str, Any]:
        if not path.exists() and not path.is_symlink():
            return {"state": "no_observations", "epoch": 0, "dropped": None,
                    "suppressed": None, "last_success": None}
        if path.is_symlink() or not path.is_file():
            return {"state": "unavailable", "epoch": None}
        conn = None
        try:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
            conn.row_factory = sqlite3.Row
            if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("unsupported observer health schema")
            row = dict(conn.execute("SELECT * FROM health WHERE id=1").fetchone())
            row.pop("id")
            return row
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return {"state": "unavailable", "epoch": None}
        finally:
            if conn is not None:
                conn.close()


class OptimizationLedger:
    """Bounded advisory observations, isolated from every version of the budget ledger.

    Only hashes, finite categories, counters and times cross this interface. No
    optimization decision can admit a tool, change a budget, or stop a Task.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("optimizer requires a regular local database")
        self.conn = sqlite3.connect(str(path), timeout=0.25, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA busy_timeout=250")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA synchronous=FULL")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("unsupported optimizer schema")
            if version == 0:
                self.conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS settings (enabled INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS turns (
                        turn_hash TEXT PRIMARY KEY, project_hash TEXT NOT NULL,
                        task_hash TEXT NOT NULL, role TEXT NOT NULL,
                        created REAL NOT NULL, updated REAL NOT NULL,
                        ended TEXT NOT NULL DEFAULT 'active',
                        started INTEGER NOT NULL DEFAULT 0,
                        limited INTEGER NOT NULL DEFAULT 0,
                        warnings INTEGER NOT NULL DEFAULT 0,
                        last_warning INTEGER NOT NULL DEFAULT 0,
                        completed_calls INTEGER NOT NULL DEFAULT 0,
                        check_sample INTEGER NOT NULL DEFAULT 0,
                        health_epoch INTEGER NOT NULL DEFAULT 0, issue_code TEXT
                    );
                    CREATE INDEX IF NOT EXISTS optimizer_project ON turns(project_hash, role);
                    CREATE TABLE IF NOT EXISTS calls (
                        turn_hash TEXT NOT NULL, call_hash TEXT NOT NULL,
                        input_hash TEXT NOT NULL, response_hash TEXT,
                        kind TEXT NOT NULL, capability TEXT, is_check INTEGER NOT NULL,
                        outcome TEXT NOT NULL DEFAULT 'pending',
                        failure_hash TEXT, error_class TEXT, completed_order INTEGER,
                        PRIMARY KEY(turn_hash, call_hash),
                        FOREIGN KEY(turn_hash) REFERENCES turns(turn_hash) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS observation_meta (
                        id INTEGER PRIMARY KEY CHECK(id=1), health_epoch INTEGER NOT NULL
                    );
                    INSERT OR IGNORE INTO observation_meta VALUES(1,0);
                    PRAGMA user_version=2;
                    COMMIT;
                """)
            elif version == 1:
                self._upgrade(path)
            os.chmod(path, 0o600)
        except BaseException:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    def _upgrade(self, path: Path) -> None:
        backup_root = path.parent / "backups"
        if backup_root.is_symlink():
            raise ValueError("optimizer backup requires a local directory")
        backup_root.mkdir(exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix="optimizer-v1-", suffix=".sqlite3", dir=backup_root)
        os.close(fd)
        target = sqlite3.connect(name)
        deadline = time.monotonic() + 0.5

        def progress(_status, _remaining, _total):
            if time.monotonic() > deadline:
                raise TimeoutError("optimizer backup timeout")

        try:
            self.conn.backup(target, pages=128, progress=progress, sleep=0.01)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("optimizer backup validation failed")
        finally:
            target.close()
        migration = get_data("codex_run_budget", "migrations/003_optimizer_sensing.sql")
        if migration is None:
            raise ValueError("optimizer migration unavailable")
        with self.transaction():
            # Concurrent hooks may have already applied the backed-up migration.
            if self.conn.execute("PRAGMA user_version").fetchone()[0] == 1:
                for statement in migration.decode().split(";"):
                    if statement.strip():
                        self.conn.execute(statement)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def configure(self, enabled: bool) -> None:
        with self.transaction():
            self.conn.execute("DELETE FROM settings")
            self.conn.execute("INSERT INTO settings VALUES(?)", (int(enabled),))
            if not enabled:
                self.conn.execute(
                    "UPDATE turns SET limited=1,check_sample=0,"
                    "issue_code=COALESCE(issue_code,'observer_disabled') WHERE ended='active'")

    @staticmethod
    def snapshot(path: Path, project: str) -> dict[str, Any]:
        """Read back one exact project without creating or migrating any database."""
        if path.is_symlink() or not path.is_file():
            if not path.is_symlink() and not path.exists():
                return {"enabled": True, "turns": [], "calls": [], "status": "no_observations"}
            raise ValueError("optimizer requires a regular local database")
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN")
            if conn.execute("PRAGMA user_version").fetchone()[0] not in (1, 2):
                raise ValueError("unsupported optimizer schema")
            setting = conn.execute("SELECT enabled FROM settings LIMIT 1").fetchone()
            turns = [dict(row) for row in conn.execute(
                "SELECT * FROM turns WHERE project_hash=? ORDER BY created,turn_hash", (project,))]
            calls = [dict(row) for row in conn.execute(
                "SELECT calls.* FROM calls JOIN turns USING(turn_hash) WHERE project_hash=?",
                (project,))]
            for turn in turns:
                if "health_epoch" not in turn:
                    turn.update(health_epoch=0, issue_code="legacy_coverage", limited=1,
                                check_sample=0)
            return {"enabled": bool(setting[0]) if setting else True,
                    "status": "observed" if turns else "no_observations",
                    "turns": turns, "calls": calls}
        finally:
            conn.close()

    def _calls(self, turn: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM calls WHERE turn_hash=? AND completed_order IS NOT NULL "
            "ORDER BY completed_order", (turn,)
        )]

    def _limited(self, turn: str, code: str) -> None:
        self.conn.execute(
            "UPDATE turns SET limited=1,check_sample=0,issue_code=COALESCE(issue_code,?) "
            "WHERE turn_hash=?", (code, turn))

    def observe(self, value: dict[str, Any]) -> str | None:
        from .optimization import MAX_CALLS, MAX_TURNS, baseline, check_sample, loop_warning

        with self.transaction():
            setting = self.conn.execute("SELECT enabled FROM settings LIMIT 1").fetchone()
            if setting is not None and not setting[0]:
                return None
            epoch = value.get("health_epoch", 0)
            current = self.conn.execute(
                "SELECT health_epoch FROM observation_meta WHERE id=1").fetchone()[0]
            if epoch > current:
                self.conn.execute(
                    "UPDATE turns SET limited=1,check_sample=0,"
                    "issue_code=COALESCE(issue_code,'observer_gap') WHERE ended='active' "
                    "OR (created<=? AND updated>=?)",
                    (value.get("gap_until") or 0, value.get("gap_since") or float("inf")))
                self.conn.execute("UPDATE observation_meta SET health_epoch=? WHERE id=1", (epoch,))
            turn, project, task, role = (value[key] for key in (
                "turn_hash", "project_hash", "task_hash", "role"))
            row = self.conn.execute("SELECT * FROM turns WHERE turn_hash=?", (turn,)).fetchone()
            if row and (row["project_hash"], row["task_hash"], row["role"]) != (
                    project, task, role):
                self._limited(turn, "scope_conflict")
                return None
            if row is None:
                self.conn.execute(
                    "INSERT INTO turns(turn_hash,project_hash,task_hash,role,created,updated,"
                    "health_epoch) VALUES(?,?,?,?,?,?,?)",
                    (turn, project, task, role, time.time(), time.time(), epoch))
                self.conn.execute(
                    "DELETE FROM turns WHERE turn_hash IN (SELECT turn_hash FROM turns "
                    "ORDER BY created DESC,turn_hash LIMIT -1 OFFSET ?)", (MAX_TURNS,))
            event = value["event"]
            if row is None and event != "UserPromptSubmit":
                self._limited(turn, "missing_start")
            if epoch < current:
                self._limited(turn, "observer_gap")
            if event == "UserPromptSubmit":
                if row is not None and row["ended"] != "active":
                    if not row["started"]:
                        self._limited(turn, "late_start")
                    return None
                if row is not None and not row["started"]:
                    self._limited(turn, "late_start")
                self.conn.execute("UPDATE turns SET started=1 WHERE turn_hash=?", (turn,))
            elif event == "Incomplete":
                self._limited(turn, value.get("issue_code", "stream_gap"))
            elif event in {"Stop", "Interrupt"}:
                ended = "stopped" if event == "Stop" else "aborted"
                self.conn.execute(
                    "UPDATE turns SET ended=CASE WHEN ended='aborted' THEN ended ELSE ? END "
                    "WHERE turn_hash=?", (ended, turn))
            elif event in {"PreToolUse", "PostToolUse", "CompletedExecution"}:
                call = self.conn.execute(
                    "SELECT * FROM calls WHERE turn_hash=? AND call_hash=?",
                    (turn, value["call_hash"])).fetchone()
                if call is None:
                    size = self.conn.execute("SELECT COUNT(*) FROM calls WHERE turn_hash=?",
                                             (turn,)).fetchone()[0]
                    if size >= MAX_CALLS:
                        self._limited(turn, "call_limit")
                        return None
                    self.conn.execute(
                        "INSERT INTO calls(turn_hash,call_hash,input_hash,kind,capability,is_check)"
                        "VALUES(?,?,?,?,?,?)", (turn, value["call_hash"], value["input_hash"],
                                               value["kind"], value["capability"],
                                               int(value["is_check"])))
                    if event == "PostToolUse":
                        self._limited(turn, "missing_pre")
                else:
                    mismatch = (value["has_input"] and value["has_name"] and (
                        call["input_hash"] != value["input_hash"] or (
                                    call["kind"], call["capability"], bool(call["is_check"])) != (
                                        value["kind"], value["capability"], value["is_check"])))
                    if mismatch or (event in {"PostToolUse", "CompletedExecution"}
                                    and call["response_hash"] is not None):
                        if mismatch or call["response_hash"] != value.get("response_hash"):
                            self._limited(turn, "conflicting_event")
                        return None
                if row is not None and row["ended"] != "active":
                    self._limited(turn, "late_call")
                if event in {"PostToolUse", "CompletedExecution"}:
                    failure_hash = value["failure_hash"]
                    if value["failure_basis"] == "input" and call is not None:
                        failure_hash = stable_hash(["failure-v1", value["error_class"],
                                                    call["input_hash"]])
                    order = self.conn.execute(
                        "SELECT COALESCE(MAX(completed_order),0)+1 FROM calls WHERE turn_hash=?",
                        (turn,)).fetchone()[0]
                    self.conn.execute(
                        "UPDATE calls SET response_hash=?,outcome=?,failure_hash=?,error_class=?,"
                        "completed_order=? WHERE turn_hash=? AND call_hash=?",
                        (value["response_hash"], value["outcome"], failure_hash,
                         value["error_class"], order, turn, value["call_hash"]))
            calls = self._calls(turn)
            state = self.conn.execute("SELECT * FROM turns WHERE turn_hash=?", (turn,)).fetchone()
            pending = self.conn.execute(
                "SELECT 1 FROM calls WHERE turn_hash=? AND outcome='pending' LIMIT 1", (turn,)
            ).fetchone()
            sample = check_sample(calls, ended=state["ended"], limited=bool(
                state["limited"] or pending or not state["started"]))
            self.conn.execute(
                "UPDATE turns SET completed_calls=?,check_sample=?,updated=? WHERE turn_hash=?",
                (len(calls), int(sample), time.time(), turn))
            if (event not in {"PostToolUse", "CompletedExecution"}
                    or state["ended"] != "active" or state["limited"]):
                return None
            history = [dict(row) for row in self.conn.execute(
                "SELECT completed_calls,check_sample FROM turns WHERE project_hash=? "
                "AND role=? AND turn_hash<>?", (project, role, turn))]
            message = loop_warning(calls, baseline(history), state["warnings"],
                                   state["last_warning"])
            if message:
                self.conn.execute(
                    "UPDATE turns SET warnings=warnings+1,last_warning=? WHERE turn_hash=?",
                    (sum(call["kind"] != "observer" for call in calls), turn))
            return message


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = sqlite3.connect(str(path), timeout=1.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        try:
            self._enable_wal()
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=1000")
            self.conn.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except BaseException:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    def _enable_wal(self) -> None:
        # Changing journal mode can return BUSY immediately when simultaneous
        # first-open connections try to upgrade their locks. busy_timeout alone
        # does not resolve that race. Established WAL stores only need a read.
        deadline = time.monotonic() + 1.0
        delay = 0.01
        while True:
            try:
                if self.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                    return
                if self.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise ValueError("ledger requires WAL journal mode")
                return
            except sqlite3.OperationalError as exc:
                code = getattr(exc, "sqlite_errorcode", None)
                # Python 3.10 lacks sqlite_errorcode; match only SQLite's BUSY
                # label there. I/O, corruption and other errors must propagate.
                busy = (code & 0xFF == 5 if code is not None
                        else str(exc) == "database is locked")
                remaining = deadline - time.monotonic()
                if not busy or remaining <= 0:
                    raise
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, 0.08)

    def _migrate(self) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        row = (
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if exists
            else None
        )
        # Old retained hook versions rewrite meta on every connection. SQLite's
        # user_version survives those writes and prevents repeating a completed migration.
        version = max(
            int(row[0]) if row else 0, int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        )
        if version > SCHEMA_VERSION:
            raise ValueError("ledger was created by a newer Run Budget version")
        if version == SCHEMA_VERSION:
            return
        if version:
            backup_root = self.path.parent / "backups"
            backup_root.mkdir(exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(
                prefix=f"ledger-v{version}-", suffix=".sqlite3", dir=backup_root
            )
            os.close(fd)
            deadline = time.monotonic() + 1.0

            def progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() > deadline:
                    raise TimeoutError("ledger backup timeout")

            target = sqlite3.connect(name)
            try:
                self.conn.backup(target, pages=128, progress=progress, sleep=0.01)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("ledger backup validation failed")
            finally:
                target.close()
        migration_bytes = get_data("codex_run_budget", "migrations/002_hardening.sql")
        if migration_bytes is None:
            raise ValueError("ledger migration resource is unavailable")
        migration = migration_bytes.decode("utf-8")
        self.conn.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                epoch INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active','halted','off')),
                max_tokens INTEGER NOT NULL,
                warn_ratio REAL NOT NULL,
                block_agents_ratio REAL NOT NULL,
                max_tool_calls INTEGER NOT NULL,
                max_agents INTEGER NOT NULL,
                max_in_flight INTEGER NOT NULL,
                max_tool_output_chars INTEGER NOT NULL,
                repeat_steer INTEGER NOT NULL,
                repeat_halt INTEGER NOT NULL,
                fail_closed INTEGER NOT NULL,
                spent_tokens INTEGER NOT NULL DEFAULT 0,
                tool_calls INTEGER NOT NULL DEFAULT 0,
                in_flight INTEGER NOT NULL DEFAULT 0,
                active_agents INTEGER NOT NULL DEFAULT 0,
                last_fingerprint TEXT,
                repeat_count INTEGER NOT NULL DEFAULT 0,
                halt_reason TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                run_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                total_tokens INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                reasoning_output_tokens INTEGER NOT NULL,
                agent_id TEXT,
                agent_type TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (run_id, epoch, source_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                run_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                tool_use_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('admitted','completed','blocked','expired')),
                reason TEXT,
                output_chars INTEGER,
                admitted_at REAL NOT NULL,
                completed_at REAL,
                PRIMARY KEY (run_id, epoch, tool_use_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS subagents (
                run_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                source_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('active','stopped')),
                started_at REAL NOT NULL,
                stopped_at REAL,
                PRIMARY KEY (run_id, epoch, agent_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                at REAL NOT NULL,
                kind TEXT NOT NULL,
                source_id TEXT,
                agent_id TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS events_run_epoch_idx
                ON events(run_id, epoch, id);
            CREATE INDEX IF NOT EXISTS tool_calls_lease_idx
                ON tool_calls(run_id, epoch, status, admitted_at);
            """
            + migration
            + f"""
            INSERT INTO meta(key,value) VALUES('schema_version','{SCHEMA_VERSION}')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value;
            PRAGMA user_version={SCHEMA_VERSION};
            COMMIT;
            """
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _event(
        self,
        run_id: str,
        epoch: int,
        kind: str,
        payload: dict[str, Any],
        source_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO events(run_id,epoch,at,kind,source_id,agent_id,payload_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (run_id, epoch, time.time(), kind, source_id, agent_id, safe_json(payload)),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._row(
            self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        )
        if run is not None:
            health = self.conn.execute(
                "SELECT state,reason FROM source_health WHERE run_id=? AND epoch=?",
                (run_id, run["epoch"]),
            ).fetchall()
            issues = sorted(
                {
                    r["reason"] or r["state"]
                    for r in health
                    if r["state"] in ("unavailable", "regressed")
                }
            )
            run["usage_issues"] = issues
            known_source = self.conn.execute(
                "SELECT 1 FROM sources WHERE run_id=? AND epoch=? LIMIT 1",
                (run_id, run["epoch"]),
            ).fetchone()
            run["usage_status"] = (
                "unavailable"
                if issues
                else (
                    "pending"
                    if (not health and not known_source)
                    or any(r["state"] == "pending" for r in health)
                    else "ok"
                )
            )
            run["pending_agents"] = self._pending_agents(run_id, int(run["epoch"]))
        return run

    def _pending_agents(self, run_id: str, epoch: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM agent_slots WHERE run_id=? AND epoch=? AND status='pending'",
                (run_id, epoch),
            ).fetchone()[0]
        )

    def _health(
        self, run_id: str, epoch: int, source_id: str, state: str, reason: str | None = None
    ) -> None:
        previous = self.conn.execute(
            "SELECT state,reason FROM source_health WHERE run_id=? AND epoch=? AND source_id=?",
            (run_id, epoch, source_id),
        ).fetchone()
        if previous is not None and previous["state"] == state and previous["reason"] == reason:
            return
        self.conn.execute(
            "INSERT INTO source_health VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(run_id,epoch,source_id) DO UPDATE SET state=excluded.state,"
            "reason=excluded.reason,updated_at=excluded.updated_at",
            (run_id, epoch, source_id, state, reason, time.time()),
        )
        self._event(
            run_id,
            epoch,
            "usage_health",
            {"state": state, "reason": reason},
            source_id=source_id,
        )

    def start_run(
        self,
        run_id: str,
        config: RunConfig,
        source_id: str | None,
        usage: Usage | None,
    ) -> dict[str, Any]:
        now = time.time()
        with self.transaction():
            old = self.conn.execute(
                "SELECT epoch,created_at FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            epoch = int(old["epoch"]) + 1 if old else 1
            created_at = float(old["created_at"]) if old else now
            values = asdict(config)
            self.conn.execute(
                """
                INSERT INTO runs(
                    run_id,epoch,status,max_tokens,warn_ratio,block_agents_ratio,
                    max_tool_calls,max_agents,max_in_flight,max_tool_output_chars,
                    repeat_steer,repeat_halt,fail_closed,spent_tokens,tool_calls,
                    in_flight,active_agents,last_fingerprint,repeat_count,halt_reason,
                    created_at,updated_at
                ) VALUES(?,?,'active',?,?,?,?,?,?,?,?,?,?,0,0,0,0,NULL,0,NULL,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    epoch=excluded.epoch,status='active',max_tokens=excluded.max_tokens,
                    warn_ratio=excluded.warn_ratio,
                    block_agents_ratio=excluded.block_agents_ratio,
                    max_tool_calls=excluded.max_tool_calls,max_agents=excluded.max_agents,
                    max_in_flight=excluded.max_in_flight,
                    max_tool_output_chars=excluded.max_tool_output_chars,
                    repeat_steer=excluded.repeat_steer,repeat_halt=excluded.repeat_halt,
                    fail_closed=excluded.fail_closed,spent_tokens=0,tool_calls=0,
                    in_flight=0,active_agents=0,last_fingerprint=NULL,repeat_count=0,
                    halt_reason=NULL,updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    epoch,
                    values["max_tokens"],
                    values["warn_ratio"],
                    values["block_agents_ratio"],
                    values["max_tool_calls"],
                    values["max_agents"],
                    values["max_in_flight"],
                    values["max_tool_output_chars"],
                    values["repeat_steer"],
                    values["repeat_halt"],
                    int(values["fail_closed"]),
                    created_at,
                    now,
                ),
            )
            if source_id:
                self._upsert_source(run_id, epoch, source_id, usage or Usage())
                self._health(run_id, epoch, source_id, "ok" if usage is not None else "pending")
            self._event(run_id, epoch, "run_started", {"config": values})
        return self.get_run(run_id) or {}

    def _upsert_source(
        self,
        run_id: str,
        epoch: int,
        source_id: str,
        usage: Usage,
        agent_id: str | None = None,
        agent_type: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sources(
                run_id,epoch,source_id,total_tokens,input_tokens,cached_input_tokens,
                output_tokens,reasoning_output_tokens,agent_id,agent_type,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,epoch,source_id) DO UPDATE SET
                total_tokens=excluded.total_tokens,input_tokens=excluded.input_tokens,
                cached_input_tokens=excluded.cached_input_tokens,
                output_tokens=excluded.output_tokens,
                reasoning_output_tokens=excluded.reasoning_output_tokens,
                agent_id=COALESCE(excluded.agent_id,sources.agent_id),
                agent_type=COALESCE(excluded.agent_type,sources.agent_type),
                updated_at=excluded.updated_at
            """,
            (
                run_id,
                epoch,
                source_id,
                usage.total,
                usage.input,
                usage.cached_input,
                usage.output,
                usage.reasoning_output,
                agent_id,
                agent_type,
                time.time(),
            ),
        )

    def sync_usage(
        self,
        run_id: str,
        source_id: str | None,
        usage: Usage | None,
        issue: str | None = None,
        recovered_source: str | None = None,
    ) -> dict[str, Any] | None:
        source_id = source_id or "unknown"
        with self.transaction():
            run_row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run_row is None or run_row["status"] == "off":
                return self._row(run_row)
            epoch = int(run_row["epoch"])
            prior_row = self.conn.execute(
                "SELECT * FROM sources WHERE run_id=? AND epoch=? AND source_id=?",
                (run_id, epoch, source_id),
            ).fetchone()
            if prior_row is None:
                prior = Usage()
            else:
                prior = Usage(
                    total=int(prior_row["total_tokens"]),
                    input=int(prior_row["input_tokens"]),
                    cached_input=int(prior_row["cached_input_tokens"]),
                    output=int(prior_row["output_tokens"]),
                    reasoning_output=int(prior_row["reasoning_output_tokens"]),
                )
            if usage is None:
                pending = issue == "pending" and prior.total == 0
                self._health(
                    run_id,
                    epoch,
                    source_id,
                    "pending" if pending else "unavailable",
                    None if pending else (issue or "missing_usage"),
                )
                return self.get_run(run_id)
            if any(
                getattr(usage, k) < getattr(prior, k)
                for k in ("total", "input", "cached_input", "output", "reasoning_output")
            ):
                self._health(run_id, epoch, source_id, "regressed", "counter_regressed")
                return self.get_run(run_id)
            self._health(run_id, epoch, source_id, "ok")
            if recovered_source is not None and recovered_source != source_id:
                self.conn.execute(
                    "DELETE FROM source_health WHERE run_id=? AND epoch=? AND source_id=?",
                    (run_id, epoch, recovered_source),
                )
            delta = usage.delta(prior)
            # Replayed cumulative observations still recheck health and limits
            # atomically, but must not create a durable write on every hook.
            if prior_row is None or usage != prior:
                self._upsert_source(run_id, epoch, source_id, usage)
            if delta.total:
                self.conn.execute(
                    "UPDATE runs SET spent_tokens=spent_tokens+?,updated_at=? WHERE run_id=?",
                    (delta.total, time.time(), run_id),
                )
                self._event(
                    run_id,
                    epoch,
                    "usage_observed",
                    {
                        "delta": asdict(delta),
                        "cumulative_source": asdict(usage),
                        "source_reset": False,
                    },
                    source_id=source_id,
                )
            current = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if (
                current
                and current["status"] == "active"
                and current["spent_tokens"] >= current["max_tokens"]
            ):
                reason = (
                    f"token budget exhausted: {current['spent_tokens']:,}/"
                    f"{current['max_tokens']:,} observed tokens"
                )
                self._halt_locked(run_id, epoch, reason, "token_budget")
        return self.get_run(run_id)

    def _halt_locked(
        self,
        run_id: str,
        epoch: int,
        reason: str,
        policy: str,
        detail_hash: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE runs SET status='halted',halt_reason=?,updated_at=? WHERE run_id=?",
            (reason[:500], time.time(), run_id),
        )
        payload = {"policy": policy, "reason": reason[:500]}
        if detail_hash:
            payload["detail_hash"] = detail_hash
        self._event(run_id, epoch, "halt", payload)

    def halt(
        self,
        run_id: str,
        reason: str,
        policy: str = "operator",
        detail_hash: str | None = None,
    ) -> dict[str, Any] | None:
        with self.transaction():
            row = self.conn.execute("SELECT epoch FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            self._halt_locked(run_id, int(row["epoch"]), reason, policy, detail_hash)
        return self.get_run(run_id)

    def resume(self, run_id: str, max_tokens: int | None = None) -> dict[str, Any] | None:
        with self.transaction():
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            new_max = int(max_tokens if max_tokens is not None else row["max_tokens"])
            if new_max <= int(row["spent_tokens"]):
                raise ValueError("resume token ceiling must exceed observed spend")
            self.conn.execute(
                "UPDATE runs SET status='active',max_tokens=?,halt_reason=NULL,updated_at=? "
                "WHERE run_id=?",
                (new_max, time.time(), run_id),
            )
            self._event(run_id, int(row["epoch"]), "resume", {"max_tokens": new_max})
        return self.get_run(run_id)

    def disable(self, run_id: str) -> dict[str, Any] | None:
        with self.transaction():
            row = self.conn.execute("SELECT epoch FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE runs SET status='off',in_flight=0,active_agents=0,updated_at=? "
                "WHERE run_id=?",
                (time.time(), run_id),
            )
            self.conn.execute(
                "UPDATE agent_slots SET status='released',updated_at=? "
                "WHERE run_id=? AND epoch=? AND status='pending'",
                (time.time(), run_id, int(row["epoch"])),
            )
            self._event(run_id, int(row["epoch"]), "disabled", {})
        return self.get_run(run_id)

    def _expire_leases(self, run_id: str, epoch: int) -> int:
        cutoff = time.time() - LEASE_SECONDS
        expired_slots = self.conn.execute(
            "UPDATE agent_slots SET status='expired',updated_at=? WHERE run_id=? AND epoch=? "
            "AND status='pending' AND created_at<?",
            (time.time(), run_id, epoch, cutoff),
        ).rowcount
        if expired_slots:
            self._event(run_id, epoch, "agent_slots_expired", {"count": expired_slots})
        rows = self.conn.execute(
            "SELECT tool_use_id FROM tool_calls WHERE run_id=? AND epoch=? "
            "AND status='admitted' AND admitted_at<?",
            (run_id, epoch, cutoff),
        ).fetchall()
        if not rows:
            return 0
        self.conn.execute(
            "UPDATE tool_calls SET status='expired',reason='lease expired',completed_at=? "
            "WHERE run_id=? AND epoch=? AND status='admitted' AND admitted_at<?",
            (time.time(), run_id, epoch, cutoff),
        )
        self.conn.execute(
            "UPDATE runs SET in_flight=MAX(0,in_flight-?),updated_at=? WHERE run_id=?",
            (len(rows), time.time(), run_id),
        )
        self._event(run_id, epoch, "leases_expired", {"count": len(rows)})
        return len(rows)

    def admit_tool(
        self,
        run_id: str,
        source_id: str,
        tool_use_id: str,
        tool_name: str,
        input_hash: str,
    ) -> Decision:
        with self.transaction():
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row["status"] == "off":
                return Decision(True, run=self._row(row))
            epoch = int(row["epoch"])
            self._expire_leases(run_id, epoch)
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            existing = self.conn.execute(
                "SELECT * FROM tool_calls WHERE run_id=? AND epoch=? AND tool_use_id=?",
                (run_id, epoch, tool_use_id),
            ).fetchone()
            if existing is not None and row["status"] != "halted":
                allowed = existing["status"] in ("admitted", "completed")
                return Decision(allowed, existing["reason"], run=self._row(row))

            if row["status"] == "halted":
                return self._block_tool(
                    row, source_id, tool_use_id, tool_name, input_hash, row["halt_reason"]
                )
            if int(row["spent_tokens"]) >= int(row["max_tokens"]):
                reason = "token budget exhausted"
                self._halt_locked(run_id, epoch, reason, "token_budget")
                row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)
            if int(row["tool_calls"]) >= int(row["max_tool_calls"]):
                reason = f"tool-call ceiling reached ({row['max_tool_calls']})"
                self._halt_locked(run_id, epoch, reason, "tool_call_cap")
                row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)
            if int(row["in_flight"]) >= int(row["max_in_flight"]):
                reason = (
                    f"in-flight call ceiling reached ({row['max_in_flight']}); "
                    "retry after a call completes"
                )
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)

            ratio = int(row["spent_tokens"]) / max(1, int(row["max_tokens"]))
            if tool_name in AGENT_TOOLS and (
                int(row["active_agents"]) + self._pending_agents(run_id, epoch)
                >= int(row["max_agents"])
            ):
                reason = f"active and pending subagent ceiling reached ({row['max_agents']})"
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)
            if tool_name in AGENT_TOOLS and ratio >= float(row["block_agents_ratio"]):
                reason = (
                    "STEER: new subagents are disabled near the token ceiling; "
                    "finish from current evidence"
                )
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)

            repeat_count = (
                int(row["repeat_count"]) + 1 if row["last_fingerprint"] == input_hash else 1
            )
            if tool_name in WAIT_TOOLS:
                repeat_count = 1
            if repeat_count >= int(row["repeat_halt"]):
                reason = f"repeated identical tool call detected ({repeat_count} times)"
                self.conn.execute(
                    "UPDATE runs SET last_fingerprint=?,repeat_count=? WHERE run_id=?",
                    (input_hash, repeat_count, run_id),
                )
                self._halt_locked(run_id, epoch, reason, "progress_guard")
                row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                return self._block_tool(row, source_id, tool_use_id, tool_name, input_hash, reason)

            now = time.time()
            self.conn.execute(
                "INSERT INTO tool_calls(run_id,epoch,tool_use_id,source_id,tool_name,"
                "input_hash,status,admitted_at) "
                "VALUES(?,?,?,?,?,?,'admitted',?)",
                (run_id, epoch, tool_use_id, source_id, tool_name[:200], input_hash, now),
            )
            if tool_name in AGENT_TOOLS:
                self.conn.execute(
                    "INSERT INTO agent_slots(run_id,epoch,tool_use_id,status,"
                    "created_at,updated_at) "
                    "VALUES(?,?,?,'pending',?,?)",
                    (run_id, epoch, tool_use_id, now, now),
                )
            self.conn.execute(
                "UPDATE runs SET tool_calls=tool_calls+1,in_flight=in_flight+1,last_fingerprint=?,"
                "repeat_count=?,updated_at=? WHERE run_id=?",
                (input_hash, repeat_count, now, run_id),
            )
            self._event(
                run_id,
                epoch,
                "tool_admitted",
                {"tool": tool_name[:200], "repeat_count": repeat_count},
                source_id=source_id,
            )
            row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            contexts: list[str] = []
            if ratio >= float(row["warn_ratio"]):
                contexts.append(self._steer_text(row))
            if repeat_count >= int(row["repeat_steer"]):
                contexts.append(
                    f"Progress guard: this exact tool call has repeated {repeat_count} times. "
                    "Check whether results or external state changed; avoid unchanged retries."
                )
            return Decision(
                True, additional_context="\n".join(contexts) or None, run=self._row(row)
            )

    def _block_tool(
        self,
        run: sqlite3.Row,
        source_id: str,
        tool_use_id: str,
        tool_name: str,
        input_hash: str,
        reason: str | None,
    ) -> Decision:
        reason = (reason or "run halted")[:500]
        self.conn.execute(
            "INSERT OR IGNORE INTO tool_calls(run_id,epoch,tool_use_id,source_id,"
            "tool_name,input_hash,"
            "status,reason,admitted_at) VALUES(?,?,?,?,?,?,'blocked',?,?)",
            (
                run["run_id"],
                run["epoch"],
                tool_use_id,
                source_id,
                tool_name[:200],
                input_hash,
                reason,
                time.time(),
            ),
        )
        self._event(
            run["run_id"],
            int(run["epoch"]),
            "tool_blocked",
            {"tool": tool_name[:200], "reason": reason},
            source_id=source_id,
        )
        return Decision(False, reason=reason, run=self._row(run))

    @staticmethod
    def _steer_text(run: sqlite3.Row | dict[str, Any]) -> str:
        spent = int(run["spent_tokens"])
        maximum = int(run["max_tokens"])
        remaining = max(0, maximum - spent)
        return (
            f"Run budget STEER: {spent:,}/{maximum:,} observed tokens used; {remaining:,} remain. "
            "Finish from current evidence, avoid new subagents and broad searches, "
            "and keep tool output targeted."
        )

    def complete_tool(
        self,
        run_id: str,
        tool_use_id: str,
        output_chars: int,
        output_hash: str | None = None,
        failed: bool = False,
    ) -> Decision:
        with self.transaction():
            run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] == "off":
                return Decision(True, run=self._row(run))
            epoch = int(run["epoch"])
            call = self.conn.execute(
                "SELECT * FROM tool_calls WHERE run_id=? AND epoch=? AND tool_use_id=?",
                (run_id, epoch, tool_use_id),
            ).fetchone()
            if call is not None and call["status"] == "admitted":
                if output_hash is not None:
                    previous = self.conn.execute(
                        "SELECT output_hash FROM tool_results WHERE run_id=? AND epoch=? "
                        "AND source_id=? AND input_hash=? ORDER BY at DESC,rowid DESC LIMIT 1",
                        (run_id, epoch, call["source_id"], call["input_hash"]),
                    ).fetchone()
                    self.conn.execute(
                        "INSERT INTO tool_results VALUES(?,?,?,?,?,?,?)",
                        (
                            run_id,
                            epoch,
                            tool_use_id,
                            call["source_id"],
                            call["input_hash"],
                            output_hash,
                            time.time(),
                        ),
                    )
                    if (
                        previous is not None
                        and previous["output_hash"] != output_hash
                        and run["last_fingerprint"] == call["input_hash"]
                    ):
                        self.conn.execute(
                            "UPDATE runs SET repeat_count=1 WHERE run_id=?",
                            (run_id,),
                        )
                        self._event(
                            run_id,
                            epoch,
                            "repeat_progress",
                            {"evidence": "output_changed"},
                            source_id=call["source_id"],
                        )
                if failed and call["tool_name"] in AGENT_TOOLS:
                    self.conn.execute(
                        "UPDATE agent_slots SET status='released',updated_at=? "
                        "WHERE run_id=? AND epoch=? AND tool_use_id=? AND status='pending'",
                        (time.time(), run_id, epoch, tool_use_id),
                    )
                self.conn.execute(
                    "UPDATE tool_calls SET status='completed',output_chars=?,completed_at=? "
                    "WHERE run_id=? AND epoch=? AND tool_use_id=?",
                    (output_chars, time.time(), run_id, epoch, tool_use_id),
                )
                self.conn.execute(
                    "UPDATE runs SET in_flight=MAX(0,in_flight-1),updated_at=? WHERE run_id=?",
                    (time.time(), run_id),
                )
                self._event(
                    run_id,
                    epoch,
                    "tool_completed",
                    {"tool": call["tool_name"], "output_chars": output_chars},
                    source_id=call["source_id"],
                )
            run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if output_chars > int(run["max_tool_output_chars"]):
                reason = (
                    f"Tool output was {output_chars:,} characters, above the "
                    f"{run['max_tool_output_chars']:,} limit. Save large output to a file "
                    "and return only a focused summary."
                )
                return Decision(False, reason=reason, additional_context=reason, run=self._row(run))
            ratio = int(run["spent_tokens"]) / max(1, int(run["max_tokens"]))
            context = self._steer_text(run) if ratio >= float(run["warn_ratio"]) else None
            return Decision(True, additional_context=context, run=self._row(run))

    def subagent_start(self, run_id: str, agent_id: str, agent_type: str) -> Decision:
        with self.transaction():
            run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] == "off":
                return Decision(True, run=self._row(run))
            epoch = int(run["epoch"])
            self._expire_leases(run_id, epoch)
            old = self.conn.execute(
                "SELECT status FROM subagents WHERE run_id=? AND epoch=? AND agent_id=?",
                (run_id, epoch, agent_id),
            ).fetchone()
            if old is None:
                reservation = self.conn.execute(
                    "SELECT tool_use_id FROM agent_slots WHERE run_id=? AND epoch=? "
                    "AND status='pending' ORDER BY created_at,tool_use_id LIMIT 1",
                    (run_id, epoch),
                ).fetchone()
                if reservation is not None:
                    self.conn.execute(
                        "UPDATE agent_slots SET status='started',agent_id=?,updated_at=? "
                        "WHERE run_id=? AND epoch=? AND tool_use_id=?",
                        (agent_id, time.time(), run_id, epoch, reservation["tool_use_id"]),
                    )
                self.conn.execute(
                    "INSERT INTO subagents(run_id,epoch,agent_id,agent_type,status,started_at) "
                    "VALUES(?,?,?,?, 'active',?)",
                    (run_id, epoch, agent_id, agent_type[:200], time.time()),
                )
                self.conn.execute(
                    "UPDATE runs SET active_agents=active_agents+1,updated_at=? WHERE run_id=?",
                    (time.time(), run_id),
                )
                self._event(
                    run_id,
                    epoch,
                    "subagent_started",
                    {"agent_type": agent_type[:200]},
                    agent_id=agent_id,
                )
            run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if int(run["active_agents"]) > int(run["max_agents"]) and run["status"] == "active":
                self._halt_locked(
                    run_id, epoch, "unreserved subagent exceeded active ceiling", "unreserved_agent"
                )
                run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run["status"] == "halted":
                return Decision(False, reason=run["halt_reason"], run=self._row(run))
            ratio = int(run["spent_tokens"]) / max(1, int(run["max_tokens"]))
            context = self._steer_text(run) if ratio >= float(run["warn_ratio"]) else None
            return Decision(True, additional_context=context, run=self._row(run))

    def subagent_stop(
        self,
        run_id: str,
        agent_id: str,
        source_id: str | None,
        agent_type: str,
    ) -> dict[str, Any] | None:
        with self.transaction():
            run = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["status"] == "off":
                return self._row(run)
            epoch = int(run["epoch"])
            old = self.conn.execute(
                "SELECT status FROM subagents WHERE run_id=? AND epoch=? AND agent_id=?",
                (run_id, epoch, agent_id),
            ).fetchone()
            if old is not None and old["status"] == "active":
                self.conn.execute(
                    "UPDATE subagents SET status='stopped',source_id=?,stopped_at=? "
                    "WHERE run_id=? AND epoch=? AND agent_id=?",
                    (source_id, time.time(), run_id, epoch, agent_id),
                )
                self.conn.execute(
                    "UPDATE runs SET active_agents=MAX(0,active_agents-1),updated_at=? "
                    "WHERE run_id=?",
                    (time.time(), run_id),
                )
                self._event(
                    run_id,
                    epoch,
                    "subagent_stopped",
                    {"agent_type": agent_type[:200]},
                    source_id=source_id,
                    agent_id=agent_id,
                )
            elif old is None:
                # A delayed start event must not resurrect an already stopped agent.
                self.conn.execute(
                    "INSERT INTO subagents(run_id,epoch,agent_id,agent_type,status,started_at,"
                    "stopped_at) VALUES(?,?,?,?,'stopped',?,?)",
                    (run_id, epoch, agent_id, agent_type[:200], time.time(), time.time()),
                )
        return self.get_run(run_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [dict(row) for row in rows]

    def events(self, run_id: str, epoch: int | None = None) -> list[dict[str, Any]]:
        if epoch is None:
            run = self.get_run(run_id)
            if not run:
                return []
            epoch = int(run["epoch"])
        rows = self.conn.execute(
            "SELECT id,run_id,epoch,at,kind,source_id,agent_id,payload_json "
            "FROM events WHERE run_id=? AND epoch=? ORDER BY id",
            (run_id, epoch),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result
