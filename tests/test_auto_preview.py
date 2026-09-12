from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.auto_preview import preview  # noqa: E402
from codex_run_budget.auto_report import configure, handle, recent  # noqa: E402
from test_auto_report import counter  # noqa: E402

TASK = "12345678-1234-1234-1234-123456789abc"


class AutoPreviewTest(unittest.TestCase):
    def setUp(self):
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
        self.assertIn("未觀測", next(self.output.glob("*.html")).read_text())
        link = self.root / "link"
        link.symlink_to(self.output)
        with self.assertRaises(ValueError):
            preview(self.data, TASK, "turn-1", output_dir=link, home=self.root)


if __name__ == "__main__":
    unittest.main()
