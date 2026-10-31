"""Exercise Codex optimization through the same Governor interface as native hooks."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-run-budget/lib"))

from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.ledger import ObservationHealth, OptimizationLedger  # noqa: E402
from codex_run_budget.optimization import INTERNAL_ENV  # noqa: E402
from codex_run_budget.optimization_cli import measure, report  # noqa: E402
from test_governor import token_line  # noqa: E402


class OptimizationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.root = self.project / "state"
        self.transcript = self.project / "synthetic.jsonl"
        self.transcript.write_text(token_line(0) + "\n")
        self.governor = Governor(self.root)
        self.addCleanup(self.governor.close)
        self.session, self.turn = "synthetic-task", "synthetic-turn"
        self.begun = set()

    def payload(self, event, **extra):
        return {"session_id": self.session, "turn_id": self.turn, "cwd": str(self.project),
                "transcript_path": str(self.transcript), "hook_event_name": event, **extra}

    def event(self, event, **extra):
        return self.governor.handle(self.payload(event, **extra))

    def call(self, identity, *, tool="exec_command", command="python3 -m unittest", code=1,
             output="AssertionError: synthetic failure 123", **extra):
        fields = {"tool_use_id": identity, "tool_name": tool,
                  "tool_input": {"cmd": command}, **extra}
        key = (self.session, self.turn, extra.get("agent_id"), extra.get("transcript_path"))
        if key not in self.begun:
            self.event("UserPromptSubmit", prompt="synthetic work", **extra)
            self.begun.add(key)
        self.event("PreToolUse", **fields)
        response = {"exit_code": code, "output": output}
        return self.event("PostToolUse", tool_response=response, **fields)

    def cycle(self, *, extra=None):
        messages = []
        for index in range(4):
            self.call(f"edit-{index}", tool="apply_patch", command=f"synthetic-edit-{index}",
                      code=0, output="ok", **(extra or {}))
            messages.append(self.call(f"check-{index}", command=f"python3 -m unittest case{index}",
                                      output=f"AssertionError: synthetic failure {index}",
                                      **(extra or {})))
        return messages

    def snapshot(self):
        return report(self.root, self.project)

    def test_changed_calls_with_same_normalized_failure_warn_without_starting_budget(self):
        messages = self.cycle()
        self.assertNotIn("Codex progress advisory", json.dumps(messages[:3]))
        self.assertIn("Codex progress advisory", json.dumps(messages[-1]))
        self.assertIsNone(self.governor.ledger.get_run(self.session))
        self.assertEqual(self.snapshot()["advisories"], 1)
        self.assertEqual(self.snapshot()["model_requests"], 0)

    def test_varying_failures_and_successful_check_reset_spare_productive_work(self):
        for index in range(10):
            self.call(f"changed-{index}", command=f"python3 -m unittest case{index}",
                      output=f"AssertionError: synthetic distinct {'x' * (index + 1)}")
        self.assertEqual(self.snapshot()["advisories"], 0)
        self.call("green", code=0, output="OK")
        for index in range(2):
            self.call(f"later-{index}", command=f"python3 -m unittest next{index}")
        self.assertEqual(self.snapshot()["advisories"], 0)

    def test_reads_waits_and_unknown_results_are_not_failure_evidence(self):
        for index in range(10):
            self.call(f"read-{index}", tool="Read", output="AssertionError: synthetic failure")
            self.call(f"wait-{index}", tool="wait", output="AssertionError: synthetic failure")
            self.call(f"unknown-{index}", code=None)
        value = self.snapshot()
        self.assertEqual(value["advisories"], 0)
        self.assertEqual(value["unknown_outcomes"], 10)

    def test_duplicate_delivery_and_reopen_do_not_double_count_or_repeat_warning(self):
        self.cycle()
        before = self.snapshot()
        self.cycle()
        reopened = Governor(self.root)
        try:
            reopened.handle(self.payload("PostToolUse", tool_use_id="check-3",
                            tool_name="exec_command",
                            tool_input={"cmd": "python3 -m unittest case3"},
                            tool_response={"exit_code": 1,
                                           "output": "AssertionError: synthetic failure 3"}))
        finally:
            reopened.close()
        after = self.snapshot()
        after.pop("sensor_health")
        before.pop("sensor_health")
        self.assertEqual(after, before)

    def test_warning_cooldown_is_bounded_per_turn(self):
        self.cycle()
        for index in range(40):
            self.call(f"extra-{index}", command=f"python3 -m unittest retry{index}")
        self.assertEqual(self.snapshot()["advisories"], 2)

    def test_turns_and_native_agents_do_not_share_failure_streaks(self):
        for index in range(4):
            self.call(f"parent-{index}", command=f"python3 -m unittest case{index}")
            self.call(f"child-{index}", command=f"python3 -m unittest case{index}",
                      agent_id="synthetic-child", transcript_path=str(self.project / "child.jsonl"))
        self.assertEqual(self.snapshot()["advisories"], 0)

    def test_copied_parent_source_still_separates_agent_and_parent_turns(self):
        self.cycle(extra={"agent_id": "synthetic-child"})
        self.assertEqual(self.snapshot()["advisories"], 1)
        self.cycle()
        value = self.snapshot()
        self.assertEqual((value["retained_turns"], value["advisories"]), (2, 2))

    def test_actual_exec_events_warn_without_budget_admission_and_keep_channels_separate(self):
        self.event("ExecObservation", stream_event={"type": "turn.started"})
        for index in range(8):
            result = self.event("ExecObservation", stream_event={
                "type": "item.completed", "item": {"type": "command_execution",
                    "id": f"synthetic-exec-{index}", "command": f"python3 -m unittest case{index}",
                    "exit_code": 1, "aggregated_output": "AssertionError: synthetic failure"}})
        self.assertIn("Codex progress advisory", json.dumps(result))
        self.assertIsNone(self.governor.ledger.get_run(self.session))
        self.assertEqual(self.snapshot()["observed_completed_calls"], 0)
        value = report(self.root, self.project, "exec")
        self.assertEqual((value["observed_completed_calls"], value["advisories"]), (8, 1))
        self.assertEqual(value["coverage"], "explicit_exec_stream")

    def test_exec_stream_gaps_and_quoted_events_do_not_train_or_invent_usage(self):
        self.event("ExecObservation", stream_event={"type": "turn.started"})
        self.event("ExecObservation", stream_event={"type": "item.completed", "item": {
            "id": "synthetic-text", "type": "agent_message",
            "text": 'Example: {"type":"command_execution","exit_code":1}'}})
        self.event("ExecObservation", stream_event={"type": "item.completed", "item": {
            "id": "synthetic-check", "type": "command_execution", "exit_code": 0,
            "command": "python3 -m unittest", "aggregated_output": "OK"}})
        self.event("ExecObservation", stream_event={"type": "stream.incomplete"})
        self.event("ExecObservation", stream_event={"type": "turn.completed"})
        value = report(self.root, self.project, "exec")
        self.assertEqual(value["observed_completed_calls"], 1)
        self.assertEqual(value["baselines"]["exec"]["samples"], 0)
        self.turn = "synthetic-next-turn"
        self.call("new-turn", command="python3 -m unittest fresh")
        self.assertEqual(self.snapshot()["advisories"], 0)

    def test_shared_budget_and_fail_closed_decision_win_over_optimizer_failure(self):
        self.event("UserPromptSubmit", prompt="run-budget:start tokens=10 tools=2")
        with patch("codex_run_budget.optimization.handle", side_effect=sqlite3.OperationalError):
            self.call("allowed", code=0)
            self.transcript.write_text(token_line(11) + "\n")
            result = self.event("PreToolUse", tool_use_id="blocked", tool_name="exec_command",
                                tool_input={"cmd": "synthetic"})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        run = self.governor.ledger.get_run(self.session)
        self.assertEqual((run["spent_tokens"], run["tool_calls"], run["status"]), (11, 1, "halted"))

    def test_disabled_setting_survives_new_governor(self):
        ledger = OptimizationLedger(self.root / "optimizer.sqlite3")
        ledger.configure(False)
        ledger.close()
        self.cycle()
        self.assertFalse(self.snapshot()["enabled"])
        self.assertEqual(self.snapshot()["retained_turns"], 0)
        ledger = OptimizationLedger(self.root / "optimizer.sqlite3")
        ledger.configure(True)
        ledger.close()
        self.turn = "synthetic-enabled-turn"
        self.cycle()
        self.assertEqual(self.snapshot()["advisories"], 1)

    def test_baseline_requires_successful_check_after_last_edit_and_separates_roles(self):
        self.event("Stop")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)
        for index in range(5):
            self.turn = f"synthetic-sample-{index}"
            self.call("verification", code=0, output="OK")
            self.event("Stop")
        value = self.snapshot()["baselines"]
        self.assertEqual(value["task"]["p90_calls"], 1)
        self.assertEqual(value["agent"]["samples"], 0)
        self.turn = "synthetic-stale-check"
        self.call("early-check", code=0)
        self.call("late-edit", tool="apply_patch", code=0)
        self.event("Stop")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 5)

    def test_failed_aborted_pending_opaque_and_compound_checks_do_not_train_baseline(self):
        for index, command in enumerate(("python3 -m unittest || true", "pytest; echo ok")):
            self.turn = f"synthetic-compound-{index}"
            self.call("check", command=command, code=0)
            self.event("Stop")
        self.turn = "synthetic-aborted"
        self.call("check", code=0)
        self.event("Interrupt")
        self.event("Stop")
        self.turn = "synthetic-failed"
        self.call("check", code=1)
        self.event("Stop")
        self.turn = "synthetic-pending"
        self.call("check", code=0)
        self.event("PreToolUse", tool_use_id="pending", tool_name="exec_command")
        self.event("Stop")
        self.turn = "synthetic-opaque"
        self.call("opaque", tool="functions.exec", command="await tools.view_image('synthetic')")
        self.call("check", code=0)
        self.event("Stop")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)

    def test_capability_review_requires_history_and_protects_observed_attempts(self):
        for index in range(5):
            self.session = f"synthetic-task-{index % 2}"
            self.turn = f"synthetic-turn-{index}"
            self.call("edit", tool="apply_patch", code=0)
            self.event("Stop")
        statuses = {row["capability"]: row["status"] for row in self.snapshot()["capabilities"]}
        self.assertEqual(set(statuses.values()), {"review_configuration"})
        self.turn = "synthetic-use"
        self.event("PreToolUse", tool_name="collaboration.spawn_agent", tool_use_id="agent",
                   tool_input={"task": "synthetic work"})
        rows = {row["capability"]: row for row in self.snapshot()["capabilities"]}
        self.assertEqual(rows["collaboration"]["status"], "observed_use")
        self.assertEqual(rows["goals"]["loaded_catalog"], "unknown")

    def test_code_mode_text_never_proves_nested_capability_use_or_absence(self):
        for index in range(5):
            self.session = f"synthetic-task-{index % 2}"
            self.turn = f"synthetic-turn-{index}"
            self.call("wrapper", tool="functions.exec",
                      command='const example = "tools.create_goal()";', code=0)
            self.event("Stop")
        self.assertEqual({row["status"] for row in self.snapshot()["capabilities"]},
                         {"coverage_incomplete"})
        self.assertEqual({row["observed_attempts"] for row in self.snapshot()["capabilities"]}, {0})

    def test_fixed_environment_advice_needs_repeated_cross_task_evidence(self):
        for index in range(3):
            self.session = f"synthetic-task-{index % 2}"
            self.turn = f"synthetic-turn-{index}"
            self.call("module", output="ModuleNotFoundError: No module named 'synthetic_module'")
        advice = self.snapshot()["environment_advice"]
        self.assertEqual([row["category"] for row in advice], ["missing_module"])
        self.assertNotIn("synthetic_module", json.dumps(advice))

    def test_retention_and_call_cap_mark_incomplete_evidence(self):
        with patch("codex_run_budget.optimization.MAX_CALLS", 2):
            for index in range(3):
                self.call(f"call-{index}", code=0)
        self.event("Stop")
        self.assertEqual(self.snapshot()["limited_turns"], 1)
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)
        with patch("codex_run_budget.optimization.MAX_TURNS", 2):
            for index in range(4):
                self.turn = f"synthetic-turn-{index}"
                self.call("small", code=0)
        value = self.snapshot()
        self.assertEqual(value["retained_turns"], 2)
        conn = sqlite3.connect(self.root / "optimizer.sqlite3")
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 2)
        finally:
            conn.close()

    def test_concurrent_replayed_hooks_are_counted_once(self):
        self.event("PreToolUse", tool_use_id="concurrent", tool_name="exec_command",
                   tool_input={"cmd": "python3 -m unittest"})
        payload = self.payload("PostToolUse", tool_use_id="concurrent", tool_name="exec_command",
                               tool_input={"cmd": "python3 -m unittest"},
                               tool_response={"exit_code": 1,
                                              "output": "AssertionError: synthetic"})

        def invoke(_):
            return Governor.dispatch(payload, self.root)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(invoke, range(8)))
        self.assertEqual(self.snapshot()["observed_completed_calls"], 1)

    def test_private_data_absent_from_both_databases_and_output(self):
        secret = "SYNTHETIC_PRIVATE_CONTENT"
        self.event("UserPromptSubmit", prompt=secret)
        self.call("synthetic-native-call", command=f"python3 -m unittest {secret}",
                  output=f"ModuleNotFoundError: {secret}")
        output = json.dumps(self.snapshot())
        blobs = [path.read_bytes() for path in self.root.glob("*.sqlite3*") if path.is_file()]
        for raw in (secret, self.session, self.turn, str(self.project), "synthetic-native-call"):
            self.assertNotIn(raw, output)
            self.assertTrue(all(raw.encode() not in blob for blob in blobs), raw)

    def test_missing_store_report_is_read_only_and_scoped_to_exact_project(self):
        missing = self.project / "missing"
        self.assertEqual(report(missing, self.project)["status"], "no_observations")
        self.assertFalse(missing.exists())
        self.call("one", code=0)
        self.assertEqual(report(self.root, self.project / "another")["retained_turns"], 0)

    def test_conflicting_result_and_unknown_tool_suppress_baselines_and_review(self):
        self.call("one", code=0, output="OK")
        self.event("PostToolUse", tool_use_id="one", tool_name="exec_command",
                   tool_input={"cmd": "python3 -m unittest"},
                   tool_response={"exit_code": 1, "output": "AssertionError: conflict"})
        self.event("Stop")
        self.assertEqual(self.snapshot()["limited_turns"], 1)
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)

    def test_probe_compares_canonical_input_bytes_without_raw_output_or_config_writes(self):
        results = [SimpleNamespace(returncode=0, stdout=b'[{"text":"synthetic full"}]'),
                   SimpleNamespace(returncode=0, stdout=b'[{"text":"lean"}]')]
        with patch("codex_run_budget.optimization_cli.subprocess.run", side_effect=results) as run:
            value = measure(self.project, ["collaboration"])
        self.assertGreater(value["rendered_input_bytes_difference"], 0)
        self.assertIsNone(value["saved_tokens"])
        self.assertIn("features.multi_agent=false", run.call_args.args[0])
        self.assertNotIn("synthetic full", json.dumps(value))
        self.assertFalse((self.project / ".codex/config.toml").exists())

    def test_cli_json_errors_do_not_print_exception_content(self):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            self.assertEqual(main(["--data-dir", str(self.root), "optimizer", "status",
                                   "--project", str(self.project)]), 0)
            with patch("codex_run_budget.optimization_cli.report",
                       side_effect=ValueError("SYNTHETIC_PRIVATE_CONTENT")):
                self.assertEqual(main(["optimizer", "report"]), 2)
        self.assertNotIn("SYNTHETIC_PRIVATE_CONTENT", error.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "no_observations")

    def test_malformed_completed_event_keeps_turn_partial_after_a_good_check(self):
        self.event("ExecObservation", stream_event={"type": "turn.started"})
        self.event("ExecObservation", stream_event={"type": "item.completed", "item": {
            "id": "synthetic-good", "type": "command_execution", "exit_code": 0,
            "command": "python3 -m unittest", "aggregated_output": "OK"}})
        self.event("ExecObservation", stream_event={"type": "item.completed", "item": {
            "id": "synthetic-malformed", "type": "command_execution", "exit_code": 0}})
        self.event("ExecObservation", stream_event={"type": "turn.completed"})
        value = report(self.root, self.project, "exec")
        self.assertEqual(value["coverage_issues"], {"missing_command": 1})
        self.assertEqual(value["baselines"]["exec"]["samples"], 0)

    def test_missing_call_identity_and_missing_result_leave_coverage_evidence(self):
        self.call("good", code=0, output="OK")
        self.event("PostToolUse", tool_name="exec_command", tool_response={"exit_code": 0})
        self.event("Stop")
        self.assertEqual(self.snapshot()["coverage_issues"], {"missing_call_identity": 1})
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)
        self.turn = "synthetic-next"
        self.call("good", code=0, output="OK")
        self.event("PostToolUse", tool_use_id="missing", tool_name="exec_command")
        self.event("Stop")
        self.assertIn("missing_result", self.snapshot()["coverage_issues"])

    def test_start_or_result_after_stop_cannot_repair_a_terminal_turn(self):
        self.event("Stop")
        self.call("late", code=0, output="OK")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)
        self.assertEqual(self.snapshot()["limited_turns"], 1)

    def test_help_collection_and_settings_display_do_not_establish_passed_checks(self):
        commands = ("pytest --collect-only", "pytest --version", "python3 -m unittest --help",
                    "ruff check --show-files", "pytest $SYNTHETIC_OPTIONS")
        for index, command in enumerate(commands):
            self.turn = f"synthetic-noncheck-{index}"
            self.call("display", command=command, code=0, output="OK")
            self.event("Stop")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 0)

    def test_new_failure_does_not_retrigger_an_old_failure_streak(self):
        for index in range(7):
            self.call(f"old-{index}", command=f"python3 -m unittest case{index}",
                      output="AssertionError: synthetic old error")
        result = self.call("new-error", command="python3 -m unittest new_case",
                           output="TypeError: synthetic new error")
        self.assertNotIn("Codex progress advisory", json.dumps(result))

    def test_alternating_failure_cycle_has_a_specific_bounded_advisory(self):
        for index in range(2):
            self.call(f"read-{index}", tool="Read", code=0)
        for index in range(6):
            result = self.call(f"cycle-{index}", command=f"python3 -m unittest case{index}",
                               output=("TypeError: synthetic alpha" if index % 2
                                       else "ValueError: synthetic beta"))
        self.assertIn("failure_cycle", json.dumps(result))
        self.assertEqual(self.snapshot()["advisories"], 1)

    def test_observer_commands_cannot_feed_their_own_failure_detector(self):
        for index in range(10):
            self.call(f"poll-{index}", command=(
                "python3 plugins/codex-run-budget/scripts/run_budget.py optimizer report"),
                output="OperationalError: synthetic observer failure")
        value = self.snapshot()
        self.assertEqual((value["observer_calls"], value["advisories"]), (10, 0))

    def test_dropped_observation_is_visible_and_disqualifies_recovered_turn(self):
        self.call("green", code=0, output="OK")
        with patch("codex_run_budget.ledger.OptimizationLedger.observe",
                   side_effect=sqlite3.OperationalError("SYNTHETIC_PRIVATE_CONTENT")):
            self.event("PreToolUse", tool_use_id="lost", tool_name="exec_command",
                       tool_input={"cmd": "synthetic lost command"})
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["sensor_health"]["dropped"], 1)
        self.assertEqual(value["coverage_issues"], {"observer_gap": 1})
        self.assertEqual(value["baselines"]["task"]["samples"], 0)
        self.assertNotIn("SYNTHETIC_PRIVATE_CONTENT", json.dumps(value))

    def test_observer_circuit_bounds_retries_then_recovers_after_cooldown(self):
        clock = [1000.0]
        with patch("codex_run_budget.ledger.time.time", side_effect=lambda: clock[0]):
            with patch("codex_run_budget.ledger.OptimizationLedger.observe",
                       side_effect=sqlite3.OperationalError("database is locked")) as observe:
                for _ in range(5):
                    self.event("UserPromptSubmit", prompt="synthetic work")
                self.assertEqual(observe.call_count, 3)
            value = self.snapshot()["sensor_health"]
            self.assertEqual((value["state"], value["dropped"], value["suppressed"]),
                             ("open", 3, 2))
            self.assertEqual(value["error_code"], "sqlite_busy")
            clock[0] += 31
            self.event("UserPromptSubmit", prompt="synthetic recovery")
            value = self.snapshot()["sensor_health"]
            self.assertEqual((value["state"], value["failures"]), ("healthy", 0))

    def test_recovery_probe_has_one_owner_and_late_success_cannot_release_its_lease(self):
        health = ObservationHealth(self.root / "synthetic-health.sqlite3")
        self.addCleanup(health.close)
        clock = [1000.0]
        with patch("codex_run_budget.ledger.time.time", side_effect=lambda: clock[0]):
            stale = health.reserve()
            for _ in range(3):
                ticket = health.reserve()
                health.finish(ticket, error=OSError("synthetic failure"))
            clock[0] += 31
            owner = health.reserve()
            self.assertIsNotNone(owner)
            self.assertIsNone(health.reserve())
            health.finish(stale)
            self.assertIsNone(health.reserve())
            health.finish(owner)
            self.assertIsNotNone(health.reserve())

    def test_reentrant_observation_stops_at_the_same_public_interface(self):
        nested = self.payload("UserPromptSubmit", prompt="synthetic nested observation")
        with patch("codex_run_budget.ledger.OptimizationLedger.observe",
                   side_effect=lambda value: self.governor.handle(nested)) as observe:
            self.event("UserPromptSubmit", prompt="synthetic outer observation")
        self.assertEqual(observe.call_count, 1)
        self.assertEqual(self.snapshot()["sensor_health"]["state"], "healthy")

    def test_internal_probe_marker_suppresses_observation_but_not_shared_budget(self):
        import os

        with patch.dict(os.environ, {INTERNAL_ENV: "1"}):
            self.event("UserPromptSubmit", prompt="run-budget:start tokens=10 tools=1")
            self.call("allowed", code=0)
            result = self.event("PreToolUse", tool_use_id="blocked", tool_name="exec_command",
                                tool_input={"cmd": "synthetic"})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse((self.root / "optimizer-health.sqlite3").exists())

    def test_disabling_mid_turn_permanently_marks_the_observation_gap(self):
        self.call("green", code=0, output="OK")
        ledger = OptimizationLedger(self.root / "optimizer.sqlite3")
        try:
            ledger.configure(False)
            ledger.configure(True)
        finally:
            ledger.close()
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["baselines"]["task"]["samples"], 0)
        self.assertEqual(value["coverage_issues"], {"observer_disabled": 1})

    def test_health_store_failure_preserves_unknown_coverage_after_recovery(self):
        self.call("green", code=0, output="OK")
        path = self.root / "optimizer-health.sqlite3"
        original = path.read_bytes()
        path.write_bytes(b"synthetic damaged health store")
        self.event("PreToolUse", tool_use_id="lost", tool_name="exec_command",
                   tool_input={"cmd": "synthetic lost call"})
        self.assertEqual(self.snapshot()["sensor_health"]["state"], "unavailable")
        path.write_bytes(original)
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["coverage_issues"], {"health_unavailable": 1})
        self.assertEqual(value["baselines"]["task"]["samples"], 0)

    def test_backward_clock_blocks_only_observation_and_reports_uncertain_freshness(self):
        clock = [1000.0]
        with patch("codex_run_budget.ledger.time.time", side_effect=lambda: clock[0]):
            self.call("one", code=0)
            clock[0] -= 10
            self.call("two", code=0)
            value = self.snapshot()
            self.assertEqual(value["sensor_health"]["error_code"], "clock_discontinuity")
            self.assertEqual(value["sensor_health"]["freshness"], "clock_discontinuity")
            self.assertEqual(value["evidence_status"], "partial")

    def test_health_gap_does_not_erase_earlier_settled_baseline_samples(self):
        clock = [1000.0]
        with patch("codex_run_budget.ledger.time.time", side_effect=lambda: clock[0]):
            self.call("green", code=0, output="OK")
            self.event("Stop")
            clock[0] += 100
            self.turn = "synthetic-current"
            self.call("current", code=0, output="OK")
            with patch("codex_run_budget.ledger.OptimizationLedger.observe",
                       side_effect=OSError("synthetic failure")):
                self.event("PreToolUse", tool_use_id="lost")
            self.event("Stop")
            value = self.snapshot()
            self.assertEqual(value["baselines"]["task"]["samples"], 1)
            self.assertEqual(value["limited_turns"], 1)

    def test_structured_result_metadata_is_sensed_but_json_in_text_stays_unknown(self):
        for index in range(8):
            self.call(f"prepare-{index}", tool="Read", code=0)
        fields = {"tool_use_id": "structured", "tool_name": "exec_command",
                  "tool_input": {"cmd": "python3 -m unittest"}}
        self.event("PreToolUse", **fields)
        self.event("PostToolUse", **fields, tool_response={
            "structuredContent": {"exit_code": 0, "stdout": "OK"}})
        self.event("Stop")
        self.assertEqual(self.snapshot()["baselines"]["task"]["samples"], 1)
        self.turn = "synthetic-text"
        self.event("UserPromptSubmit", prompt="synthetic work")
        self.event("PreToolUse", **fields)
        self.event("PostToolUse", **fields,
                   tool_response='{"exit_code":0,"stdout":"OK"}')
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["unknown_outcomes"], 1)
        self.assertEqual(value["baselines"]["task"]["samples"], 1)

    def test_conflicting_exit_metadata_cannot_become_a_successful_baseline(self):
        self.event("UserPromptSubmit", prompt="synthetic work")
        fields = {"tool_use_id": "conflicting-metadata", "tool_name": "exec_command",
                  "tool_input": {"cmd": "python3 -m unittest"}}
        self.event("PreToolUse", **fields)
        self.event("PostToolUse", **fields, tool_response={
            "exit_code": 0, "structuredContent": {"exit_code": 1, "stdout": "synthetic"}})
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["unknown_outcomes"], 1)
        self.assertEqual(value["baselines"]["task"]["samples"], 0)

    def test_result_without_repeated_inputs_uses_the_original_paired_intent(self):
        self.event("UserPromptSubmit", prompt="synthetic work")
        self.event("PreToolUse", tool_use_id="paired", tool_name="exec_command",
                   tool_input={"cmd": "python3 -m unittest"})
        self.event("PostToolUse", tool_use_id="paired", tool_name="exec_command",
                   tool_response={"exit_code": 0, "output": "OK"})
        self.event("Stop")
        value = self.snapshot()
        self.assertEqual(value["limited_turns"], 0)
        self.assertEqual(value["baselines"]["task"]["samples"], 1)

    def test_explicit_in_progress_command_stays_pending_without_failure_or_pass_credit(self):
        self.event("ExecObservation", stream_event={"type": "turn.started"})
        self.event("ExecObservation", stream_event={"type": "item.completed", "item": {
            "id": "synthetic-pending", "type": "command_execution", "status": "in_progress",
            "exit_code": None, "command": "python3 -m unittest", "aggregated_output": ""}})
        self.event("ExecObservation", stream_event={"type": "turn.completed"})
        value = report(self.root, self.project, "exec")
        self.assertEqual(value["pending_calls"], 1)
        self.assertEqual(value["baselines"]["exec"]["samples"], 0)


if __name__ == "__main__":
    unittest.main()
