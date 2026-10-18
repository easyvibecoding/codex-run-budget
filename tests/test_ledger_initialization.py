"""First-open journal races; all connections point at disposable databases."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-run-budget/lib"))

from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.ledger import Ledger  # noqa: E402


class LedgerInitializationTest(unittest.TestCase):
    def test_peer_wal_transition_retries_then_reads_completed_mode(self):
        real_connect = sqlite3.connect
        transitions = []

        class RacingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql == "PRAGMA journal_mode=WAL":
                    transitions.append(sql)
                    if len(transitions) == 1:
                        raise sqlite3.OperationalError("database is locked")
                return super().execute(sql, *args)

        def connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=RacingConnection)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            with patch("codex_run_budget.ledger.sqlite3.connect", side_effect=connect):
                ledger = Ledger(path)
                ledger.close()
                reopened = Ledger(path)
                reopened.close()
            self.assertEqual(len(transitions), 2)

    def test_non_busy_initialization_error_is_not_retried(self):
        real_connect = sqlite3.connect
        errors = []
        connections = []

        class BrokenConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if "journal_mode" in sql:
                    errors.append(sql)
                    raise sqlite3.OperationalError("disk I/O error")
                return super().execute(sql, *args)

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=BrokenConnection)
            connections.append(connection)
            return connection

        with tempfile.TemporaryDirectory() as directory:
            with patch("codex_run_budget.ledger.sqlite3.connect", side_effect=connect):
                with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O"):
                    Ledger(Path(directory) / "ledger.sqlite3")
            self.assertEqual(len(errors), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                connections[0].execute("SELECT 1")

    def test_busy_deadline_keeps_admission_fail_closed(self):
        real_connect = sqlite3.connect

        class BusyConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if "journal_mode" in sql:
                    raise sqlite3.OperationalError("database is locked")
                return super().execute(sql, *args)

        def connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=BusyConnection)

        with tempfile.TemporaryDirectory() as directory:
            with patch("codex_run_budget.ledger.sqlite3.connect", side_effect=connect), \
                    patch("codex_run_budget.ledger.time.monotonic", side_effect=[0, 2]):
                result = Governor.dispatch({"hook_event_name": "PreToolUse",
                                            "session_id": "synthetic-busy"}, Path(directory))
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("OperationalError", result["systemMessage"])

    def test_24_simultaneous_first_opens_and_schema_initialization(self):
        for _ in range(10):
            with tempfile.TemporaryDirectory() as directory:
                gate = threading.Barrier(24)

                def open_governor(_):
                    gate.wait(timeout=10)
                    governor = Governor(Path(directory))
                    try:
                        self.assertFalse(governor.ledger.conn.in_transaction)
                        return governor.handle({"hook_event_name": "PreToolUse",
                                                "session_id": "synthetic-init"})
                    finally:
                        governor.close()

                with ThreadPoolExecutor(24) as pool:
                    self.assertEqual(list(pool.map(open_governor, range(24))), [None] * 24)
                with sqlite3.connect(Path(directory) / "ledger.sqlite3") as db:
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
