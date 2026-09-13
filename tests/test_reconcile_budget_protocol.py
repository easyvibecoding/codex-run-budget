"""Background completion reporting never enters or changes budget policy."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_auto_report  # noqa: F401 - adds the repository runtime path
from codex_run_budget import hook_adapter
from codex_run_budget.governor import Governor


class ReconcileBudgetProtocolTest(unittest.TestCase):
    def invoke(self, args, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        output = io.StringIO()
        with (patch.object(sys, "argv", ["hook.py", *args]),
              patch.object(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw))),
              redirect_stdout(output)):
            status = hook_adapter.main()
        return status, output.getvalue()

    def test_worker_never_dispatches_budget_or_outputs_a_decision(self):
        payload = {"session_id": "example-task", "turn_id": "example-turn",
                   "transcript_path": "/example/synthetic.jsonl"}
        with (patch.object(Governor, "dispatch") as dispatch,
              patch("codex_run_budget.reconcile.worker", return_value={"status": "partial"})
              as worker):
            self.assertEqual(self.invoke(["--reconcile", "--data-dir", "/example/data"], payload),
                             (0, ""))
            dispatch.assert_not_called()
            worker.assert_called_once_with(payload, Path("/example/data"), home=None)

    def test_worker_failure_and_invalid_input_are_silent_and_report_only(self):
        with (patch.object(Governor, "dispatch") as dispatch,
              patch("codex_run_budget.reconcile.worker", side_effect=OSError)):
            for raw in (b"invalid-json", b"[]", b"{}", b"x" * (2 * 1024 * 1024 + 1)):
                with self.subTest(length=len(raw)):
                    self.assertEqual(self.invoke(["--reconcile"], raw), (0, ""))
            self.assertEqual(self.invoke(["--reconcile", "--event", "Stop"], {}), (0, ""))
            dispatch.assert_not_called()

    def test_background_launch_failure_preserves_all_stop_policy_fields(self):
        payload = {"session_id": "example-task", "hook_event_name": "Stop"}
        decisions = ({"continue": False, "stopReason": "HALT", "systemMessage": "budget"},
                     {"systemMessage": "STEER"}, None)
        for decision in decisions:
            with (self.subTest(decision=decision),
                  patch.object(Governor, "dispatch", return_value=decision) as dispatch,
                  patch("codex_run_budget.reconcile.schedule", side_effect=OSError) as schedule):
                status, output = self.invoke(["--event", "Stop"], payload)
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output) if output else None, decision)
                dispatch.assert_called_once_with(payload)
                schedule.assert_called_once()

    def test_admission_denials_never_schedule_completion_work(self):
        for event, decision in (
            ("UserPromptSubmit", {"decision": "block", "reason": "HALT"}),
            ("PreToolUse", {"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny"}}),
        ):
            with (self.subTest(event=event),
                  patch.object(Governor, "dispatch", return_value=decision),
                  patch("codex_run_budget.reconcile.schedule") as schedule):
                status, output = self.invoke(["--event", event], {
                    "session_id": "example-task", "hook_event_name": event})
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output), decision)
                schedule.assert_not_called()

    def test_actual_unqueued_worker_does_not_create_governance_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(self.invoke(["--reconcile", "--data-dir", str(root)], {
                "session_id": "example-task", "turn_id": "example-turn",
                "transcript_path": str(root / "synthetic.jsonl")}), (0, ""))
            self.assertFalse((root / "ledger.sqlite3").exists())
            self.assertFalse((root / "active").exists())


if __name__ == "__main__":
    unittest.main()
