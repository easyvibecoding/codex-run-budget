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
from codex_run_budget.util import stable_hash  # noqa: E402
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

    def tool(self, identity, call, *, code=1, command="example-check", owner=None):
        return event(1001, "event_msg", {
            "type": "item_completed", "thread_id": owner or identity, "turn_id": "t",
            "item": {"type": "CommandExecution", "id": call, "command": command,
                     "exit_code": code, "aggregated_output":
                     "Permission denied: EXAMPLE PRIVATE OUTPUT /example/private/input"}})

    def test_small_appends_read_only_the_new_complete_records(self):
        self.append(TASK_A, event(1001, "response_item", {"text":"x" * 200000}))
        first = self.capture()
        self.append(TASK_A, counter(1200, 1002))
        second = self.capture(after=first["cursor"])
        self.assertEqual(second["observed_token_delta"], 200)
        self.assertEqual(second["tasks"][0]["observation"]["read_mode"], "append")
        self.assertLess(second["scan_bytes"], 20000)
        self.assertLess(second["scan_bytes"] * 5, first["scan_bytes"])
        self.assertEqual(second["tasks"][0]["observation"]["lifecycle"]["kind"], "task_started")

    def test_partial_appended_record_is_folded_once_after_its_newline(self):
        first = self.capture()
        encoded = json.dumps(self.tool(TASK_A, "example-partial-call")) + "\n"
        with self.paths[TASK_A].open("a") as output:
            output.write(encoded[:100])
        partial = self.capture(after=first["cursor"])
        self.assertFalse(partial["tasks"][0]["observation"]["tool_evidence"].get("failures"))
        with self.paths[TASK_A].open("a") as output:
            output.write(encoded[100:])
        done = self.capture(after=partial["cursor"])
        state = done["tasks"][0]["observation"]["tool_evidence"]
        self.assertEqual(state["counts"]["failed"], 1)
        unchanged = self.capture(after=done["cursor"])
        self.assertEqual(unchanged["tasks"][0]["observation"]["tool_evidence"], state)

    def test_cross_task_failures_produce_read_only_response_plan_and_matching_recovery(self):
        for identity in (TASK_A, TASK_B):
            self.append(identity, *(self.tool(identity, f"example-failure-{n}") for n in range(3)))
        first = self.capture(include_agents=True)
        self.assertEqual(sum(s["kind"] == "cross_task_failure" for s in first["signals"]), 2)
        self.assertEqual(sum(s["kind"] == "repeated_tool_failure" for s in first["signals"]), 2)
        advice = next(r for r in first["response_plan"]
                      if r["action"] == "inspect_shared_dependency")
        self.assertEqual(advice["effects"], "read_only")
        self.assertEqual(advice["causality"], "unproven")
        self.append(TASK_A, self.tool(TASK_A, "example-recovered", code=0))
        recovered = self.capture(include_agents=True, after=first["cursor"])
        self.assertFalse(any(s["kind"] == "cross_task_failure" for s in recovered["signals"]))
        self.assertEqual(sum(s["kind"] == "tool_failure_observed"
                             for s in recovered["signals"]), 1)
        self.assertEqual(recovered["workflow_acceptance"], "not_evaluated")
        stored = (self.data / "workflow-observations/observations.sqlite3").read_bytes()
        for value in (b"EXAMPLE PRIVATE OUTPUT", b"example-check", TASK_A.encode()):
            self.assertNotIn(value, stored)

    def test_missing_source_retains_failures_and_backoff_does_not_stop_healthy_task(self):
        self.append(TASK_B, self.tool(TASK_B, "example-failure"))
        first = self.capture(include_agents=True)
        original = self.paths[TASK_B].read_bytes()
        self.paths[TASK_B].unlink()
        cursor = first["cursor"]
        for now in (1100, 1101, 1102):
            result = self.observer.capture([TASK_A], include_agents=True, after=cursor, now=now)
            cursor = result["cursor"]
        self.append(TASK_A, counter(1500, 1103))
        skipped = self.observer.capture([TASK_A], include_agents=True, after=cursor, now=1103)
        child = next(r for r in skipped["tasks"] if r["thread_hash"] == stable_hash(TASK_B))
        self.assertEqual(child["observation"]["read_mode"], "backoff")
        self.assertEqual(child["observation"]["scan_bytes"], 0)
        self.assertEqual(skipped["observed_token_delta"], 500)
        self.assertTrue(any(s["kind"] == "tool_failure_observed"
                            for s in skipped["unconfirmed_signals"]))
        self.assertFalse(any(s["kind"] == "tool_failure_observed"
                             for s in skipped["cleared_signals"]))
        self.paths[TASK_B].write_bytes(original)
        probe = self.observer.capture([TASK_A], include_agents=True, after=skipped["cursor"],
                                      now=1104, probe=True)
        child = next(r for r in probe["tasks"] if r["thread_hash"] == stable_hash(TASK_B))
        self.assertEqual(child["observation_health"]["state"], "healthy")

    def test_deleted_explicit_root_does_not_abort_other_roots_or_change_scope(self):
        first = self.observer.capture([TASK_A, TASK_B], now=1100)
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM threads WHERE id=?", (TASK_A,))
        self.append(TASK_B, counter(1700, 1101))
        second = self.observer.capture([TASK_A, TASK_B], after=first["cursor"], now=1101)
        self.assertEqual(second["scope"], first["scope"])
        self.assertEqual(second["selected_tasks"], 2)
        self.assertEqual(second["observed_token_delta"], 700)
        self.assertEqual(second["tasks"][0]["catalog_status"], "unavailable")
        self.assertEqual(second["observation_failures"], 1)

    def test_foreign_unknown_and_conflicting_native_items_cannot_claim_recovery(self):
        record = self.tool(TASK_A, "example-call")
        self.append(TASK_A, record, record, self.tool(TASK_A, "example-unknown", code=None),
                    self.tool(TASK_A, "example-foreign", owner=TASK_B))
        first = self.capture()
        tools = first["tasks"][0]["observation"]["tool_evidence"]
        self.assertEqual(tools["counts"], {"passed":0, "failed":1, "unknown":1})
        self.append(TASK_A, self.tool(TASK_A, "example-call", code=0))
        second = self.capture(after=first["cursor"])
        self.assertTrue(second["tasks"][0]["observation"]["tool_evidence"]["limited"])
        self.assertTrue(any(s["kind"] == "tool_failure_observed" for s in second["signals"]))

    def test_large_scope_native_wait_batches_exclude_self_before_partition(self):
        roots = [TASK_A, TASK_B]
        with sqlite3.connect(self.database) as db:
            for number in range(8):
                identifier = f"00000000-0000-4000-8000-{number:012d}"
                roots.append(identifier)
                db.execute("INSERT INTO threads VALUES (?,?,NULL,NULL,NULL,NULL,?,1000,NULL)",
                           (identifier, "Synthetic extra Task", '"vscode"'))
        args = ["workflow", "targets", "--codex-home", str(self.home), "--limit", "32"]
        for identifier in roots:
            args.extend(["--thread", identifier])
        with (patch.dict(os.environ, {"CODEX_THREAD_ID":TASK_A}),
              redirect_stdout(io.StringIO()) as out):
            self.assertEqual(main([*args, "--batch", "1"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(len(result["targets"]), 1)
        self.assertEqual(len(result["names"]), 1)
        self.assertTrue(result["calling_task_excluded"])

    def test_json_cursor_error_is_structured_and_does_not_reset_scope(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["--data-dir", str(self.data), "workflow", "observe", "--json",
                         "--thread", TASK_A, "--codex-home", str(self.home), "--after", "bad"])
        self.assertEqual(code, 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["code"], "invalid_cursor")
        self.assertTrue(result["scope_preserved"])
        self.assertFalse(self.data.exists())

    def test_catalog_or_store_failure_returns_typed_diagnostic_without_private_error(self):
        args = ["--data-dir", str(self.data), "workflow", "observe", "--json", "--thread",
                TASK_A, "--codex-home", str(self.home)]
        self.database.rename(self.home / "unavailable-catalog.sqlite3")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(args), 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["code"], "native_catalog_unavailable")
        self.assertTrue(result["retryable"])
        self.assertNotIn(str(self.home), out.getvalue())
        self.assertFalse(self.data.exists())
        (self.home / "unavailable-catalog.sqlite3").rename(self.database)
        broken = self.data / "workflow-observations/observations.sqlite3"
        broken.parent.mkdir(parents=True)
        broken.write_bytes(b"synthetic invalid SQLite data")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(args), 2)
        self.assertEqual(json.loads(out.getvalue())["code"], "observation_store_unavailable")

    def test_structured_mcp_outcomes_need_explicit_flags_and_matching_success(self):
        def mcp(call, result):
            return event(1001, "event_msg", {"type":"item_completed", "thread_id":TASK_A,
                "turn_id":"t", "item":{"type":"McpToolCall", "id":call,
                "server":"example", "tool":"example-check", "arguments":{}, "result":result}})
        self.append(TASK_A, mcp("example-unknown", {"content":[]} ),
                    mcp("example-failed", {"isError":True}))
        first = self.capture()
        state = first["tasks"][0]["observation"]["tool_evidence"]
        self.assertEqual(state["counts"], {"passed":0, "failed":1, "unknown":1})
        self.append(TASK_A, mcp("example-passed", {"isError":False}))
        second = self.capture(after=first["cursor"])
        self.assertFalse(any(s["kind"] == "tool_failure_observed" for s in second["signals"]))

    def test_gap_retains_unconfirmed_incidents_and_bounds_their_history(self):
        self.append(TASK_A, self.tool(TASK_A, "example-failed"))
        first = self.capture()
        self.append(TASK_A, event(1002, "response_item", {"text":"x" * (TAIL_BYTES+1000)}))
        gap = self.capture(after=first["cursor"])
        self.assertTrue(any(s["kind"] == "tool_failure_observed"
                            for s in gap["unconfirmed_signals"]))
        self.assertTrue(any(s["kind"] == "observation_coverage_gap" for s in gap["signals"]))
        self.assertIsNone(gap["observed_token_delta"])

    def test_unrelated_success_does_not_resolve_a_recorded_failure(self):
        self.append(TASK_A, self.tool(TASK_A, "example-failed"))
        first = self.capture()
        self.append(TASK_A, self.tool(TASK_A, "example-other-check", code=0,
                                      command="example-unrelated-check"))
        second = self.capture(after=first["cursor"])
        self.assertTrue(any(s["kind"] == "tool_failure_observed" for s in second["signals"]))

    def test_observer_commands_cannot_create_a_self_observation_failure_loop(self):
        for command in ("python3 scripts/run_budget.py workflow observe",
                        "python3 -I example.pyz --preview example-task example-turn",
                        ["/bin/zsh", "-lc", "python3 scripts/run_budget.py workflow observe"]):
            self.append(TASK_A, self.tool(TASK_A, "example-observer", code=2, command=command))
        result = self.capture()
        self.assertFalse(any(s["kind"] == "tool_failure_observed" for s in result["signals"]))
        state = result["tasks"][0]["observation"]["tool_evidence"]
        self.assertEqual(state["excluded_observer_items"], 3)

    def test_unchanged_failure_advice_is_not_emitted_as_new_response(self):
        self.append(TASK_A, self.tool(TASK_A, "example-failed"))
        first = self.capture()
        self.append(TASK_A, counter(1200, 1002))
        second = self.capture(after=first["cursor"])
        self.assertTrue(second["changed"])
        self.assertFalse(second["new_response_plan"])

    def test_older_or_undated_success_cannot_clear_a_newer_failure(self):
        self.append(TASK_A, self.tool(TASK_A, "example-failed"))
        first = self.capture()
        old = self.tool(TASK_A, "example-old-pass", code=0)
        old["timestamp"] = event(900, "unused", {})["timestamp"]
        undated = self.tool(TASK_A, "example-undated-pass", code=0)
        undated.pop("timestamp")
        self.append(TASK_A, old, undated)
        second = self.capture(after=first["cursor"])
        self.assertTrue(any(s["kind"] == "tool_failure_observed" for s in second["signals"]))
        self.assertFalse(any(s["kind"] == "tool_failure_observed"
                             for s in second["cleared_signals"]))

    def test_out_of_order_failure_is_still_detected_for_an_independent_operation(self):
        self.append(TASK_A, self.tool(TASK_A, "example-pass", code=0))
        first = self.capture()
        old = self.tool(TASK_A, "example-independent-failure", command="example-other-check")
        old["timestamp"] = event(900, "unused", {})["timestamp"]
        self.append(TASK_A, old)
        second = self.capture(after=first["cursor"])
        self.assertTrue(any(s["kind"] == "tool_failure_observed" for s in second["signals"]))


if __name__ == "__main__":
    unittest.main()
