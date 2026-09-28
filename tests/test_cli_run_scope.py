from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.governor import Governor  # noqa: E402


class CliRunScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "state"
        self.old = "synthetic-session-old"
        self.current = "synthetic-session-current"
        self._start(self.old)

    def _start(self, session: str) -> None:
        transcript = self.root / f"{session}.jsonl"
        transcript.write_text(
            json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 0,
                                      "output_tokens": 0, "reasoning_output_tokens": 0,
                                      "total_tokens": 100}
            }}}) + "\n",
            encoding="utf-8",
        )
        governor = Governor(self.ledger)
        try:
            result = governor.handle({
                "hook_event_name": "UserPromptSubmit",
                "session_id": session,
                "transcript_path": str(transcript),
                "prompt": "run-budget:start tokens=10k",
            })
            self.assertIn("Started a new governed epoch", json.dumps(result))
        finally:
            governor.close()

    def _run(self, *args: str, session: str | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {"CODEX_SESSION_ID": session} if session is not None else {
            "CODEX_SESSION_ID": ""
        }
        with (
            patch.dict("os.environ", environment),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = main(["--data-dir", str(self.ledger), *args])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_current_does_not_inherit_another_tasks_budget(self) -> None:
        status, output, error = self._run("show", "current", "--json", session=self.current)
        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output), {
            "scope": "current_session", "status": "not_configured"
        })
        self.assertNotIn(self.old, output)

        status, output, error = self._run("events", "current", session=self.current)
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("not configured", error)

    def test_latest_requires_explicit_cross_task_scope(self) -> None:
        for command, arguments in (
            ("show", ("latest",)),
            ("events", ("latest",)),
            ("off", ("latest",)),
            ("list", ()),
        ):
            status, output, error = self._run(command, *arguments, session=self.current)
            self.assertEqual(status, 2, command)
            self.assertEqual(output, "")
            self.assertIn("--all-tasks", error)
            self.assertNotIn(self.old, error)

        status, output, _ = self._run("list", "--all-tasks", session=self.current)
        self.assertEqual(status, 0)
        self.assertIn(self.old, output)

        status, output, _ = self._run(
            "show", "latest", "--all-tasks", "--json", session=self.current
        )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["scope"], "all_tasks_latest")
        self.assertEqual(json.loads(output)["run_id"], self.old)

        status, output, _ = self._run("show", self.old, "--json", session=self.current)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["run_id"], self.old)
        self.assertNotIn("scope", json.loads(output))

    def test_current_uses_exact_session_and_requires_identity(self) -> None:
        self._start(self.current)
        status, output, _ = self._run("show", "current", "--json", session=self.current)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["run_id"], self.current)
        self.assertEqual(json.loads(output)["scope"], "current_session")

        status, output, error = self._run("show", "current", "--json")
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("current session ID unavailable", error)


if __name__ == "__main__":
    unittest.main()
