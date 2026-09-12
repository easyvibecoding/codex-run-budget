from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.auto_preview import preview  # noqa: E402
from codex_run_budget.auto_report import configure, handle, observed_total, recent  # noqa: E402
from codex_run_budget.governor import Governor  # noqa: E402
from test_auto_report import counter  # noqa: E402

TASK = "12345678-1234-1234-1234-123456789abc"


class AutoPreviewTest(unittest.TestCase):
    def setUp(self):
        for module in ("auto_preview", "auto_report"):
            locale = patch("codex_run_budget." + module + ".resolve_locale",
                           return_value={"locale": "zh-Hant", "locale_source": "test"})
            locale.start()
            self.addCleanup(locale.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        self.output = self.root / "visuals"
        self.transcript = self.root / "secret-source.jsonl"
        self.meta = {"type": "session_meta", "payload": {"id": TASK}}
        self.transcript.write_text(json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n")
        self.db = sqlite3.connect(self.root / "state_5.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY,name TEXT,agent_nickname TEXT,"
            "agent_role TEXT,agent_path TEXT,source TEXT,rollout_path TEXT)"
        )
        self.db.execute("INSERT INTO threads VALUES (?, ?, NULL, NULL, NULL, 'vscode', ?)",
                        (TASK, '改善 <報告> $total', str(self.transcript)))
        self.db.commit()
        self.payload = {
            "session_id": TASK, "turn_id": "turn-1", "hook_event_name": "UserPromptSubmit",
            "transcript_path": str(self.transcript), "model": "gpt-6-astra",
        }
        handle(self.payload, self.data)
        with self.transcript.open("a") as output:
            output.write(json.dumps({"type": "turn_context", "payload": {
                "turn_id": "turn-1", "model": "gpt-6-astra", "effort": "xhigh"
            }}) + "\n" + json.dumps(counter(1500)) + "\n")

    def preview(self, **extra):
        return preview(self.data, TASK, "turn-1", output_dir=self.output, home=self.root, **extra)

    def test_inline_reference_real_snapshot_escaped_private_and_no_state_change(self):
        before = recent(self.data)
        result = self.preview()
        self.assertEqual(result["status"], "preview")
        self.assertLess(len(json.dumps(result)), 700)
        target = next(self.output.glob("*.html"))
        self.assertIn(str(target), result["reference"])
        content = target.read_text()
        for expected in ("500", "450", "400", "50", "25", "gpt-6-astra", "xhigh", "未知"):
            self.assertIn(expected, content)
        self.assertIn("改善 &lt;報告&gt; $total", content)
        for forbidden in (TASK, "secret-source", "<!doctype", "<html", "<script", "fetch("):
            self.assertNotIn(forbidden, content)
        self.assertEqual(recent(self.data), before)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        handle({**self.payload, "hook_event_name": "Stop"}, self.data)
        self.assertEqual(target.read_text(), content)
        self.assertEqual(recent(self.data)[0]["state"], "reported")

    def test_disable_and_threshold_avoid_preview_side_effects(self):
        configure(self.data, enabled=False)
        self.assertEqual(self.preview()["status"], "disabled")
        configure(self.data, enabled=True, threshold_seconds=300)
        self.assertEqual(self.preview()["status"], "below_threshold")
        self.assertFalse(self.output.exists())

    def test_wrong_turn_source_and_subagent_do_not_leak_another_task(self):
        self.assertEqual(preview(self.data, TASK, "other", output_dir=self.output,
                                 home=self.root)["status"], "no_active_start")
        self.transcript.write_text('{}\n')
        self.assertEqual(self.preview()["status"], "source_unavailable")
        self.db.execute("UPDATE threads SET source=?", (json.dumps({"subagent": {}}),))
        self.db.commit()
        self.assertEqual(self.preview()["status"], "subagent")
        self.assertFalse(self.output.exists())

    def test_missing_counter_is_not_zero_and_symlink_output_is_rejected(self):
        self.transcript.write_text(json.dumps(self.meta) + "\n")
        self.preview()
        card = next(self.output.glob("*.html")).read_text()
        self.assertIn('class="viz-stat-value tabular-nums">未觀測</div>', card)
        link = self.root / "link"
        link.symlink_to(self.output)
        with self.assertRaises(ValueError):
            preview(self.data, TASK, "turn-1", output_dir=link, home=self.root)

    def test_incomplete_scope_is_not_promoted_to_complete_or_zero(self):
        zero = {key: 0 for key in ("total", "input", "cached_input", "output", "reasoning_output")}
        self.assertEqual(observed_total(None, {"status": "none", "usage": zero}), (None, False))
        for status in ("observed", "partial", "unavailable"):
            self.assertEqual(observed_total(None, {"status": status, "usage": zero}), (None, False))
        for issue in ("pending_agents", "missing_agents", "selection_limited"):
            self.assertFalse(observed_total(zero, {"status": "observed", "usage": zero,
                                                  issue: 1})[1])

    def test_first_turn_pending_preview_and_separate_stop_settlement(self):
        turn = "fresh-turn"
        self.transcript.write_text("".join(json.dumps(row) + "\n" for row in (
            self.meta,
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}},
            {"type": "turn_context", "payload": {"turn_id": turn}},
        )))
        payload = {**self.payload, "turn_id": turn}
        handle(payload, self.data)
        result = preview(self.data, TASK, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "preview")
        card_path = next(self.output.glob("*.html"))
        card = card_path.read_text()
        self.assertIn('class="viz-stat-value tabular-nums">等待用量寫入</div>', card)
        self.assertIn("首筆請求用量尚未寫入", card)
        self.assertNotIn('class="viz-stat-value tabular-nums">0</div>', card)
        with self.transcript.open("a") as output:
            output.write(json.dumps(counter(1200)) + "\n")
        handle({**payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertEqual(receipt["usage"]["total"], 1200)
        self.assertEqual(receipt["usage_status"], "verified_first_turn_counter")
        self.assertEqual(card_path.read_text(), card)

    def test_child_stop_and_final_card_merge_without_model_self_report(self):
        child = "aaaaaaaa-1234-1234-1234-123456789abc"
        source = {"subagent": {"thread_spawn": {"parent_thread_id": TASK}}}
        transcript = self.root / "private-child.jsonl"
        stamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        request = {"type": "token_usage_record", "timestamp": stamp, "payload": {
            "thread_id": child, "turn_id": "child-turn", "response_id": "private-response",
            "usage": {"total_tokens": 200, "input_tokens": 180, "output_tokens": 20,
                      "cached_input_tokens": 100, "reasoning_output_tokens": 10},
        }}
        records = [
            {"type": "session_meta", "timestamp": stamp, "payload": {
                "id": child, "source": source}}, request,
            {"type": "event_msg", "timestamp": stamp, "payload": {
                "type": "task_complete", "turn_id": "child-turn"}},
        ]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in records))
        self.db.execute("INSERT INTO threads VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                        (child, None, '<測試代理> $total', json.dumps(source), str(transcript)))
        self.db.commit()
        child_stop = {"session_id": TASK, "turn_id": "child-turn", "agent_id": child,
                      "hook_event_name": "SubagentStop", "agent_transcript_path": str(transcript)}
        self.assertIsNone(handle(child_stop, self.data, home=self.root))
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        result = self.preview()
        self.assertEqual(result["status"], "preview")
        card = next(self.output.glob("*.html")).read_text()
        for expected in ("700", "500", "200", "&lt;測試代理&gt; $total", "改善 &lt;報告&gt;"):
            self.assertIn(expected, card)
        for private in (child, "private-child", "private-response"):
            self.assertNotIn(private, card)
        handle({**self.payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertTrue(receipt["subagents_included"])
        self.assertEqual(receipt["subagents"]["usage"]["total"], 200)
        self.assertEqual(receipt["usage"]["total"], 500)
        self.assertEqual(next(self.output.glob("*.html")).read_text(), card)

    def test_disabled_child_capture_and_governor_decision_are_preserved(self):
        event = {**self.payload, "hook_event_name": "SubagentStop", "agent_id": "child"}
        configure(self.data, enabled=False)
        with patch("codex_run_budget.child_usage.capture") as capture:
            self.assertIsNone(handle(event, self.data, home=self.root))
            capture.assert_not_called()
        configure(self.data, enabled=True)
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        budget = {"continue": False, "stopReason": "HALT", "systemMessage": "HALT"}
        with patch.object(governor, "_handle_budget", return_value=budget), patch(
            "codex_run_budget.child_usage.capture"
        ) as capture:
            self.assertEqual(governor.handle(event), budget)
            capture.assert_called_once()


if __name__ == "__main__":
    unittest.main()
