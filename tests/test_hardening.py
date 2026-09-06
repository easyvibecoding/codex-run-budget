from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-run-budget/lib"))

from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.ledger import LEASE_SECONDS, Ledger  # noqa: E402
from codex_run_budget.transcript import Usage, latest_usage, observe_usage  # noqa: E402
from test_governor import token_line  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1] / "plugins/codex-run-budget"


class HardeningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transcript = self.root / "transcript.jsonl"
        self.transcript.write_text(token_line(0) + "\n")
        self.g = Governor(self.root / "state")
        self.addCleanup(self.g.close)
        self.start()

    def payload(self, event, **extra):
        return {
            "hook_event_name": event,
            "session_id": "run",
            "turn_id": "t",
            "transcript_path": str(self.transcript),
            **extra,
        }

    def start(self, options="tokens=10k"):
        result = self.g.handle(
            self.payload("UserPromptSubmit", prompt="run-budget:start " + options)
        )
        self.assertIn("Started a new governed epoch", json.dumps(result))

    def pre(self, identity="call", tool="Bash", value="pwd"):
        return self.g.handle(
            self.payload(
                "PreToolUse", tool_use_id=identity, tool_name=tool, tool_input={"command": value}
            )
        )

    def post(self, identity="call", output=None):
        return self.g.handle(
            self.payload(
                "PostToolUse", tool_use_id=identity, tool_response=output or {"output": "ok"}
            )
        )

    def denied(self, result):
        return (result or {}).get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def test_read_failure_preserves_accounting_and_recovers_automatically(self):
        self.transcript.write_text(token_line(100) + "\n")
        self.g.handle(self.payload("PostCompact"))
        self.transcript.unlink()
        self.assertTrue(self.denied(self.pre()))
        run = self.g.ledger.get_run("run")
        self.assertEqual(
            (run["spent_tokens"], run["usage_status"], run["status"]),
            (100, "unavailable", "active"),
        )
        self.transcript.write_text(token_line(120) + "\n")
        self.assertFalse(self.denied(self.pre()))
        run = self.g.ledger.get_run("run")
        self.assertEqual((run["spent_tokens"], run["usage_status"]), (120, "ok"))

    def test_regression_is_not_counted_as_reset(self):
        self.transcript.write_text(token_line(100) + "\n")
        self.g.handle(self.payload("PostCompact"))
        self.transcript.write_text(token_line(10) + "\n")
        self.assertTrue(self.denied(self.pre()))
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 100)
        self.transcript.write_text(token_line(120) + "\n")
        self.assertFalse(self.denied(self.pre()))
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 120)

    def test_known_zero_pending_missing_and_oversized_are_distinct(self):
        self.assertEqual(latest_usage(str(self.transcript)), Usage())
        self.transcript.write_text('{"type":"session_meta","payload":{}}\n')
        self.assertEqual(observe_usage(str(self.transcript)).state, "pending")
        self.assertIsNone(latest_usage(str(self.root / "missing")))
        with patch("codex_run_budget.transcript.MAX_USAGE_SCAN_BYTES", 1):
            self.assertEqual(observe_usage(str(self.transcript)).reason, "scan_limit")
            self.assertTrue(self.denied(self.pre()))

    def test_fail_open_warns_but_does_not_reset_usage(self):
        self.start("tokens=10k fail=open")
        self.transcript.write_text(token_line(100) + "\n")
        self.g.handle(self.payload("PostCompact"))
        self.transcript.unlink()
        result = self.pre()
        self.assertFalse(self.denied(result))
        self.assertIn("fail=open", json.dumps(result))
        self.transcript.write_text(token_line(120) + "\n")
        self.post()
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 120)

    def test_pending_baseline_and_multiline_control_need_no_new_setting(self):
        self.transcript.write_text('{"type":"session_meta","payload":{}}\n')
        self.start("tokens=10k\nImplement the task.")
        self.assertEqual(self.g.ledger.get_run("run")["usage_status"], "pending")
        self.assertIsNone(self.pre())
        self.transcript.write_text(token_line(120) + "\n")
        self.post()
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 120)

    def test_large_transcript_uses_bounded_tail_and_ignores_partial_last_line(self):
        with self.transcript.open("wb") as handle:
            handle.seek(257 * 1024 * 1024)
            handle.write(b"\n" + token_line(120).encode() + b'\n{"partial":')
        self.assertEqual(observe_usage(str(self.transcript)).usage.total, 120)
        self.assertFalse(self.denied(self.pre()))
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 120)

    def test_invalid_usage_and_completed_without_usage_are_not_zero(self):
        self.transcript.write_text(token_line(100) + "\n")
        self.g.handle(self.payload("PostCompact"))
        for total in (True, -1, float("nan"), 2**64):
            record = {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": total}},
                },
            }
            self.transcript.write_text(json.dumps(record) + "\n")
            self.assertEqual(observe_usage(str(self.transcript)).state, "unavailable")
            self.assertTrue(self.denied(self.pre()))
            self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 100)
        self.transcript.write_text('{"type":"event_msg","payload":{"type":"task_complete"}}\n')
        self.assertEqual(observe_usage(str(self.transcript)).state, "unavailable")

    def test_complete_last_record_without_newline_is_observed(self):
        self.transcript.write_text(token_line(120))
        self.assertEqual(observe_usage(str(self.transcript)).usage.total, 120)
        self.assertFalse(self.denied(self.pre()))
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 120)

    def test_healthy_parent_cannot_clear_missing_child_usage(self):
        self.g.handle(self.payload("SubagentStart", agent_id="child"))
        self.g.handle(self.payload("SubagentStop", agent_id="child", agent_transcript_path=None))
        self.assertTrue(self.denied(self.pre()))
        child = self.root / "child.jsonl"
        child.write_text(token_line(20) + "\n")
        self.g.handle(
            self.payload("SubagentStop", agent_id="child", agent_transcript_path=str(child))
        )
        self.assertFalse(self.denied(self.pre()))
        self.assertEqual(self.g.ledger.get_run("run")["spent_tokens"], 20)

    def test_incidental_control_text_cannot_disable_run(self):
        self.g.handle(
            self.payload("UserPromptSubmit", prompt="Explain this example:\nrun-budget:off")
        )
        self.assertEqual(self.g.ledger.get_run("run")["status"], "active")
        for option in ("tokens=10k toknes=1", "tokens=10k tokens=20k"):
            result = self.g.handle(
                self.payload("UserPromptSubmit", prompt="run-budget:start " + option)
            )
            self.assertEqual(result["decision"], "block")

    def test_halt_wins_over_replayed_admission(self):
        self.pre()
        self.g.handle(self.payload("UserPromptSubmit", prompt="run-budget:halt"))
        self.assertTrue(self.denied(self.pre()))

    def test_changed_results_reset_repeat_streak_without_storing_output(self):
        for index in range(8):
            self.assertFalse(self.denied(self.pre(str(index))))
            self.post(str(index), {"output": f"PRIVATE-PROGRESS-{index}"})
        self.assertEqual(self.g.ledger.get_run("run")["status"], "active")
        dump = "\n".join(self.g.ledger.conn.iterdump())
        self.assertNotIn("PRIVATE-PROGRESS", dump)
        self.assertTrue(any(e["kind"] == "repeat_progress" for e in self.g.ledger.events("run")))

    def test_explicit_waits_do_not_trip_repeat_halt(self):
        for index in range(8):
            self.assertFalse(self.denied(self.pre(str(index), tool="wait")))
            self.post(str(index))
        self.assertEqual(self.g.ledger.get_run("run")["status"], "active")
        self.assertEqual(self.g.ledger.get_run("run")["tool_calls"], 8)

    def test_parallel_agent_admission_reserves_before_start_event(self):
        self.start("tokens=10k agents=2 inflight=20")

        def admit(index):
            payload = self.payload(
                "PreToolUse", tool_name="Agent", tool_use_id=str(index), tool_input={"task": index}
            )
            return not self.denied(Governor.dispatch(payload, self.root / "state"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            allowed = list(pool.map(admit, range(20)))
        self.assertEqual(sum(allowed), 2)
        run = self.g.ledger.get_run("run")
        self.assertEqual((run["active_agents"], run["pending_agents"]), (0, 2))
        for _ in range(2):
            self.g.handle(self.payload("SubagentStart", agent_id="a", agent_type="worker"))
        run = self.g.ledger.get_run("run")
        self.assertEqual((run["active_agents"], run["pending_agents"]), (1, 1))
        self.assertTrue(self.denied(self.pre("extra", "Agent", "extra")))

    def test_failed_start_and_expired_lease_release_reservation(self):
        self.start("tokens=10k agents=1")
        self.assertFalse(self.denied(self.pre("failed", "Agent", "first")))
        self.post("failed", {"isError": True})
        self.assertEqual(self.g.ledger.get_run("run")["pending_agents"], 0)
        self.assertFalse(self.denied(self.pre("lost", "Agent", "second")))
        self.g.ledger.conn.execute(
            "UPDATE agent_slots SET created_at=?", (time.time() - LEASE_SECONDS - 1,)
        )
        self.assertFalse(self.denied(self.pre("after-expiry", "Agent", "third")))

    def test_post_completion_does_not_release_delayed_successful_start(self):
        self.start("tokens=10k agents=1")
        self.pre("spawn", "Agent", "work")
        self.post("spawn", {"id": "child"})
        self.assertTrue(self.denied(self.pre("second", "Agent", "more")))
        self.g.handle(self.payload("SubagentStart", agent_id="child"))
        run = self.g.ledger.get_run("run")
        self.assertEqual((run["active_agents"], run["pending_agents"]), (1, 0))

    def test_unreserved_overflow_halts_future_tools(self):
        self.start("tokens=10k agents=1")
        self.g.handle(self.payload("SubagentStart", agent_id="a"))
        result = self.g.handle(self.payload("SubagentStart", agent_id="b"))
        self.assertIn("HALT", json.dumps(result))
        self.assertTrue(self.denied(self.pre()))

    def test_duplicate_stop_and_late_start_do_not_resurrect_agent(self):
        child = self.root / "child.jsonl"
        child.write_text(token_line(0) + "\n")
        for _ in range(2):
            self.g.handle(
                self.payload("SubagentStop", agent_id="late", agent_transcript_path=str(child))
            )
        self.g.handle(self.payload("SubagentStart", agent_id="late"))
        self.assertEqual(self.g.ledger.get_run("run")["active_agents"], 0)


class HookFailureTest(unittest.TestCase):
    def invoke(self, root, event, raw):
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "scripts/hook.py"), "--event", event],
            input=raw,
            capture_output=True,
            env={"CODEX_RUN_BUDGET_HOME": str(root)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
        return json.loads(result.stdout)

    def assert_stopped(self, event, result):
        if event == "PreToolUse":
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertNotIn("continue", result)
        elif event == "UserPromptSubmit":
            self.assertEqual(result["decision"], "block")
        else:
            self.assertIs(result["continue"], False)
            self.assertNotEqual(result.get("decision"), "block")

    def test_malformed_and_oversized_input_blocks_without_stop_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            for event in ("PreToolUse", "UserPromptSubmit", "Stop", "PostToolUse", "SubagentStop"):
                for raw in (
                    b"PRIVATE-invalid-json",
                    b"x" * (2 * 1024 * 1024 + 1),
                    b"[]",
                    b"[" * 2000 + b"0" + b"]" * 2000,
                ):
                    with self.subTest(event=event, size=len(raw)):
                        result = self.invoke(temporary, event, raw)
                        self.assert_stopped(event, result)
                        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_corrupt_database_bootstrap_honors_saved_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ledger.sqlite3").write_bytes(b"not-a-database")
            for event in ("PreToolUse", "UserPromptSubmit", "Stop"):
                raw = json.dumps({"session_id": "x", "hook_event_name": event}).encode()
                self.assert_stopped(event, self.invoke(root, event, raw))
            from codex_run_budget.util import stable_hash

            (root / "active").mkdir()
            (root / "active" / (stable_hash("x") + ".json")).write_text(
                json.dumps({"status": "active", "fail_closed": False})
            )
            raw = json.dumps({"session_id": "x", "hook_event_name": "PreToolUse"}).encode()
            result = self.invoke(root, "PreToolUse", raw)
            self.assertNotIn("hookSpecificOutput", result)
            self.assertIn("fail-open", result["systemMessage"])

    def test_fixed_event_mismatch_cannot_change_denial_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = json.dumps({"session_id": "x", "hook_event_name": "Stop"}).encode()
            self.assert_stopped("PreToolUse", self.invoke(temporary, "PreToolUse", raw))


class MigrationTest(unittest.TestCase):
    def test_v1_upgrade_is_additive_backed_up_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.sqlite3"
            ledger = Ledger(path)
            from codex_run_budget.ledger import RunConfig

            ledger.start_run("existing", RunConfig(100), "source", Usage())
            ledger.sync_usage("existing", "source", Usage(total=20, input=20))
            for table in ("source_health", "agent_slots", "tool_results"):
                ledger.conn.execute("DROP TABLE " + table)
            ledger.conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            ledger.conn.execute("PRAGMA user_version=1")
            ledger.close()
            upgraded = Ledger(path)
            self.assertEqual(upgraded.get_run("existing")["spent_tokens"], 20)
            self.assertEqual(upgraded.get_run("existing")["usage_status"], "ok")
            upgraded.close()
            backups = list((path.parent / "backups").glob("*.sqlite3"))
            self.assertEqual(len(backups), 1)
            with sqlite3.connect(backups[0]) as restored:
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(restored.execute("SELECT value FROM meta").fetchone()[0], "1")
                self.assertEqual(
                    restored.execute("SELECT spent_tokens FROM runs").fetchone()[0], 20
                )
            Ledger(path).close()
            self.assertEqual(len(list((path.parent / "backups").glob("*.sqlite3"))), 1)
            with sqlite3.connect(path) as old_writer:
                old_writer.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            Ledger(path).close()
            self.assertEqual(len(list((path.parent / "backups").glob("*.sqlite3"))), 1)
