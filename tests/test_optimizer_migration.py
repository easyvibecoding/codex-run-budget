"""Disposable version-1 observations: backup, atomic upgrade and bounded recovery."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-run-budget/lib"))

from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.ledger import OptimizationLedger  # noqa: E402
from codex_run_budget.optimization_cli import report  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402


class OptimizerMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "optimizer.sqlite3"
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript("""
                CREATE TABLE settings(enabled INTEGER NOT NULL);
                CREATE TABLE turns (
                    turn_hash TEXT PRIMARY KEY,project_hash TEXT,task_hash TEXT,role TEXT,
                    created REAL,updated REAL,ended TEXT DEFAULT 'active',
                    started INTEGER DEFAULT 0,limited INTEGER DEFAULT 0,
                    warnings INTEGER DEFAULT 0,last_warning INTEGER DEFAULT 0,
                    completed_calls INTEGER DEFAULT 0,check_sample INTEGER DEFAULT 0
                );
                CREATE TABLE calls (
                    turn_hash TEXT,call_hash TEXT,input_hash TEXT,response_hash TEXT,kind TEXT,
                    capability TEXT,is_check INTEGER,outcome TEXT,failure_hash TEXT,
                    error_class TEXT,
                    completed_order INTEGER,PRIMARY KEY(turn_hash,call_hash)
                );
                PRAGMA user_version=1;
            """)
            conn.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (stable_hash("synthetic-turn"), stable_hash(str(self.root)),
                          stable_hash("synthetic-task"), "task", 1, 2, "stopped", 1, 0, 1, 8, 1, 1))
            conn.commit()
        finally:
            conn.close()

    def test_v1_upgrade_preserves_history_and_verified_backup_before_marking_coverage(self):
        governor = Governor(self.root)
        try:
            governor.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
                             "session_id": "synthetic-task", "turn_id": "synthetic-new"})
        finally:
            governor.close()
        value = report(self.root, self.root)
        self.assertEqual(value["advisories"], 1)
        self.assertEqual(value["coverage_issues"], {"legacy_coverage": 1})
        self.assertEqual(value["baselines"]["task"]["samples"], 0)
        backups = list((self.root / "backups").glob("optimizer-v1-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        conn = sqlite3.connect(backups[0])
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT warnings,check_sample FROM turns").fetchone(),
                             (1, 1))
        finally:
            conn.close()
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_missing_migration_resource_keeps_original_schema_and_rows(self):
        with patch("codex_run_budget.ledger.get_data", return_value=None):
            with self.assertRaises(ValueError):
                OptimizationLedger(self.path)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT warnings,check_sample FROM turns").fetchone(),
                             (1, 1))
        finally:
            conn.close()
        # Read-only reports identify unverified legacy coverage without migrating it.
        self.assertEqual(report(self.root, self.root)["baselines"]["task"]["samples"], 0)

    def test_concurrent_openers_recheck_the_locked_schema_before_altering(self):
        def open_ledger(_):
            ledger = OptimizationLedger(self.path)
            try:
                return ledger.conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                ledger.close()

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(list(pool.map(open_ledger, range(6))), [2] * 6)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
