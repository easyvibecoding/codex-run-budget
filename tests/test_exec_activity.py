"""Synthetic catalog, real CLI process and private receipt integration tests."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))
from codex_run_budget.exec_activity import (  # noqa: E402
    add_notice,
    notice,
    record_launch,
    scan,
)
from codex_run_budget.util import stable_hash  # noqa: E402

TASK = "11111111-2222-4333-8444-555555555555"
PARENT = "22222222-2222-4333-8444-555555555555"
OTHER = "33333333-2222-4333-8444-555555555555"
CLI = ROOT / "plugins/codex-run-budget/scripts/run_budget.py"


def usage(n):
    return {"total_tokens": n, "input_tokens": n - 10,
            "cached_input_tokens": 0, "output_tokens": 10}


class ExecActivityTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home, self.project, self.data = (self.root / x for x in ("native", "project", "data"))
        self.home.mkdir()
        self.project.mkdir()
        self.path = self.home / "synthetic.jsonl"
        self.now = time.time()
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("CREATE TABLE threads (id TEXT,source TEXT,cwd TEXT,rollout_path TEXT,"
                       "created_at INTEGER,updated_at INTEGER)")
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                       (TASK, "exec", str(self.project), str(self.path), self.now, self.now))
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                       (OTHER, "exec", str(self.root / "elsewhere"), str(self.path),
                        self.now, self.now))
        self.write()

    def write(self, *, identity=TASK, records=None):
        rows = [{"type": "session_meta", "payload": {"id": identity, "source": "exec",
                "cwd": str(self.project), "originator": "Codex Desktop",
                "base_instructions": "PRIVATE PROMPT"}}]
        rows += records if records is not None else [
            {"type": "token_usage_record", "payload": {"thread_id": TASK,
             "thread_token_usage": usage(100)}},
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def scan(self, **kw):
        return scan(self.project, root=self.data, home=self.home, since=self.now - 60, **kw)

    def invoke(self, action, *extra, home=True):
        args = [sys.executable, str(CLI), "--data-dir", str(self.data)]
        args += ["exec-activity", action, "--project", str(self.project)]
        if home:
            args += ["--codex-home", str(self.home)]
        args += list(extra)
        return subprocess.run(args, capture_output=True, timeout=15)

    def test_exact_project_readonly_identity_and_no_inferred_parent(self):
        before = (self.home / "state_5.sqlite").read_bytes()
        report = self.scan()
        self.assertEqual(len(report["activities"]), 1)
        row = report["activities"][0]
        self.assertEqual(row["usage"]["total"], 100)
        self.assertEqual(row["state"], "last_turn_completed")
        self.assertIsNone(row["parent_hash"])
        self.assertEqual(row["attribution"], "unknown")
        self.assertFalse(report["included_in_parent_usage"])
        self.assertNotIn(TASK, json.dumps(report))
        self.assertNotIn("PRIVATE PROMPT", json.dumps(report))
        self.assertEqual(before, (self.home / "state_5.sqlite").read_bytes())
        self.assertFalse(self.data.exists())

    def test_foreign_transcript_and_symlink_never_establish_usage(self):
        self.write(identity=OTHER)
        self.assertIsNone(self.scan()["activities"][0]["usage"])
        other = self.path.with_suffix(".other")
        self.path.rename(other)
        self.path.symlink_to(other)
        self.assertIsNone(self.scan()["activities"][0]["usage"])

    def test_same_lane_reset_unknown_but_cross_lane_is_not_a_reset(self):
        def record(n):
            return {"type": "token_usage_record", "payload": {"thread_id": TASK,
                    "thread_token_usage": usage(n)}}
        legacy = {"type": "event_msg", "payload": {"type": "token_count",
                  "info": {"total_token_usage": usage(1000)}}}
        self.write(records=[legacy, record(100), record(200)])
        row = self.scan()["activities"][0]
        self.assertEqual(row["usage"]["total"], 200)
        self.assertEqual(row["usage_status"], "observed")
        self.write(records=[record(200), record(100)])
        row = self.scan()["activities"][0]
        self.assertIsNone(row["usage"])
        self.assertEqual(row["usage_status"], "counter_reset")

    def test_resumed_session_is_recent_but_cumulative_is_not_window_delta(self):
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET created_at=? WHERE id=?", (self.now - 90000, TASK))
        row = self.scan()["activities"][0]
        self.assertEqual(row["usage_scope"], "session_cumulative")
        self.assertLess(row["started"], self.now - 86400)

    def test_missing_catalog_is_unknown_not_empty_success(self):
        (self.home / "state_5.sqlite").unlink()
        report = self.scan()
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("native_catalog_unavailable", report["issues"])

    def test_launcher_merges_by_exact_identity_and_hashes_all_persistent_identity(self):
        key = stable_hash("synthetic-launch")
        record_launch(self.data, key, project=self.project, parent=PARENT,
                      attribution="launcher_argument", task=TASK)
        record_launch(self.data, key, project=self.project, parent=PARENT,
                      attribution="launcher_argument", task=TASK, state="exited", exit_code=0,
                      usage={"total": 40, "input": 30, "cached_input": 0, "output": 10})
        report = self.scan()
        self.assertEqual(len(report["activities"]), 1)
        row = report["activities"][0]
        self.assertEqual(row["parent_hash"], stable_hash(PARENT))
        self.assertEqual(row["usage"]["total"], 40)
        self.assertEqual(row["usage_scope"], "launcher_invocation")
        raw = (self.data / "exec-activity.sqlite3").read_bytes()
        for private in (TASK, PARENT, str(self.project), str(self.path), "PRIVATE PROMPT"):
            self.assertNotIn(private.encode(), raw)

    def test_hook_notice_is_deduplicated_and_keeps_denial_unchanged(self):
        payload = {"session_id": PARENT, "turn_id": "example-turn", "cwd": str(self.project)}
        self.assertIsNone(notice({**payload, "hook_event_name": "PreToolUse"}, self.data,
                                 home=self.home, now=self.now - 1))
        message = notice({**payload, "hook_event_name": "PostToolUse"}, self.data,
                         home=self.home, now=self.now + 3)
        self.assertIn("1 new", message["systemMessage"])
        self.assertIsNone(notice({**payload, "hook_event_name": "PostToolUse"}, self.data,
                                 home=self.home, now=self.now + 6))
        deny = {"continue": False, "decision": "block", "systemMessage": "existing"}
        with patch("codex_run_budget.exec_activity.notice", return_value=message):
            merged = add_notice(deny, payload, self.data)
        self.assertFalse(merged["continue"])
        self.assertEqual(merged["decision"], "block")
        self.assertTrue(merged["systemMessage"].startswith("existing\n"))
        with patch("codex_run_budget.exec_activity.notice", side_effect=RuntimeError):
            self.assertEqual(add_notice(deny, payload, self.data), deny)

    def test_repeated_resume_launches_keep_distinct_parent_and_invocation_usage(self):
        for key, parent, total in (("first", PARENT, 40), ("second", OTHER, 60)):
            record_launch(self.data, stable_hash(key), project=self.project, parent=parent,
                          attribution="launcher_argument", task=TASK, state="exited", exit_code=0,
                          usage={"total": total, "input": total - 10,
                                 "cached_input": 0, "output": 10})
        rows = self.scan()["activities"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({x["usage"]["total"] for x in rows}, {40, 60})
        self.assertEqual({x["parent_hash"] for x in rows},
                         {stable_hash(PARENT), stable_hash(OTHER)})
        self.assertEqual(rows[0]["native_session"]["usage"]["total"], 100)

    def test_notice_opt_out_has_no_state_side_effect(self):
        with patch.dict(os.environ, {"CODEX_EXEC_ACTIVITY_NOTICES": "0"}):
            self.assertIsNone(notice({"hook_event_name": "PostToolUse", "session_id": PARENT,
                                      "turn_id": "example", "cwd": str(self.project)}, self.data))
        self.assertFalse(self.data.exists())

    def test_hook_adapter_delivers_one_notice_with_reports_disabled(self):
        from codex_run_budget.auto_report import configure
        configure(self.data, enabled=False)
        hook = ROOT / "plugins/codex-run-budget/scripts/hook.py"
        env = {**os.environ, "CODEX_HOME": str(self.home),
               "CODEX_RUN_BUDGET_HOME": str(self.data),
               "CODEX_EXEC_ACTIVITY_NOTICES": "1",
               "CODEX_RUN_BUDGET_EXEC_ACTIVITY_NOTICES": "1"}
        payload = {"session_id": PARENT, "turn_id": "example-turn", "cwd": str(self.project),
                   "tool_name": "example_tool", "tool_input": {}}
        def call(event):
            return subprocess.run([sys.executable, str(hook), "--event", event], env=env,
                                  input=json.dumps({**payload, "hook_event_name": event}),
                                  text=True, capture_output=True, timeout=10)
        before = call("PreToolUse")
        self.assertEqual(before.returncode, 0, before.stderr)
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET created_at=?,updated_at=? WHERE id=?",
                       (time.time(), time.time(), TASK))
        after = call("PostToolUse")
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn("1 new codex exec", after.stdout)
        self.assertNotIn("1 new codex exec", call("PostToolUse").stdout)

    def test_cli_list_and_watch_only_emit_changes(self):
        result = self.invoke("list", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["activities"]), 1)
        result = self.invoke("watch", "--format", "json", "--duration", ".3",
                             "--interval", ".2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["activities"]), 1)

    def test_human_output_exposes_partial_usage_and_exit_code(self):
        with self.path.open("a") as stream:
            stream.write('{"unfinished":')
        result = self.invoke("list")
        self.assertIn(b"100 (partial)", result.stdout)
        self.assertIn(b"Started (UTC)", result.stdout)
        record_launch(self.data, stable_hash("failed-example"), project=self.project,
                      state="exited", exit_code=7)
        self.assertIn(b"exited (7)", self.invoke("list").stdout)

    def test_real_launcher_process_exit_usage_and_ephemeral_receipt(self):
        fake = self.root / "synthetic-codex"
        fake.write_text("#!" + sys.executable + "\nimport json,sys\n"
                        "assert sys.argv[1:3] == ['exec','--json']\n"
                        "print(json.dumps({'type':'thread.started','thread_id':'" + OTHER + "'}))\n"
                        "print(json.dumps({'type':'turn.started'}))\n"
                        "print(json.dumps({'type':'turn.completed','usage':"
                        "{'input_tokens':30,'cached_input_tokens':10,'output_tokens':5}}))\n"
                        "sys.exit(7)\n")
        fake.chmod(0o700)
        result = self.invoke("run", "--parent-task", PARENT, "--codex-binary", str(fake),
                             "--", "--ephemeral", "PRIVATE PROMPT")
        self.assertEqual(result.returncode, 7, result.stderr)
        report = self.scan()
        row = next(x for x in report["activities"] if x["task_hash"] == stable_hash(OTHER))
        self.assertEqual(row["exit_code"], 7)
        self.assertEqual(row["usage"]["total"], 35)
        self.assertEqual(row["parent_hash"], stable_hash(PARENT))
        self.assertNotIn(b"PRIVATE PROMPT", (self.data / "exec-activity.sqlite3").read_bytes())
        self.assertIn(b'"exec_activity": "started"', result.stderr)

    def test_launcher_recording_failure_never_prevents_requested_process(self):
        fake = self.root / "synthetic-codex"
        fake.write_text("#!" + sys.executable + "\nprint('example output')\n")
        fake.chmod(0o700)
        self.data.write_text("not a directory")
        result = self.invoke("run", "--codex-binary", str(fake), "--", "example")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"example output", result.stdout)
        self.assertIn(b"recording_unavailable", result.stderr)

    def test_launcher_observes_executed_failures_without_changing_stdout_or_exit(self):
        from codex_run_budget.optimization_cli import report

        rows = [{"type": "thread.started", "thread_id": OTHER}, {"type": "turn.started"}]
        rows += [{"type": "item.completed", "item": {
            "id": f"synthetic-item-{index}", "type": "command_execution", "exit_code": 1,
            "command": f"python3 -m unittest synthetic_case{index}",
            "aggregated_output": "AssertionError: synthetic failure"}} for index in range(8)]
        rows += [{"type": "turn.completed", "usage": {
            "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 5}}]
        expected = "".join(json.dumps(row) + "\n" for row in rows)
        fake = self.root / "synthetic-codex"
        fake.write_text("#!" + sys.executable + "\nimport sys\nsys.stdout.write(" +
                        repr(expected) + ")\nsys.exit(7)\n")
        fake.chmod(0o700)
        result = self.invoke("run", "--codex-binary", str(fake), "--", "synthetic work")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.decode(), expected)
        self.assertIn(b'"optimizer": "advisory"', result.stderr)
        self.assertEqual(report(self.data, self.project, "exec")["advisories"], 1)
        self.assertEqual(report(self.data, self.project)["observed_completed_calls"], 0)
        self.assertNotIn(b"synthetic_case", (self.data / "optimizer.sqlite3").read_bytes())

    def stream(self, rows, *, suffix=b"", final_newline=True):
        raw = b"\n".join(json.dumps(row).encode() for row in rows)
        if final_newline:
            raw += b"\n"
        raw += suffix
        fake = self.root / "synthetic-stream"
        fake.write_text("#!" + sys.executable + "\nimport sys\nsys.stdout.buffer.write(" +
                        repr(raw) + ")\nsys.exit(7)\n")
        fake.chmod(0o700)
        result = self.invoke("run", "--codex-binary", str(fake), "--", "synthetic work")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, raw)
        from codex_run_budget.optimization_cli import report

        return report(self.data, self.project, "exec")

    def good_stream(self):
        return [{"type": "thread.started", "thread_id": OTHER}, {"type": "turn.started"},
                {"type": "item.completed", "item": {"id": "synthetic-check",
                 "type": "command_execution", "exit_code": 0,
                 "command": "python3 -m unittest", "aggregated_output": "OK"}},
                {"type": "turn.completed", "usage": {
                    "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 5}}]

    def test_final_complete_json_without_newline_is_not_a_gap(self):
        value = self.stream(self.good_stream(), final_newline=False)
        self.assertEqual(value["baselines"]["exec"]["samples"], 1)
        self.assertEqual(value["limited_turns"], 0)
        row = next(x for x in self.scan()["activities"] if x["task_hash"] == stable_hash(OTHER))
        self.assertEqual(row["usage"]["total"], 35)

    def test_oversized_unterminated_tail_invalidates_preceding_completion_sample(self):
        value = self.stream(self.good_stream(), suffix=b"x" * (300 * 1024))
        self.assertEqual(value["baselines"]["exec"]["samples"], 0)
        self.assertEqual(value["coverage_issues"], {"stream_gap": 1})
        row = next(x for x in self.scan()["activities"] if x["evidence"] == "launcher_receipt")
        self.assertIsNone(row["usage"])

    def test_duplicate_start_does_not_restart_observation_turn(self):
        rows = self.good_stream()
        rows.insert(2, {"type": "turn.started"})
        value = self.stream(rows)
        self.assertEqual((value["retained_turns"], value["limited_turns"]), (1, 1))
        self.assertEqual(value["baselines"]["exec"]["samples"], 0)

    def test_conflicting_thread_identity_does_not_rebind_launcher_or_observer(self):
        rows = self.good_stream()
        rows.insert(2, {"type": "thread.started", "thread_id": PARENT})
        value = self.stream(rows)
        self.assertEqual((value["retained_turns"], value["limited_turns"]), (1, 1))
        row = next(x for x in self.scan()["activities"] if x["evidence"] == "launcher_receipt")
        self.assertEqual(row["task_hash"], stable_hash(OTHER))
        self.assertIsNone(row["usage"])

    def test_duplicate_terminal_record_does_not_double_count_or_erase_usage(self):
        rows = self.good_stream()
        rows.append(rows[-1])
        value = self.stream(rows)
        self.assertEqual(value["observed_completed_calls"], 1)
        self.assertEqual(value["baselines"]["exec"]["samples"], 1)
        row = next(x for x in self.scan()["activities"] if x["evidence"] == "launcher_receipt")
        self.assertEqual(row["usage"]["total"], 35)

    def test_later_unfinished_turn_is_not_hidden_by_an_earlier_completion(self):
        rows = self.good_stream()
        rows += [{"type": "turn.started"}, {"type": "item.completed", "item": {
            "id": "synthetic-later", "type": "command_execution", "exit_code": 0,
            "command": "python3 -m unittest", "aggregated_output": "OK"}}]
        value = self.stream(rows)
        self.assertEqual((value["retained_turns"], value["limited_turns"]), (2, 1))
        self.assertEqual(value["baselines"]["exec"]["samples"], 1)

    def test_watch_repeated_unavailability_stops_with_bounded_backoff_and_one_snapshot(self):
        from codex_run_budget.exec_activity_cli import run

        args = SimpleNamespace(activity_action="watch", hours=24, limit=50, duration=0,
                               interval=0.2, project=self.project, format="json",
                               codex_home=self.home)
        report = {"status": "unavailable", "activities": [], "issues": ["synthetic_unavailable"]}
        output, error = StringIO(), StringIO()
        with patch("codex_run_budget.exec_activity_cli.scan", return_value=report) as scan:
            with patch("codex_run_budget.exec_activity_cli.time.sleep") as sleep:
                with redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(run(args, self.data), 1)
        self.assertEqual(scan.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.4, 0.8])
        self.assertEqual(output.getvalue().count('"status"'), 1)
        self.assertIn("watch_stopped", error.getvalue())

    def test_bad_inherited_identity_does_not_block_and_ambiguous_usage_stays_unknown(self):
        fake = self.root / "synthetic-codex"
        fake.write_text("#!" + sys.executable + "\nimport json\n"
                        "print(json.dumps({'type':'thread.started','thread_id':123}))\n"
                        "for _ in range(2):\n"
                        " print(json.dumps({'type':'turn.completed','usage':"
                        "{'input_tokens':30,'cached_input_tokens':10,'output_tokens':5}}))\n")
        fake.chmod(0o700)
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "invalid inherited metadata"}):
            result = self.invoke("run", "--codex-binary", str(fake), "--", "example")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = next(x for x in self.scan()["activities"] if x["evidence"] == "launcher_receipt")
        self.assertIsNone(row["usage"])
        self.assertIsNone(row["parent_hash"])

    def test_launch_failure_is_explicit_and_bad_windows_rejected(self):
        result = self.invoke("run", "--codex-binary", str(self.root / "absent"), "--", "example")
        self.assertEqual(result.returncode, 127)
        self.assertEqual(self.invoke("list", "--hours", "nan").returncode, 1)


if __name__ == "__main__":
    unittest.main()
