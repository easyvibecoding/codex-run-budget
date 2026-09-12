from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.auto_report import (  # noqa: E402
    SCAN_BYTES,
    configure,
    handle,
    recent,
    settings,
    snapshot,
)
from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402


def counter(total):
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "total_tokens": total,
                    "input_tokens": total * 9 // 10,
                    "cached_input_tokens": total * 8 // 10,
                    "output_tokens": total // 10,
                    "reasoning_output_tokens": total // 20,
                }
            },
        },
    }


class AutoReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.page = self.root / "private-source.jsonl"
        self.meta = {"type": "session_meta", "payload": {"id": "private-task-id"}}
        self.page.write_text(json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n")
        self.payload = {
            "session_id": "private-session-id",
            "turn_id": "private-turn-id",
            "transcript_path": str(self.page),
            "model": "gpt-6-astra",
            "prompt": "DO NOT EXPORT PRIVATE PROMPT",
        }

    def event(self, event, seconds=0, **extra):
        return handle(
            {**self.payload, "hook_event_name": event, **extra},
            self.data,
            wall=1000000 + seconds,
            monotonic=5000 + seconds,
        )

    def start(self, threshold=0):
        configure(self.data, enabled=True, threshold_seconds=threshold)
        result = self.event("UserPromptSubmit")
        self.assertEqual(set(result), {"hookSpecificOutput"})
        return result

    def append(self, item):
        with self.page.open("a") as stream:
            stream.write(json.dumps(item) + "\n")

    def report(self):
        return json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())

    def test_disabled_has_no_report_store_side_effects(self):
        configure(self.data, enabled=False)
        before = set(self.data.rglob("*"))
        self.assertFalse(settings(self.data)["enabled"])
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertEqual(set(self.data.rglob("*")), before)

    def test_missing_settings_default_on_without_writing_preferences(self):
        self.assertEqual(settings(self.data), {"enabled": True, "threshold_seconds": 0})
        self.assertFalse(self.data.exists())
        self.assertIsNotNone(self.event("UserPromptSubmit"))
        self.append(counter(1200))
        self.assertEqual(set(self.event("Stop", 1)), {"systemMessage"})
        self.assertEqual(self.report()["usage"]["total"], 200)
        self.assertFalse((self.data / "auto-report.json").exists())

    def test_switch_is_reread_and_explicit_off_is_not_overridden(self):
        self.event("UserPromptSubmit")
        configure(self.data, enabled=False)
        saved = (self.data / "auto-report.json").read_bytes()
        self.assertIsNone(self.event("Stop", 1))
        self.assertEqual((self.data / "auto-report.json").read_bytes(), saved)
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        configure(self.data, enabled=True)
        self.event("UserPromptSubmit", 2, turn_id="next-turn")
        self.assertIsNotNone(self.event("Stop", 3, turn_id="next-turn"))

    def test_parallel_tasks_can_initialize_shared_store(self):
        configure(self.data, enabled=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda n: self.event("UserPromptSubmit", turn_id=f"turn-{n}"), range(8))
            )
        self.assertTrue(all(set(result) == {"hookSpecificOutput"} for result in results))
        self.assertEqual(len(recent(self.data)), 8)

    def test_every_turn_default_zero_and_boundary_counts(self):
        self.start()
        self.append(counter(1200))
        message = self.event("Stop", 0)
        self.assertEqual(set(message), {"systemMessage"})
        self.assertLess(len(message["systemMessage"]), 600)
        receipt = self.report()
        self.assertEqual(receipt["elapsed_seconds"], 0)
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertEqual(receipt["usage"]["cached_input"], 160)
        self.assertEqual(receipt["model_requests_for_report"], 0)
        self.assertEqual(receipt["task_hash"], stable_hash("private-task-id"))
        self.assertIsNone(self.event("Stop", 10))
        self.assertEqual(recent(self.data)[0]["state"], "reported")

    def test_start_requests_inline_preview_and_stop_completes_pending_markdown(self):
        result = self.start()
        specific = result["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        context = specific["additionalContext"]
        target = next((self.data / "auto-reports").glob("*.md"))
        self.assertIn("--preview", context)
        self.assertIn("visualize reference", context)
        self.assertLess(len(context), 1300)
        self.assertIn("待結算", target.read_text())
        self.assertNotIn("Token 前後差額", target.read_text())
        self.append(counter(1400))
        self.event("Stop", 10)
        self.assertIn("400", target.read_text())
        self.assertNotIn("待結算", target.read_text())
        final = target.read_bytes()
        self.assertIsNone(self.event("Stop", 20))
        self.assertEqual(target.read_bytes(), final)

    def test_footer_command_quotes_shell_characters(self):
        self.data = self.root / "space >[inject](x)"
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("'" + str(self.data) + "'", context)
        self.assertNotIn("\n", context)

    def test_pending_file_does_not_claim_report_after_failure_or_disable(self):
        self.start()
        target = next((self.data / "auto-reports").glob("*.md"))
        pending = target.read_bytes()
        configure(self.data, enabled=False)
        self.assertIsNone(self.event("Stop", 1))
        self.assertEqual(target.read_bytes(), pending)

    def test_report_never_overwrites_foreign_markdown_or_symlink(self):
        for mode in ("foreign", "symlink"):
            with self.subTest(mode=mode):
                self.payload["turn_id"] = mode
                self.start()
                row = recent(self.data)[0]
                target = self.data / "auto-reports" / (row["key"] + ".md")
                foreign = self.root / "foreign"
                foreign.write_text("retain")
                if mode == "symlink":
                    target.unlink()
                    target.symlink_to(foreign)
                else:
                    target.write_text("retain")
                self.assertEqual(set(self.event("Stop", 1)), {"systemMessage"})
                self.assertEqual(target.read_text(), "retain")
                self.assertEqual(foreign.read_text(), "retain")
                self.assertEqual(recent(self.data)[0]["state"], "failed")

    def test_governor_preserves_budget_context_with_footer(self):
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        budget = {"systemMessage": "STEER", "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": "budget rules"
        }}
        with patch.object(governor, "_handle_budget", return_value=budget):
            result = governor.handle({**self.payload, "hook_event_name": "UserPromptSubmit"})
        self.assertEqual(result["systemMessage"], "STEER")
        self.assertTrue(
            result["hookSpecificOutput"]["additionalContext"].startswith("budget rules\n")
        )
        self.assertNotIn("decision", result)
        self.assertNotIn("continue", result)

    def test_subagent_start_never_injects_footer(self):
        self.assertIsNone(self.event("UserPromptSubmit", agent_id="child"))
        self.meta["payload"]["source"] = {"subagent": {"thread_spawn": {}}}
        self.page.write_text(json.dumps(self.meta) + "\n")
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertFalse(self.data.exists())

    def test_optional_threshold_strictly_exceeds_and_start_idempotent(self):
        self.start(300)
        self.assertIsNone(self.event("UserPromptSubmit", 200))
        self.append(counter(1500))
        self.assertIsNone(self.event("Stop", 300))
        self.assertIsNotNone(self.event("Stop", 301, stop_hook_active=True))
        self.assertEqual(self.report()["elapsed_seconds"], 301)
        self.assertTrue(self.report()["stop_hook_active"])

    def test_interruption_end_and_missing_start_never_fabricate_completion(self):
        self.start()
        self.event("Interrupt", 200)
        self.assertIsNone(self.event("Stop", 400))
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        self.assertIsNone(self.event("Stop", 400, turn_id="another"))
        self.event("UserPromptSubmit", 500, turn_id="another")
        self.event("SessionEnd", 600, turn_id=None)
        self.assertIsNone(self.event("Stop", 700, turn_id="another"))

    def test_clock_discontinuity_and_other_events_do_not_report(self):
        self.start()
        self.event("SessionStart", 10)
        self.event("PreCompact", 20)
        result = handle(
            {**self.payload, "hook_event_name": "Stop"}, self.data, wall=1001000, monotonic=5001
        )
        self.assertIsNone(result)
        self.assertEqual(recent(self.data)[0]["state"], "clock_discontinuity")

    def test_source_replacement_reset_and_missing_usage_are_unknown(self):
        for mode in ("replacement", "reset", "missing", "no-baseline"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                data = Path(root) / "store"
                configure(data, enabled=True)
                if mode == "no-baseline":
                    self.page.write_text(json.dumps(self.meta) + "\n")
                handle(
                    {**self.payload, "hook_event_name": "UserPromptSubmit"},
                    data,
                    wall=10,
                    monotonic=10,
                )
                if mode == "replacement":
                    self.page.rename(self.root / "old-page")
                    self.page.write_text(
                        json.dumps(self.meta) + "\n" + json.dumps(counter(2000)) + "\n"
                    )
                elif mode == "missing":
                    self.append(
                        {"type": "event_msg", "payload": {"type": "token_count", "info": {}}}
                    )
                else:
                    self.append(counter(100 if mode == "reset" else 3000))
                handle({**self.payload, "hook_event_name": "Stop"}, data, wall=11, monotonic=11)
                receipt = json.loads(next((data / "auto-reports").glob("*.json")).read_text())
                self.assertIsNone(receipt["usage"])
                self.page.write_text(
                    json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n"
                )

    def test_context_is_exact_turn_unknown_fast_not_false_and_safe(self):
        self.start()
        self.append(
            {
                "type": "turn_context",
                "payload": {"turn_id": "old-turn", "effort": "ultra", "service_tier": "fast"},
            }
        )
        self.append(
            {
                "type": "turn_context",
                "payload": {
                    "turn_id": self.payload["turn_id"],
                    "model": "gpt-6-astra",
                    "effort": "high",
                    "service_tier": "priority",
                },
            }
        )
        self.append(counter(2000))
        self.event("Stop", 1, model="</script>private")
        receipt = self.report()
        self.assertEqual(len(receipt["stop_contexts"]), 1)
        self.assertEqual(receipt["stop_contexts"][0]["reasoning_effort"], "high")
        self.assertIsNone(receipt["stop_contexts"][0]["fast_mode"])
        for path in (self.data / "auto-reports").iterdir():
            raw = path.read_bytes()
            for secret in (
                b"private-source",
                b"private-task-id",
                b"private-session-id",
                b"private-turn-id",
                b"PRIVATE PROMPT",
                b"</script>",
            ):
                self.assertNotIn(secret, raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_no_subagent_reports_and_scan_is_bounded(self):
        self.start()
        self.assertIsNone(self.event("Stop", 5, agent_id="subagent"))
        with self.page.open("ab") as stream:
            stream.write(b" " * (SCAN_BYTES + 100) + b"\n")
            stream.write((json.dumps(counter(2000)) + "\n").encode())
        result = snapshot(str(self.page), self.payload["turn_id"])
        self.assertTrue(result["tail_limited"])
        self.assertLessEqual(result["scan_bytes"], SCAN_BYTES + 128 * 1024)
        self.assertEqual(result["usage"]["total"], 2000)
        self.meta["payload"]["source"] = {"subagent": {"thread_spawn": {}}}
        self.page.write_text(json.dumps(self.meta) + "\n")
        self.assertEqual(snapshot(str(self.page), "turn")["status"], "subagent")

    def test_concurrent_stops_publish_once(self):
        self.start()
        self.append(counter(2000))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.event("Stop", 3), range(2)))
        self.assertEqual(sum(bool(r) for r in results), 1)
        self.assertEqual(len(list((self.data / "auto-reports").glob("*.md"))), 1)

    def test_symlinks_and_generation_failure_do_not_continue_or_override_halt(self):
        self.start()
        link = self.root / "link.jsonl"
        link.symlink_to(self.page)
        self.assertEqual(snapshot(str(link), "turn")["status"], "unavailable")
        with patch("codex_run_budget.auto_report._publish", side_effect=OSError):
            message = self.event("Stop", 3)
        self.assertEqual(set(message), {"systemMessage"})
        self.assertIsNone(self.event("Stop", 4))
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        with (
            patch.object(
                governor, "_handle_budget", return_value={"continue": False, "stopReason": "HALT"}
            ),
            patch("codex_run_budget.auto_report.handle", return_value={"systemMessage": "report"}),
        ):
            result = governor.handle({**self.payload, "hook_event_name": "Stop"})
        self.assertFalse(result["continue"])
        self.assertEqual(result["stopReason"], "HALT")

    def test_denied_prompt_does_not_start_and_disable_preserves_files(self):
        self.start()
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        with (
            patch.object(governor, "_handle_budget", return_value={"decision": "block"}),
            patch("codex_run_budget.auto_report.handle") as reporter,
        ):
            governor.handle({**self.payload, "hook_event_name": "UserPromptSubmit"})
            reporter.assert_not_called()
        self.event("Stop", 1)
        paths = set((self.data / "auto-reports").iterdir())
        configure(self.data, enabled=False)
        self.assertIsNone(self.event("UserPromptSubmit", 2, turn_id="next"))
        self.assertEqual(paths, set((self.data / "auto-reports").iterdir()))


if __name__ == "__main__":
    unittest.main()
