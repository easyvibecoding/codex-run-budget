from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from .transcript import Usage
from .util import safe_json

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


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = sqlite3.connect(str(path), timeout=1.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=1000")
            self.conn.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except Exception:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

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
        migration = files("codex_run_budget").joinpath("migrations/002_hardening.sql").read_text()
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
        self.conn.execute(
            "INSERT INTO source_health VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(run_id,epoch,source_id) DO UPDATE SET state=excluded.state,"
            "reason=excluded.reason,updated_at=excluded.updated_at",
            (run_id, epoch, source_id, state, reason, time.time()),
        )
        if previous is None or previous["state"] != state or previous["reason"] != reason:
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
