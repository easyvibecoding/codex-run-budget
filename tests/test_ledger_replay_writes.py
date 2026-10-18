"""Identical observations do not generate redundant durable ledger writes."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-run-budget/lib"))

from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.ledger import RunConfig  # noqa: E402
from codex_run_budget.transcript import Usage  # noqa: E402


class LedgerReplayWritesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        governor = Governor(Path(temporary.name))
        self.addCleanup(governor.close)
        self.ledger = governor.ledger
        self.usage = Usage(total=120, input=90, cached_input=10, output=30)
        self.ledger.start_run("synthetic-run", RunConfig(1000), "synthetic-source", Usage())
        self.sync(self.usage)

    def sync(self, usage, issue=None):
        return self.ledger.sync_usage("synthetic-run", "synthetic-source", usage, issue)

    def test_identical_usage_and_health_do_not_write(self):
        changes = self.ledger.conn.total_changes
        for _ in range(24):
            self.assertEqual(self.sync(self.usage)["spent_tokens"], 120)
        self.assertEqual(self.ledger.conn.total_changes, changes)

    def test_identical_failure_is_read_only_but_recovery_is_recorded(self):
        self.assertEqual(self.sync(None, "missing_usage")["usage_status"], "unavailable")
        changes = self.ledger.conn.total_changes
        self.sync(None, "missing_usage")
        self.assertEqual(self.ledger.conn.total_changes, changes)
        self.assertEqual(self.sync(self.usage)["usage_status"], "ok")
        self.assertGreater(self.ledger.conn.total_changes, changes)
        self.assertEqual(self.ledger.get_run("synthetic-run")["spent_tokens"], 120)

    def test_changed_component_with_same_total_is_recorded_once(self):
        changed = Usage(total=120, input=90, cached_input=15, output=30)
        changes = self.ledger.conn.total_changes
        self.sync(changed)
        self.assertGreater(self.ledger.conn.total_changes, changes)
        source = self.ledger.conn.execute("SELECT * FROM sources").fetchone()
        self.assertEqual(source["cached_input_tokens"], 15)
        changes = self.ledger.conn.total_changes
        self.sync(changed)
        self.assertEqual(self.ledger.conn.total_changes, changes)
        self.assertEqual(self.ledger.get_run("synthetic-run")["spent_tokens"], 120)
