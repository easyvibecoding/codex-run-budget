from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.survey import sessions_dir, survey_summary, survey_transcripts  # noqa: E402


class SurveyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def page(self, name, modified, text="{}\n"):
        path = self.root / name
        path.write_text(text)
        os.utime(path, (modified, modified))
        return path

    def test_recent_pages_newest_first_and_limit_is_visible(self):
        old = self.page("old.jsonl", 1)
        older = self.page("older.jsonl", 95_000)
        first = self.page("secret-first.jsonl", 99_000)
        second = self.page("secret-second.jsonl", 98_000)
        self.page("ignore.txt", 99_500)
        with patch("codex_run_budget.survey.audit_transcripts", return_value={}) as audit:
            result = survey_transcripts(self.root, days=1, limit=2, now=100_000)
        audit.assert_called_once_with(
            [first, second], since=13_600, until=100_000, include_requests=False
        )
        selected = result["selection"]
        self.assertTrue(selected["coverage_limited"])
        self.assertEqual(selected["selected_files"], 2)
        self.assertEqual(selected["diagnostics"]["file_limit_skips"], 1)
        self.assertEqual(selected["diagnostics"]["older_files"], 1)
        for private in (str(self.root), first.name, old.name, older.name):
            self.assertNotIn(private, json.dumps(result))

    def test_byte_limit_oversized_and_symlinks_do_not_enter_audit(self):
        first = self.page("first.jsonl", 99_000)
        self.page("second.jsonl", 98_000)
        self.page("oversized.jsonl", 99_500, "x" * 20)
        (self.root / "alias.jsonl").symlink_to(first)
        with (
            patch("codex_run_budget.survey.audit_transcripts", return_value={}) as audit,
            patch("codex_run_budget.survey.MAX_TRANSCRIPT_BYTES", 10),
            patch("codex_run_budget.survey.MAX_SURVEY_BYTES", 3),
        ):
            result = survey_transcripts(self.root, now=100_000)
        self.assertEqual(audit.call_args.args[0], [first])
        counts = result["selection"]["diagnostics"]
        self.assertEqual(counts["non_regular_files"], 1)
        self.assertEqual(counts["oversized_files"], 1)
        self.assertEqual(counts["byte_limit_skips"], 1)
        self.assertTrue(result["selection"]["coverage_limited"])

    def test_discovery_is_bounded_and_empty_directory_is_not_usage_zero(self):
        for name in ("a.jsonl", "b.jsonl", "c.jsonl"):
            self.page(name, 99_000)
        with (
            patch("codex_run_budget.survey.audit_transcripts", return_value={}),
            patch("codex_run_budget.survey.MAX_DISCOVERY_ENTRIES", 2),
        ):
            report = survey_transcripts(self.root, now=100_000)
        self.assertTrue(report["selection"]["coverage_limited"])
        self.assertEqual(report["selection"]["diagnostics"]["discovery_limit_reached"], 1)
        empty = self.root / "empty"
        empty.mkdir()
        report = survey_transcripts(empty)
        self.assertEqual(report["selection"]["selected_files"], 0)
        self.assertIsNone(report["audit"]["request_usage"])
        self.assertFalse(report["coverage"]["evidence_available"])
        self.assertTrue(report["coverage"]["evidence_limited"])

    def test_invalid_selection_fails_before_audit(self):
        with patch("codex_run_budget.survey.audit_transcripts") as audit:
            for options in ({"days": 0}, {"days": float("nan")}, {"limit": 0}, {"limit": True}):
                with self.assertRaises(ValueError):
                    survey_transcripts(self.root, **options)
            audit.assert_not_called()

    def test_root_alias_rejected_and_empty_home_does_not_scan_cwd(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            survey_transcripts(alias)
        with (
            patch.dict(os.environ, {"CODEX_HOME": ""}),
            patch("codex_run_budget.survey.Path.home", return_value=self.root),
        ):
            self.assertEqual(sessions_dir(), self.root / ".codex/sessions")

    def test_directory_entries_count_toward_discovery_cap(self):
        for name in ("a", "b", "c", "d"):
            (self.root / name).mkdir()
        with (
            patch("codex_run_budget.survey.audit_transcripts", return_value={}),
            patch("codex_run_budget.survey.MAX_DISCOVERY_ENTRIES", 2),
        ):
            report = survey_transcripts(self.root)
        self.assertTrue(report["selection"]["coverage_limited"])
        self.assertEqual(report["selection"]["diagnostics"]["discovery_limit_reached"], 1)

    def test_empty_and_incomplete_evidence_is_not_reported_as_zero_or_complete(self):
        with patch("codex_run_budget.survey.audit_transcripts", return_value={}):
            report = survey_transcripts(self.root)
        summary = survey_summary(report)
        self.assertIn("request usage: unknown", summary)
        self.assertIn("no matching call records", summary)
        self.assertIn("Evidence coverage: unknown", summary)
        self.assertNotIn("timeouts 0", summary)
        with patch(
            "codex_run_budget.survey.audit_transcripts",
            return_value={"diagnostics": {"incomplete_lines": 1, "unmatched_outputs": 2}},
        ):
            report = survey_transcripts(self.root)
        self.assertTrue(report["coverage"]["evidence_limited"])
        summary = survey_summary(report)
        self.assertIn("partial or uncertain", summary)
        self.assertIn("incomplete_lines=1", summary)
        self.assertIn("unmatched_outputs=2", summary)

    def test_default_cli_scans_codex_home_without_creating_ledger(self):
        sessions = self.root / "sessions"
        sessions.mkdir()
        (sessions / "private-page.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "private-thread"}}) + "\n"
        )
        ledger = self.root / "no-ledger"
        command = [sys.executable, str(PLUGIN / "scripts/run_budget.py"), "survey", "--json"]
        env = {**os.environ, "CODEX_HOME": str(self.root), "CODEX_RUN_BUDGET_HOME": str(ledger)}
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["selection"]["selected_files"], 1)
        self.assertIsNone(report["audit"]["request_usage"])
        self.assertFalse(ledger.exists())
        self.assertNotIn("private-page", result.stdout)
        self.assertNotIn("private-thread", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)
        failure = subprocess.run(
            [*command, str(self.root / "private-missing")], env=env, capture_output=True, text=True
        )
        self.assertEqual(failure.returncode, 2)
        self.assertNotIn("private-missing", failure.stderr)
        self.assertFalse(ledger.exists())

    def test_lifecycle_only_evidence_and_bounded_detail_output(self):
        turns = [
            {
                "thread_hash": f"{index:064x}",
                "turn_hash": f"{index + 100:064x}",
                "state": "completed",
                "started_at": index,
                "start_observed": True,
                "duration_ms": 2500,
                "duration_source": "explicit",
                "compactions": index,
            }
            for index in range(22)
        ]
        turns[-1].update(state="no_terminal_observed", duration_ms=None, start_observed=False)
        audit = {
            "lifecycle": {
                "summary": {"turns": 22, "completed": 21, "no_terminal_observed": 1},
                "turns": turns,
            }
        }
        with patch("codex_run_budget.survey.audit_transcripts", return_value=audit):
            report = survey_transcripts(self.root)
        self.assertTrue(report["coverage"]["evidence_available"])
        self.assertFalse(report["coverage"]["evidence_limited"])
        text = survey_summary(report, lifecycle_details=True)
        self.assertIn("Turn lifecycle: observed 22, completed 21", text)
        self.assertIn("Lifecycle evidence rows: 20 of 22", text)
        rows = [line for line in text.splitlines() if " | " in line][1:]
        self.assertEqual(len(rows), 20)
        self.assertIn("no_terminal_observed | unknown", rows[0])
        self.assertIn("not proof of same-work recovery", text)
        self.assertNotIn("Lifecycle evidence rows", survey_summary(report))

    def test_unattributed_compaction_evidence_and_nested_issues_remain_visible(self):
        audit = {
            "diagnostics": {"lifecycle_conflicting_terminals": 1},
            "lifecycle": {
                "summary": {"turns": 0, "compactions": 2, "unattributed_compactions": 2},
                "turns": [],
                "diagnostics": {"conflicting_terminals": 1, "unattributed_compactions": 2},
            },
        }
        with patch("codex_run_budget.survey.audit_transcripts", return_value=audit):
            report = survey_transcripts(self.root)
        self.assertTrue(report["coverage"]["evidence_available"])
        self.assertTrue(report["coverage"]["evidence_limited"])
        self.assertEqual(
            report["coverage"]["evidence_issues"]["lifecycle_conflicting_terminals"], 1
        )
        text = survey_summary(report, lifecycle_details=True)
        self.assertIn("Compactions: 2; unattributed 2", text)
        self.assertIn("lifecycle_unattributed_compactions=2", text)

    def test_lifecycle_cli_is_read_only_and_json_remains_full(self):
        sessions = self.root / "sessions"
        sessions.mkdir()
        stamp = datetime.now(timezone.utc).isoformat()
        records = [
            {"type": "session_meta", "payload": {"id": "private-thread"}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "private-turn"}},
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "private-turn",
                    "duration_ms": 50,
                    "last_agent_message": "private completion text",
                },
            },
        ]
        (sessions / "private-page.jsonl").write_text(
            "\n".join(json.dumps({"timestamp": stamp, **record}) for record in records) + "\n"
        )
        ledger = self.root / "no-ledger"
        env = {**os.environ, "CODEX_HOME": str(self.root), "CODEX_RUN_BUDGET_HOME": str(ledger)}
        command = [sys.executable, str(PLUGIN / "scripts/run_budget.py"), "survey"]
        result = subprocess.run([*command, "--lifecycle"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Turn lifecycle: observed 1, completed 1", result.stdout)
        self.assertIn("Lifecycle evidence rows: 1 of 1", result.stdout)
        self.assertNotIn("private-", result.stdout)
        self.assertNotIn("private completion text", result.stdout)
        self.assertFalse(ledger.exists())
        result = subprocess.run([*command, "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["audit"]["lifecycle"]["summary"]["turns"], 1)
        failure = subprocess.run(
            [*command, "--json", "--lifecycle"], env=env, capture_output=True, text=True
        )
        self.assertEqual(failure.returncode, 2)
        self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
