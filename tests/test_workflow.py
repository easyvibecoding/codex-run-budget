from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))
from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.workflow import (  # noqa: E402
    HEADER_BYTES,
    TAIL_BYTES,
    WorkflowObserver,
    render,
)
from test_report import TASK_A, TASK_B, event  # noqa: E402


def counter(total, stamp=1000):
    return event(
        stamp,
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": total // 2,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total,
                }
            },
        },
    )


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.data = self.root / "data"
        self.database = self.home / "state_5.sqlite"
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY,name TEXT,title TEXT,"
            "agent_nickname TEXT,agent_role TEXT,agent_path TEXT,source TEXT,"
            "updated_at INT,rollout_path TEXT)"
        )
        self.paths = {}
        for identity, parent, name, nickname in (
            (TASK_A, None, "驗證工作流", None),
            (TASK_B, TASK_A, None, "Curie"),
        ):
            path = self.home / f"rollout-{identity}.jsonl"
            self.paths[identity] = path
            source = (
                {"subagent": {"thread_spawn": {"parent_thread_id": parent}}} if parent else "vscode"
            )
            path.write_text(
                json.dumps(event(999, "session_meta", {"id": identity, "source": source})) + "\n"
            )
            self.append(
                identity,
                event(999, "event_msg", {"type": "task_started", "turn_id": "t"}),
                counter(1000),
            )
            connection.execute(
                "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    name,
                    "PRIVATE PROMPT",
                    nickname,
                    "worker" if parent else None,
                    "/root/helper" if parent else None,
                    json.dumps(source),
                    1000,
                    str(path),
                ),
            )
        connection.commit()
        connection.close()
        self.observer = WorkflowObserver(self.data, self.home)

    def append(self, identity, *records):
        with self.paths[identity].open("a") as output:
            for row in records:
                output.write(json.dumps(row) + "\n")

    def capture(self, **kwargs):
        return self.observer.capture([TASK_A], now=1100, **kwargs)

    def test_exact_scope_no_survey_and_native_names_and_private_storage(self):
        before = self.database.read_bytes()
        self.append(
            TASK_A,
            event(
                1001,
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec",
                    "arguments": "PRIVATE COMMAND AND SECRET",
                },
            ),
        )
        with patch("codex_run_budget.survey.survey_transcripts", side_effect=AssertionError):
            result = self.capture()
        self.assertEqual(result["selected_tasks"], 1)
        self.assertEqual(result["tasks"][0]["display_name"], "驗證工作流")
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["live_status"], "not_queried")
        self.assertEqual(result["workflow_acceptance"], "not_evaluated")
        self.assertEqual(before, self.database.read_bytes())
        stored = (self.data / "workflow-observations/observations.sqlite3").read_bytes()
        for secret in ("PRIVATE", TASK_A, str(self.paths[TASK_A])):
            self.assertNotIn(secret.encode(), stored)
        self.assertEqual(
            (self.data / "workflow-observations/observations.sqlite3").stat().st_mode & 0o777, 0o600
        )

    def test_unchanged_cursor_comparison_reads_less_and_append_delta(self):
        self.append(TASK_A, event(1001, "response_item", {"text": "unused" * 10000}), counter(1100))
        first = self.capture()
        second = self.capture(after=first["cursor"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["observed_token_delta"], 0)
        self.assertLess(second["scan_bytes"], first["scan_bytes"])
        self.append(
            TASK_A,
            counter(1300, 1002),
            event(1003, "event_msg", {"type": "task_complete", "turn_id": "t"}),
        )
        third = self.capture(after=second["cursor"])
        self.assertTrue(third["changed"])
        self.assertEqual(third["observed_token_delta"], 200)
        self.assertEqual(third["changes"][0]["last_lifecycle"], "task_complete")
        self.assertEqual(third["workflow_acceptance"], "not_evaluated")

    def test_descendants_deduplicate_and_limits_and_cursor_scope(self):
        result = self.capture(include_agents=True)
        self.assertEqual(result["selected_tasks"], 2)
        child = result["tasks"][1]
        self.assertEqual(child["parent_name"], "驗證工作流")
        self.assertEqual(child["root_name"], "驗證工作流")
        self.assertIn("Curie", render(result))
        capped = self.capture(include_agents=True, limit=1)
        self.assertTrue(capped["selection_limited"])
        both = self.observer.capture([TASK_A, TASK_B], include_agents=True, now=1100)
        self.assertEqual(both["selected_tasks"], 2)
        with self.assertRaises(ValueError):
            self.capture(after=result["cursor"])
        with self.assertRaises(ValueError):
            self.capture(after="bad")

    def test_gap_reset_truncation_and_missing_sources_do_not_fabricate_delta(self):
        first = self.capture()
        self.append(
            TASK_A, event(1001, "response_item", {"text": "x" * (TAIL_BYTES + 1000)}), counter(2000)
        )
        gap = self.capture(after=first["cursor"])
        self.assertIsNone(gap["observed_token_delta"])
        self.assertLessEqual(gap["scan_bytes"], HEADER_BYTES + TAIL_BYTES + 8193)
        self.append(TASK_A, counter(100), counter(2500))
        reset = self.capture(after=gap["cursor"])
        self.assertIsNone(reset["observed_token_delta"])
        self.assertTrue(reset["tasks"][0]["observation"]["counter_discontinuity"])
        self.paths[TASK_A].write_text(json.dumps(event(999, "session_meta", {"id": TASK_A})) + "\n")
        truncated = self.capture(after=reset["cursor"])
        self.assertIsNone(truncated["observed_token_delta"])
        self.paths[TASK_A].unlink()
        missing = self.capture(after=truncated["cursor"])
        self.assertEqual(missing["tasks"][0]["observation"]["source_status"], "unavailable")

    def test_abort_old_evidence_and_resolved_signals_are_not_live_claims(self):
        self.append(
            TASK_A,
            event(1001, "event_msg", {"type": "turn_aborted", "turn_id": "t", "reason": "PRIVATE"}),
        )
        first = self.capture()
        self.assertTrue(any(s["kind"] == "abort_observed_check_native" for s in first["signals"]))
        later = self.observer.capture([TASK_A], now=3000, after=first["cursor"])
        self.assertIn("old_evidence_not_proof_of_stall", [s["kind"] for s in later["new_signals"]])
        self.append(TASK_A, event(2999, "event_msg", {"type": "task_complete", "turn_id": "t"}))
        resolved = self.observer.capture([TASK_A], now=3001, after=later["cursor"])
        self.assertEqual(len(resolved["cleared_signals"]), 2)
        self.assertEqual(resolved["live_status"], "not_queried")

    def test_symlinks_wrong_identity_partial_records_and_clock(self):
        first = self.capture()
        with self.assertRaises(ValueError):
            self.observer.capture([TASK_A], after=first["cursor"], now=1099)
        with self.paths[TASK_A].open("a") as stream:
            stream.write(json.dumps(counter(2000))[:-2])
        partial = self.capture(after=first["cursor"])
        self.assertEqual(partial["observed_token_delta"], 0)
        self.paths[TASK_A].write_text(json.dumps(event(999, "session_meta", {"id": TASK_B})) + "\n")
        self.assertEqual(
            self.capture()["tasks"][0]["observation"]["source_status"], "identity_mismatch"
        )
        self.paths[TASK_A].unlink()
        self.paths[TASK_A].symlink_to(self.paths[TASK_B])
        self.assertEqual(self.capture()["tasks"][0]["observation"]["source_status"], "unavailable")

    def test_cli_is_opt_in_compact_and_excludes_calling_task_from_native_wait(self):
        with (
            patch("codex_run_budget.workflow.WorkflowObserver.capture", side_effect=AssertionError),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["--data-dir", str(self.data), "workflow"]), 0)
        self.assertFalse(self.data.exists())
        args = [
            "--data-dir",
            str(self.data),
            "workflow",
            "observe",
            "--thread",
            TASK_A,
            "--codex-home",
            str(self.home),
        ]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args), 0)
        self.assertLess(len(output.getvalue()), 1500)
        self.assertIn("驗證工作流", output.getvalue())
        with (
            patch.dict(os.environ, {"CODEX_THREAD_ID": TASK_A}),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                main(
                    [
                        "workflow",
                        "targets",
                        "--thread",
                        TASK_A,
                        "--include-agents",
                        "--codex-home",
                        str(self.home),
                    ]
                ),
                0,
            )
        native = json.loads(output.getvalue())
        self.assertEqual(native["targets"], [{"threadId": TASK_B, "hostId": "local"}])
        self.assertTrue(native["calling_task_excluded"])
        self.assertFalse((self.data / "auto-report.json").exists())
        with redirect_stderr(io.StringIO()), patch.dict(os.environ, {"CODEX_THREAD_ID": ""}):
            self.assertEqual(main(["workflow", "observe"]), 2)

    def test_cursor_expiry_and_no_silent_new_baseline(self):
        with patch("codex_run_budget.workflow.MAX_SNAPSHOTS", 2):
            first = self.capture()
            second = self.observer.capture([TASK_A], now=1101, after=first["cursor"])
            self.observer.capture([TASK_A], now=1102, after=second["cursor"])
            with self.assertRaises(ValueError):
                self.observer.capture([TASK_A], now=1103, after=first["cursor"])


if __name__ == "__main__":
    unittest.main()
