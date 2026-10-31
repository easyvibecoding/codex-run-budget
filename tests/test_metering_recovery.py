"""Accounting recovery through normal hooks and the bounded reconciliation worker."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import test_auto_report as fixtures
from codex_run_budget.auto_report import _delta, handle, recent, snapshot
from codex_run_budget.governor import Governor
from codex_run_budget.reconcile import run, schedule
from codex_run_budget.util import stable_hash

TASK = "11111111-2222-4333-8444-555555555555"
TURN = "example-metering-turn"


class MeteringRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "synthetic-home"
        self.home.mkdir()
        self.data = self.root / "reports"
        self.path = self.home / "synthetic-source.jsonl"
        self.payload = {"session_id": TASK, "turn_id": TURN,
                        "transcript_path": str(self.path)}
        self.now = time.time()
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": TASK}})
                             + "\n" + json.dumps(fixtures.counter(1000)) + "\n"
                             + json.dumps(self.event("task_started")) + "\n")
        with closing(sqlite3.connect(self.home / "state_5.sqlite")) as db, db:
            db.execute("CREATE TABLE threads (id TEXT,name TEXT,agent_nickname TEXT,"
                       "agent_role TEXT,agent_path TEXT,source TEXT,rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES (?,?,NULL,NULL,NULL,?,?)",
                       (TASK, "Synthetic metering Task", "vscode", str(self.path)))
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home),
                                               "CODEX_RUN_BUDGET_HOME": str(self.data)})
        environment.start()
        self.addCleanup(environment.stop)
        self.key = stable_hash([TASK, TURN])

    def event(self, kind, **extra):
        return {"type": "event_msg", "timestamp": datetime.fromtimestamp(
            self.now, timezone.utc).isoformat(),
            "payload": {"type": kind, "turn_id": TURN, **extra}}

    def append(self, *records):
        with self.path.open("a") as output:
            for record in records:
                output.write(json.dumps(record) + "\n")

    def hook(self, kind, **extra):
        return handle({**self.payload, "hook_event_name": kind, **extra}, self.data,
                      home=self.home)

    def artifact(self, *, revised=False, extension="json"):
        suffix = ".reconciled." if revised else "."
        return self.data / "auto-reports" / (self.key + suffix + extension)

    def receipt(self, *, revised=False):
        return json.loads(self.artifact(revised=revised).read_text())

    def queued(self, **extra):
        with patch("codex_run_budget.reconcile.subprocess.Popen", return_value=Mock()):
            self.assertTrue(schedule({**self.payload, "hook_event_name": "Stop", **extra},
                                     self.data, home=self.home))

    def relocate(self, *, replace=False):
        target = self.home / "archived_sessions" / self.path.name
        target.parent.mkdir()
        if replace:
            target.write_bytes(self.path.read_bytes())
            self.path.unlink()
        else:
            self.path.rename(target)
        with closing(sqlite3.connect(self.home / "state_5.sqlite")) as db, db:
            db.execute("UPDATE threads SET rollout_path=? WHERE id=?", (str(target), TASK))
        self.path = target

    def test_governor_retains_unknown_and_reports_root_conflict_without_legacy_fallback(self):
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        self.assertIsNotNone(governor.handle({**self.payload,
                                             "hook_event_name": "UserPromptSubmit"}))
        record = fixtures.native_counter(TASK, TURN, 1500, request=500, turn_total=500)
        record["payload"]["root_turn_id"] = "example-other-task-root-turn"
        self.append(record, fixtures.counter(1500))
        response = governor.handle({**self.payload, "hook_event_name": "Stop"})
        self.assertNotIn("continue", response)
        self.assertNotIn("decision", response)
        receipt = self.receipt()
        self.assertIsNone(receipt["usage"])
        self.assertEqual(receipt["usage_status"], "counter_identity_conflict")
        self.assertEqual(receipt["counter_issues"], ["root_turn_identity_conflict"])
        self.assertTrue(receipt["source_identity_verified"])
        self.assertNotIn("example-other-task-root-turn", json.dumps(receipt))

    def test_fixed_conflict_stops_after_one_snapshot_and_preserves_stop_scope(self):
        self.hook("UserPromptSubmit")
        broken = fixtures.native_counter(TASK, TURN, 1500, request=500, turn_total=500)
        broken["payload"]["root_turn_id"] = "example-other-root-turn"
        self.append(broken, fixtures.counter(1500))
        self.hook("Stop")
        originals = {ext:self.artifact(extension=ext).read_bytes()
                     for ext in ("json", "md", "html")}
        self.queued()
        with patch("codex_run_budget.reconcile.snapshot", wraps=snapshot) as observe, \
                patch("codex_run_budget.reconcile.collect") as collect:
            result = run(self.payload, self.data, home=self.home, delays=(0,) * 8)
        self.assertEqual(result, {"status": "identity_conflict", "attempts": 1})
        self.assertEqual(observe.call_count, 1)
        collect.assert_not_called()
        revised = self.receipt(revised=True)
        self.assertEqual(revised["scope"], "user_turn_stop_boundary")
        self.assertEqual(revised["usage_status"], "counter_identity_conflict")
        self.assertFalse(revised["completion_observed"])
        self.assertFalse(revised["reconciliation_retryable"])
        self.assertIsNone(revised["usage"])
        self.assertEqual(revised["counter_issues"], ["root_turn_identity_conflict"])
        for ext,content in originals.items():
            self.assertEqual(self.artifact(extension=ext).read_bytes(), content)
        self.assertEqual(recent(self.data)[0]["report"], self.key + ".reconciled.md")
        self.assertIn("歸屬", self.artifact(revised=True, extension="md").read_text())
        self.assertFalse(schedule({**self.payload, "hook_event_name": "Stop"},
                                  self.data, home=self.home))
        self.assertEqual(run(self.payload, self.data, home=self.home, delays=(0,)),
                         {"status": "not_queued"})

    def test_late_conflict_after_stop_does_not_invent_completion_or_keep_scanning(self):
        self.hook("UserPromptSubmit")
        self.append(fixtures.counter(1200))
        self.hook("Stop")
        self.queued()
        self.assertEqual(self.receipt()["usage"]["total"], 200)
        record = fixtures.native_counter(TASK, TURN, 1500, request=500, turn_total=500)
        record["payload"]["session_id"] = "example-foreign-session"
        self.append(record, self.event("task_complete"))
        self.assertEqual(run(self.payload, self.data, home=self.home, delays=(0,) * 8),
                         {"status": "identity_conflict", "attempts": 1})
        self.assertEqual(self.receipt()["usage"]["total"], 200)
        self.assertIsNone(self.receipt(revised=True)["usage"])

    def test_missing_hook_paths_use_only_the_exact_catalog_task(self):
        self.assertIsNotNone(self.hook("UserPromptSubmit", transcript_path=None))
        self.append(fixtures.counter(1200))
        self.hook("Stop", transcript_path=None)
        receipt = self.receipt()
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertTrue(receipt["source_observations"]["exact_catalog"])
        self.queued(transcript_path=None)
        self.append(fixtures.native_counter(TASK, TURN, 1500, request=500, turn_total=500),
                    self.event("task_complete"))
        self.assertEqual(run({**self.payload, "transcript_path": None}, self.data,
                             home=self.home, delays=(0,))["status"], "complete")
        self.assertEqual(self.receipt(revised=True)["usage"]["total"], 500)

    def test_archive_move_between_start_and_stop_retains_original_baseline(self):
        self.hook("UserPromptSubmit")
        self.append(fixtures.counter(1200))
        baseline_db = self.data / "auto-reports/timing.sqlite3"
        with closing(sqlite3.connect(baseline_db)) as db:
            original = db.execute("SELECT baseline FROM turns WHERE key=?",
                                  (self.key,)).fetchone()[0]
        self.relocate()
        self.hook("Stop")  # The original hook path is now missing.
        receipt = self.receipt()
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertTrue(receipt["source_observations"]["relocated"])
        with closing(sqlite3.connect(baseline_db)) as db:
            self.assertEqual(db.execute("SELECT baseline FROM turns WHERE key=?",
                                        (self.key,)).fetchone()[0], original)
        self.assertNotIn(str(self.path), json.dumps(receipt))

    def test_archive_move_after_stop_can_reconcile_the_same_inode(self):
        self.hook("UserPromptSubmit")
        self.append(fixtures.counter(1200))
        self.hook("Stop")
        self.queued()
        self.relocate()
        self.append(fixtures.native_counter(TASK, TURN, 1500, request=500, turn_total=500),
                    self.event("task_complete"))
        result = run(self.payload, self.data, home=self.home, delays=(0,))
        self.assertEqual(result, {"status": "complete", "attempts": 1})
        self.assertTrue(self.receipt(revised=True)["source_observations"]["relocated"])
        self.assertEqual(self.receipt(revised=True)["usage"]["total"], 500)

    def test_catalog_replacement_with_same_task_header_cannot_replace_start_inode(self):
        self.hook("UserPromptSubmit")
        self.append(fixtures.counter(1200))
        self.relocate(replace=True)
        self.hook("Stop")
        self.assertIsNone(self.receipt()["usage"])
        self.assertFalse(self.receipt()["source_identity_verified"])
        self.assertEqual(self.receipt()["usage_status"], "source_identity_unavailable")
        self.assertEqual(self.receipt()["source_observations"]["stop"], "catalog_source_changed")

    def test_unavailable_file_identity_cannot_authorize_relocation(self):
        before = snapshot(str(self.path), TURN)
        after = {**before, "source_hash": "a" * 64,
                 "source_relocated_from_hash": before["source_hash"]}
        for inode in (None, 0, False):
            with self.subTest(inode=inode):
                self.assertEqual(_delta({**before, "inode":inode}, {**after, "inode":inode}),
                                 (None, "source_changed"))

    def test_existing_foreign_or_symlink_hook_source_is_not_replaced_by_catalog(self):
        for variant in ("foreign", "symlink", "malformed"):
            with self.subTest(variant=variant):
                # A separate turn avoids replacing a prior receipt.
                self.payload["turn_id"] = "example-" + variant + "-turn"
                self.key = stable_hash([TASK, self.payload["turn_id"]])
                self.hook("UserPromptSubmit")
                candidate = self.home / (variant + ".jsonl")
                if variant == "foreign":
                    candidate.write_text(json.dumps({"type":"session_meta", "payload":{
                        "id":"example-other-task"}}) + "\n"
                        + json.dumps(fixtures.counter(9000)) + "\n")
                elif variant == "symlink":
                    candidate.symlink_to(self.path)
                else:
                    candidate.write_text("invalid synthetic header\n")
                self.hook("Stop", transcript_path=str(candidate))
                self.assertIsNone(self.receipt()["usage"])
                self.assertFalse(self.receipt()["source_identity_verified"])
                self.assertFalse(self.receipt()["source_observations"]["exact_catalog"])

    def test_no_source_keeps_unknown_with_explicit_missing_path_diagnostics(self):
        self.path.unlink()
        self.hook("UserPromptSubmit", transcript_path=None)
        self.hook("Stop", transcript_path=None)
        self.assertIsNone(self.receipt()["usage"])
        self.assertEqual(self.receipt()["usage_status"], "source_identity_unavailable")
        self.assertEqual(self.receipt()["source_observations"]["start"], "path_unavailable")
        with patch("codex_run_budget.reconcile.subprocess.Popen") as spawn:
            self.assertFalse(schedule({**self.payload, "hook_event_name": "Stop",
                                       "transcript_path":None}, self.data, home=self.home))
        spawn.assert_not_called()
        dump = json.dumps(self.receipt())
        for value in (TASK, TURN, str(self.path)):
            self.assertNotIn(value, dump)
