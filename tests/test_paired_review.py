"""Synthetic remote and private queue tests for paired review."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
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
        count = self.git("-C", str(project), "rev-list", "--count", "HEAD")
        (project / "README.md").write_text(f"changed after {count} commits\n")
        self.git("-C", str(project), "add", "README.md")
        self.git("-C", str(project), "commit", "-m", "synthetic change")
        self.git("-C", str(project), "push", "origin", "main")
        return self.git("-C", str(project), "rev-parse", "HEAD")

    def extra_project(self, name):
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
        return project

    def test_named_pairs_can_share_a_source_with_isolated_state(self):
        third = self.extra_project("third")
        with patch.object(paired_review, "_registered_codex_project", return_value=True):
            result = paired_review.configure_pair(self.data, "left-third",
                                                  self.projects[0], third)
        self.assertEqual(result["pair"], "left-third")
        self.assertFalse(paired_review.list_pairs(self.data)["pairs"][1]["enabled"])
        self.assertEqual(paired_review.scan(self.data)[-1]["status"], "pair-disabled")
        paired_review.set_pair_enabled(self.data, "left-third", True)
        head = self.advance()
        findings = paired_review.scan(self.data)
        self.assertEqual({(row["pair"], row["destination"]) for row in findings
                          if row["status"] == "detected"},
                         {("default", "right"), ("left-third", "third")})
        decision = paired_review.stop_decision(self.data, {
            "hook_event_name": "Stop", "cwd": str(self.projects[0]),
            "session_id": "synthetic-shared-source", "turn_id": "synthetic-turn"})
        self.assertEqual(decision["decision"], "block")
        self.assertIn("Pair default:", decision["reason"])
        self.assertIn("Pair left-third:", decision["reason"])
        self.assertIn("--pair left-third", decision["reason"])
        self.assertEqual(self.state()["pending"]["left"]["head"], head)
        named = json.loads((self.data / paired_review.PAIR_DIR / "left-third" /
                            "paired-review-state.json").read_text())
        self.assertEqual(named["pending"]["left"]["head"], head)
        paired_review.reserve_pending(self.data, "left", head, "left-third")
        paired_review.mark_dispatched(self.data, "left", head, "synthetic-third-task",
                                      "left-third")
        paired_review.resolve_pending(self.data, "left", "no-alignment-needed",
                                      "left-third")
        self.assertEqual(self.state()["cursors"]["left"],
                         self.git("-C", str(self.projects[0]), "rev-list", "--max-parents=0",
                                  "HEAD"))
        named = json.loads((self.data / paired_review.PAIR_DIR / "left-third" /
                            "paired-review-state.json").read_text())
        self.assertEqual(named["cursors"]["left"], head)

    def test_experimental_and_pair_switches_preserve_queued_state(self):
        new_root = self.root / "new-private"
        with patch.object(paired_review, "_registered_codex_project", return_value=True):
            paired_review.configure_pair(new_root, "web-api", *self.projects)
        self.assertFalse(paired_review.list_pairs(new_root)["enabled"])
        self.assertEqual(paired_review.scan(new_root)[0]["status"],
                         "experimental-disabled")
        paired_review.set_feature(new_root, True)
        self.assertEqual(paired_review.scan(new_root)[0]["status"], "pair-disabled")
        paired_review.set_pair_enabled(new_root, "web-api", True)
        head = self.advance()
        self.assertEqual(paired_review.scan(new_root)[0]["status"], "detected")
        before = (new_root / paired_review.PAIR_DIR / "web-api" /
                  "paired-review-state.json").read_bytes()
        paired_review.set_feature(new_root, False)
        self.assertIsNone(paired_review.stop_decision(new_root, {
            "hook_event_name": "Stop", "cwd": str(self.projects[0]),
            "session_id": "synthetic-session"}))
        self.assertEqual(paired_review.scan(new_root)[0]["status"],
                         "experimental-disabled")
        self.assertEqual((new_root / paired_review.PAIR_DIR / "web-api" /
                          "paired-review-state.json").read_bytes(), before)
        paired_review.set_feature(new_root, True)
        paired_review.set_pair_enabled(new_root, "web-api", False)
        self.assertEqual(paired_review.scan(new_root)[0]["status"], "pair-disabled")
        paired_review.set_pair_enabled(new_root, "web-api", True)
        self.assertEqual(paired_review.scan(new_root)[0]["status"], "pending-review")
        self.assertEqual(json.loads(before)["pending"]["left"]["head"], head)

    def test_named_pair_needs_two_registered_roots_and_unique_edge(self):
        third = self.extra_project("third")
        with patch.object(paired_review, "_registered_codex_project", return_value=False):
            with self.assertRaisesRegex(ValueError, "registered Codex project roots"):
                paired_review.configure_pair(self.data, "new-edge", self.projects[0], third)
        with patch.object(paired_review, "_registered_codex_project", return_value=True):
            with self.assertRaisesRegex(ValueError, "already paired"):
                paired_review.configure_pair(self.data, "duplicate",
                                             self.projects[1], self.projects[0])
            with self.assertRaisesRegex(ValueError, "reserved"):
                paired_review.configure_pair(self.data, "default", self.projects[0], third)
            with self.assertRaisesRegex(ValueError, "lowercase slug"):
                paired_review.configure_pair(self.data, "../bad", self.projects[0], third)

    def test_catalog_check_uses_exact_registered_codex_root(self):
        database = self.root / "projects-synthetic.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE project_roots (project_id TEXT, path TEXT)")
            connection.execute("INSERT INTO project_roots VALUES (?,?)",
                               ("synthetic-project", str(self.projects[0])))
        with patch("codex_run_budget.exec_activity._native",
                   return_value=sqlite3.connect(database)):
            self.assertTrue(paired_review._registered_codex_project(
                str(self.projects[0])))
        with patch("codex_run_budget.exec_activity._native",
                   side_effect=lambda _: sqlite3.connect(database)):
            self.assertFalse(paired_review._registered_codex_project(
                str(self.projects[1])))

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
        with patch.object(paired_review, "_is_receiving_review_task", return_value=True):
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

    def test_only_named_receiving_task_is_excluded(self):
        database = self.root / "native-synthetic.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE threads (id TEXT, thread_source TEXT, name TEXT)")
            connection.executemany("INSERT INTO threads VALUES (?,?,?)", [
                ("review", "agent_created_thread", "Review counterpart changes: left abc1234"),
                ("alternate-review", "agent_created_thread", "Review left paired change abc1234"),
                ("ordinary", "agent_created_thread", "Verify paired review Stop hook"),
            ])

        def native(_home):
            return sqlite3.connect(database)

        with patch("codex_run_budget.exec_activity._native", native):
            self.assertTrue(paired_review._is_receiving_review_task("review"))
            self.assertTrue(paired_review._is_receiving_review_task("alternate-review"))
            self.assertFalse(paired_review._is_receiving_review_task("ordinary"))

    def test_bound_tasks_relay_once_per_turn_without_echo_or_new_task(self):
        head = self.advance()
        source_id = "synthetic-source-task"
        destination_id = "synthetic-destination-task"
        source_stop = {"hook_event_name": "Stop", "cwd": str(self.projects[0]),
                       "session_id": source_id, "turn_id": "first-source-turn"}
        self.assertEqual(paired_review.stop_decision(self.data, source_stop)["decision"],
                         "block")
        paired_review.reserve_pending(self.data, "left", head)
        paired_review.mark_dispatched(self.data, "left", head, destination_id)
        state = self.state()
        self.assertEqual(len(state["bindings"]), 1)
        self.assertNotIn(source_id, json.dumps(state))
        self.assertNotIn(destination_id, json.dumps(state))
        self.assertEqual(state["bindings"][0]["tasks"], {
            "left": paired_review._task_hash(source_id),
            "right": paired_review._task_hash(destination_id),
        })
        paired_review.resolve_pending(self.data, "left", "no-alignment-needed")

        def resolve(task_hash):
            return {paired_review._task_hash(source_id): source_id,
                    paired_review._task_hash(destination_id): destination_id}.get(task_hash)

        with patch.object(paired_review, "_native_task_for_hash", side_effect=resolve):
            receiver_stop = {"hook_event_name": "Stop", "cwd": str(self.projects[1]),
                             "session_id": destination_id, "turn_id": "review-turn"}
            decision = paired_review.stop_decision(self.data, receiver_stop)
            self.assertEqual(decision["decision"], "block")
            self.assertIn(source_id, decision["reason"])
            self.assertIsNone(paired_review.stop_decision(self.data, receiver_stop))
            paired_review.mark_relay_sent(self.data, "right", destination_id, "review-turn")
            self.assertIsNone(paired_review.stop_decision(self.data, {
                **source_stop, "turn_id": "inbound-source-turn"}))
            self.assertIsNone(paired_review.stop_decision(self.data, {
                **source_stop, "turn_id": "inbound-source-turn"}))

            second_head = self.advance()
            fresh_stop = {**source_stop, "turn_id": "new-source-turn"}
            decision = paired_review.stop_decision(self.data, fresh_stop)
            self.assertEqual(decision["decision"], "block")
            self.assertIn(destination_id, decision["reason"])
            self.assertIn(second_head, decision["reason"])
            self.assertEqual(len(self.state()["bindings"]), 1)
            paired_review.mark_relay_sent(self.data, "left", source_id,
                                          "new-source-turn")
            self.assertEqual(self.state()["pending"]["left"]["status"], "dispatched")
            self.assertIsNone(paired_review.stop_decision(self.data, {
                **receiver_stop, "turn_id": "inbound-review-turn"}))

    def test_hook_continuation_consumes_inbound_echo_guard(self):
        head = self.advance()
        source_id = "synthetic-source-task"
        destination_id = "synthetic-destination-task"
        source_stop = {"hook_event_name": "Stop", "cwd": str(self.projects[0]),
                       "session_id": source_id, "turn_id": "initial-turn"}
        paired_review.stop_decision(self.data, source_stop)
        paired_review.reserve_pending(self.data, "left", head)
        paired_review.mark_dispatched(self.data, "left", head, destination_id)
        with patch.object(paired_review, "_native_task_for_hash", return_value=source_id):
            paired_review.stop_decision(self.data, {
                "hook_event_name": "Stop", "cwd": str(self.projects[1]),
                "session_id": destination_id, "turn_id": "receiver-turn"})
        paired_review.mark_relay_sent(self.data, "right", destination_id,
                                      "receiver-turn")
        binding = self.state()["bindings"][0]
        self.assertTrue(binding["relay"]["left"]["suppress_next_stop"])
        self.assertIsNone(paired_review.stop_decision(self.data, {
            **source_stop, "stop_hook_active": True}))
        binding = self.state()["bindings"][0]
        self.assertFalse(binding["relay"]["left"]["suppress_next_stop"])
        with patch.object(paired_review, "_native_task_for_hash",
                          return_value=destination_id):
            decision = paired_review.stop_decision(self.data, {
                **source_stop, "turn_id": "later-independent-turn"})
        self.assertEqual(decision["decision"], "block")


if __name__ == "__main__":
    unittest.main()
