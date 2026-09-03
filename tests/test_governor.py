from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "codex-run-budget" / "lib"))

from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.transcript import Usage, latest_usage  # noqa: E402


def token_line(total: int, input_tokens: int | None = None) -> str:
    input_value = total if input_tokens is None else input_tokens
    return json.dumps(
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": input_value,
                        "cached_input_tokens": 0,
                        "output_tokens": total - input_value,
                        "reasoning_output_tokens": 0,
                        "total_tokens": total,
                    }
                },
            },
        }
    )


class GovernorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "root.jsonl"
        self.transcript.write_text(token_line(100) + "\n", encoding="utf-8")
        self.run_id = "session-root"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def payload(self, event: str, **extra: object) -> dict[str, object]:
        data: dict[str, object] = {
            "session_id": self.run_id,
            "transcript_path": str(self.transcript),
            "cwd": str(self.root),
            "hook_event_name": event,
            "turn_id": "turn-1",
        }
        data.update(extra)
        return data

    def start(self, options: str = "tokens=1k") -> Governor:
        governor = Governor(self.root / "state")
        result = governor.handle(
            self.payload("UserPromptSubmit", prompt=f"run-budget:start {options}")
        )
        self.assertIn("Started a new governed epoch", json.dumps(result))
        return governor

    def append_usage(self, total: int, input_tokens: int | None = None) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(token_line(total, input_tokens) + "\n")

    def test_latest_usage_ignores_malformed_lines(self) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write("not json token_count\n")
            handle.write(token_line(250, 200) + "\n")
        self.assertEqual(latest_usage(str(self.transcript)), Usage(total=250, input=200, output=50))

    def test_start_uses_current_transcript_as_zero_baseline(self) -> None:
        governor = self.start()
        try:
            self.append_usage(150)
            result = governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-1",
                    tool_input={"command": "pwd"},
                )
            )
            self.assertIsNone(result)
            run = governor.ledger.get_run(self.run_id)
            self.assertEqual(run["spent_tokens"], 50)
        finally:
            governor.close()

    def test_parent_and_subagent_sources_share_one_budget(self) -> None:
        governor = self.start()
        agent = self.root / "agent.jsonl"
        agent.write_text(token_line(30) + "\n", encoding="utf-8")
        try:
            self.append_usage(120)
            governor.handle(self.payload("PostCompact", trigger="auto"))
            governor.handle(self.payload("SubagentStart", agent_id="agent-1", agent_type="worker"))
            governor.handle(
                self.payload(
                    "SubagentStop",
                    agent_id="agent-1",
                    agent_type="worker",
                    agent_transcript_path=str(agent),
                    stop_hook_active=False,
                )
            )
            run = governor.ledger.get_run(self.run_id)
            self.assertEqual(run["spent_tokens"], 50)
            self.assertEqual(run["active_agents"], 0)
            usage_events = [
                e for e in governor.ledger.events(self.run_id) if e["kind"] == "usage_observed"
            ]
            self.assertEqual(len(usage_events), 2)
        finally:
            governor.close()

    def test_observed_budget_halts_before_supported_tool(self) -> None:
        governor = self.start("tokens=50")
        try:
            self.append_usage(151)
            result = governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-1",
                    tool_input={"command": "pwd"},
                )
            )
            decision = result["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            run = governor.ledger.get_run(self.run_id)
            self.assertEqual(run["status"], "halted")
            self.assertEqual(run["spent_tokens"], 51)
        finally:
            governor.close()

    def test_warning_steers_and_blocks_new_agents_later(self) -> None:
        governor = self.start("tokens=100 warn=50% block_agents=75%")
        try:
            self.append_usage(160)
            result = governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-1",
                    tool_input={"command": "pwd"},
                )
            )
            self.assertIn("STEER", json.dumps(result))
            governor.handle(
                self.payload(
                    "PostToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-1",
                    tool_input={"command": "pwd"},
                    tool_response={"output": "ok"},
                )
            )
            self.append_usage(180)
            result = governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Agent",
                    tool_use_id="agent-call",
                    tool_input={"task": "x"},
                )
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("new subagents", result["hookSpecificOutput"]["permissionDecisionReason"])
        finally:
            governor.close()

    def test_repeat_guard_steers_then_halts(self) -> None:
        governor = self.start("tokens=1k repeat_steer=3 repeat_halt=5")
        try:
            third = None
            fifth = None
            for index in range(1, 6):
                tool_id = f"repeat-{index}"
                result = governor.handle(
                    self.payload(
                        "PreToolUse",
                        tool_name="Bash",
                        tool_use_id=tool_id,
                        tool_input={"command": "same"},
                    )
                )
                if index == 3:
                    third = result
                if index == 5:
                    fifth = result
                    break
                governor.handle(
                    self.payload(
                        "PostToolUse",
                        tool_name="Bash",
                        tool_use_id=tool_id,
                        tool_input={"command": "same"},
                        tool_response={"output": "ok"},
                    )
                )
            self.assertIn("Progress guard", json.dumps(third))
            self.assertEqual(fifth["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(governor.ledger.get_run(self.run_id)["status"], "halted")
        finally:
            governor.close()

    def test_tool_output_cap_replaces_large_result(self) -> None:
        governor = self.start("tokens=1k output=10")
        try:
            governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-large",
                    tool_input={"command": "x"},
                )
            )
            result = governor.handle(
                self.payload(
                    "PostToolUse",
                    tool_name="Bash",
                    tool_use_id="tool-large",
                    tool_input={"command": "x"},
                    tool_response={"output": "x" * 100},
                )
            )
            self.assertEqual(result["decision"], "block")
            self.assertIn("above the 10 limit", result["reason"])
            self.assertEqual(governor.ledger.get_run(self.run_id)["in_flight"], 0)
        finally:
            governor.close()

    def test_prompt_halt_resume_and_off(self) -> None:
        governor = self.start()
        try:
            governor.handle(
                self.payload("UserPromptSubmit", prompt='run-budget:halt reason="pause"')
            )
            blocked = governor.handle(self.payload("UserPromptSubmit", prompt="continue the task"))
            self.assertEqual(blocked["decision"], "block")
            resumed = governor.handle(
                self.payload("UserPromptSubmit", prompt="run-budget:resume tokens=2k")
            )
            self.assertIn("ACTIVE", json.dumps(resumed))
            disabled = governor.handle(self.payload("UserPromptSubmit", prompt="run-budget:off"))
            self.assertIn("OFF", json.dumps(disabled))
            self.assertIsNone(governor.handle(self.payload("UserPromptSubmit", prompt="normal")))
        finally:
            governor.close()

    def test_invalid_control_is_blocked_before_model_request(self) -> None:
        governor = Governor(self.root / "state")
        try:
            result = governor.handle(
                self.payload("UserPromptSubmit", prompt="run-budget:start tokens=wat")
            )
            self.assertEqual(result["decision"], "block")
            self.assertIn("Invalid Run Budget control", result["reason"])
            self.assertIsNone(governor.ledger.get_run(self.run_id))
        finally:
            governor.close()

    def test_parallel_admission_respects_shared_tool_ceiling(self) -> None:
        governor = self.start("tokens=1k tools=5 inflight=20")
        governor.close()

        def invoke(index: int) -> bool:
            local = Governor(self.root / "state")
            try:
                result = local.handle(
                    self.payload(
                        "PreToolUse",
                        tool_name="Bash",
                        tool_use_id=f"parallel-{index}",
                        tool_input={"command": str(index)},
                    )
                )
                return (
                    result is None
                    or result.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
                )
            finally:
                local.close()

        with ThreadPoolExecutor(max_workers=10) as pool:
            allowed = list(pool.map(invoke, range(20)))
        self.assertEqual(sum(allowed), 5)
        check = Governor(self.root / "state")
        try:
            run = check.ledger.get_run(self.run_id)
            self.assertEqual(run["tool_calls"], 5)
            self.assertEqual(run["status"], "halted")
        finally:
            check.close()

    def test_ledger_does_not_store_private_hook_content(self) -> None:
        secret = "PRIVATE-TOOL-CONTENT-7f23"
        governor = self.start()
        try:
            governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="private-tool",
                    tool_input={"command": secret},
                )
            )
            governor.handle(
                self.payload(
                    "UserPromptSubmit",
                    prompt=f'run-budget:halt reason="{secret}-reason"',
                )
            )
        finally:
            governor.close()
        database_bytes = (self.root / "state" / "ledger.sqlite3").read_bytes()
        self.assertNotIn(secret.encode(), database_bytes)
        self.assertNotIn(str(self.transcript).encode(), database_bytes)

    def test_fail_closed_marker_blocks_on_internal_error(self) -> None:
        governor = self.start("tokens=1k fail=closed")
        try:

            def broken(*_args: object, **_kwargs: object) -> None:
                raise sqlite3.OperationalError("synthetic")

            governor.ledger.sync_usage = broken  # type: ignore[method-assign]
            result = governor.handle(
                self.payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="broken",
                    tool_input={"command": "pwd"},
                )
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn(
                "Failing closed", result["hookSpecificOutput"]["permissionDecisionReason"]
            )
        finally:
            governor.close()


if __name__ == "__main__":
    unittest.main()
