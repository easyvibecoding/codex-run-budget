"""Synthetic remote and private queue tests for paired review."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))
from codex_run_budget import hook_adapter, paired_review  # noqa: E402


class PairedReviewTest(unittest.TestCase):
    def setUp(self):
        notification = patch.object(paired_review, "_notify", lambda source, status: None)
        notification.start()
        self.addCleanup(notification.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "private"
        self.projects = []
        for name in ("left", "right"):
            bare = self.root / f"{name}.git"
            project = self.root / name
            self.git("init", "--bare", "-b", "main", str(bare))
            self.git("clone", str(bare), str(project))
            self.git("-C", str(project), "config", "user.name", "Synthetic Tester")
            self.git("-C", str(project), "config", "user.email", "tester@example.invalid")
            (project / "README.md").write_text("baseline\n")
            self.git("-C", str(project), "add", "README.md")
            self.git("-C", str(project), "commit", "-m", "synthetic baseline")
            self.git("-C", str(project), "push", "origin", "main")
            self.projects.append(project)
        paired_review.configure(self.data, *self.projects)

    @staticmethod
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout.strip()

    def state(self):
        return json.loads((self.data / "paired-review-state.json").read_text())

    def advance(self, index=0):
        project = self.projects[index]
        (project / "README.md").write_text("changed\n")
        self.git("-C", str(project), "add", "README.md")
        self.git("-C", str(project), "commit", "-m", "synthetic change")
        self.git("-C", str(project), "push", "origin", "main")
        return self.git("-C", str(project), "rev-parse", "HEAD")

    def test_remote_advance_queues_one_opposite_review(self):
        self.assertTrue(all(row["status"] == "unchanged" for row in
                            paired_review.scan(self.data)))
        baseline = self.state()["cursors"]["left"]
        head = self.advance()
        result = paired_review.scan(self.data)
        self.assertEqual(result[0]["status"], "detected")
        pending = self.state()["pending"]["left"]
        self.assertEqual((pending["base"], pending["head"], pending["destination"]),
                         (baseline, head, "right"))
        self.assertEqual(self.state()["cursors"]["left"], baseline)
        prompt = paired_review.prompt_for(self.data, "left")
        self.assertIn(head, prompt)
        self.assertIn("read-only review", prompt)
        self.assertEqual(paired_review.scan(self.data)[0]["status"], "pending-review")

    def test_dispatch_and_resolution_store_only_hashed_task_id(self):
        head = self.advance()
        paired_review.scan(self.data)
        paired_review.reserve_pending(self.data, "left", head)
        with self.assertRaises(ValueError):
            paired_review.reserve_pending(self.data, "left", head)
        task_id = "synthetic-native-task-id"
        paired_review.mark_dispatched(self.data, "left", head, task_id)
        state = self.state()
        self.assertEqual(state["pending"]["left"]["task_hash"],
                         hashlib.sha256(task_id.encode()).hexdigest()[:16])
        self.assertNotIn(task_id, json.dumps(state))
        paired_review.resolve_pending(self.data, "left", "no-alignment-needed")
        self.assertEqual(self.state()["cursors"]["left"], head)
        self.assertEqual(self.state()["pending"], {})
        self.assertEqual(paired_review.scan(self.data)[0]["status"], "unchanged")

    def test_uncertain_dispatch_is_not_duplicated(self):
        head = self.advance()
        paired_review.scan(self.data)
        paired_review.reserve_pending(self.data, "left", head)
        self.assertEqual(self.state()["pending"]["left"]["status"], "dispatching")
        self.assertEqual(paired_review.scan(self.data)[0]["status"], "pending-review")
        with self.assertRaises(ValueError):
            paired_review.reserve_pending(self.data, "left", head)
        paired_review.retry_pending(self.data, "left")
        self.assertEqual(paired_review.scan(self.data)[0]["status"], "detected")

    def test_unavailable_remote_keeps_cursor(self):
        before = self.state()
        with patch.object(paired_review, "_fetch_head", side_effect=OSError("offline")):
            self.assertTrue(all(row["status"] == "remote-unavailable" for row in
                                paired_review.scan(self.data)))
        self.assertEqual(self.state(), before)

    def test_stop_hook_is_silent_until_exact_project_changes(self):
        payload = {"hook_event_name": "Stop", "cwd": str(self.projects[0]),
                   "stop_hook_active": False}
        self.assertIsNone(paired_review.stop_decision(self.data, payload))
        head = self.advance()
        # A source Task Stop uses only the local origin/main tracking ref.
        decision = paired_review.stop_decision(self.data, payload)
        self.assertEqual(decision["decision"], "block")
        self.assertIn(head, decision["reason"])
        self.assertEqual(self.state()["pending"]["left"]["destination"], "right")
        self.assertIsNone(paired_review.stop_decision(
            self.data, {**payload, "stop_hook_active": True}))
        self.assertIsNone(paired_review.stop_decision(
            self.data, {**payload, "cwd": str(self.root)}))

    def test_stop_hook_does_not_repeat_after_reservation(self):
        head = self.advance()
        payload = {"hook_event_name": "Stop", "cwd": str(self.projects[0])}
        self.assertEqual(paired_review.stop_decision(self.data, payload)["decision"], "block")
        paired_review.reserve_pending(self.data, "left", head)
        self.assertIsNone(paired_review.stop_decision(self.data, payload))

    def test_stop_hook_accepts_worktree_of_configured_project(self):
        worktree = self.root / "isolated" / "left"
        worktree.parent.mkdir()
        self.git("-C", str(self.projects[0]), "worktree", "add", "--detach", str(worktree))
        head = self.advance()
        result = paired_review.stop_decision(
            self.data, {"hook_event_name": "Stop", "cwd": str(worktree)})
        self.assertEqual(result["decision"], "block")
        self.assertIn(head, result["reason"])

    def test_receiving_review_task_does_not_dispatch_another_review(self):
        first_head = self.advance(0)
        second_head = self.advance(1)
        paired_review.scan(self.data)
        paired_review.reserve_pending(self.data, "left", first_head)
        paired_review.mark_dispatched(self.data, "left", first_head,
                                      "synthetic-review-session")
        result = paired_review.stop_decision(self.data, {
            "hook_event_name": "Stop", "cwd": str(self.projects[1]),
            "session_id": "synthetic-review-session"})
        self.assertIsNone(result)
        self.assertEqual(self.state()["pending"]["right"]["head"], second_head)
        with patch.object(paired_review, "_is_agent_created_task", return_value=True):
            self.assertIsNone(paired_review.stop_decision(self.data, {
                "hook_event_name": "Stop", "cwd": str(self.projects[1]),
                "session_id": "different-native-session"}))

    def test_stop_hook_adapter_preserves_budget_output_and_adds_review(self):
        self.advance()
        payload = {"hook_event_name": "Stop", "session_id": "synthetic-session",
                   "cwd": str(self.projects[0]), "stop_hook_active": False}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()))
        stdout = io.StringIO()
        with (patch.object(sys, "argv", ["hook", "--event", "Stop"]),
              patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout),
              patch.object(hook_adapter.Governor, "dispatch",
                           return_value={"systemMessage": "budget unchanged"}),
              patch("codex_run_budget.reconcile.schedule"),
              patch("codex_run_budget.util.data_path", return_value=self.data)):
            self.assertEqual(hook_adapter.main(), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["systemMessage"], "budget unchanged")


if __name__ == "__main__":
    unittest.main()
