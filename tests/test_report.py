from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.audit import audit_transcripts  # noqa: E402
from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.meter import normalize_snapshot, record_snapshot  # noqa: E402
from codex_run_budget.report import (  # noqa: E402
    build_report,
    render_report,
    resolve_windows,
    write_report,
)
from codex_run_budget.survey import survey_transcripts  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402

TASK_A = "12345678-1234-1234-1234-123456789abc"
TASK_B = "22345678-1234-1234-1234-123456789abc"


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def event(stamp, kind, payload):
    return {"timestamp": iso(stamp), "type": kind, "payload": payload}


def request(stamp, response):
    return event(
        stamp,
        "token_usage_record",
        {
            "response_id": response,
            "usage": {
                "input_tokens": 900,
                "cached_input_tokens": 800,
                "output_tokens": 100,
                "reasoning_output_tokens": 20,
                "total_tokens": 1000,
            },
        },
    )


def native(stamp, used=10, account="private-account", reset=2000000):
    return {
        "started_at": stamp - 1,
        "finished_at": stamp,
        "account_response": {"account": {"type": "chatgpt", "planType": "pro"}},
        "rate_limits": {
            "accountId": account,
            "rateLimitsByLimitId": {
                "codex": {
                    "planType": "pro",
                    "primary": {"usedPercent": used, "windowDurationMins": 300, "resetsAt": reset},
                }
            },
        },
    }


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.end = 1000000.0
        self.page = self.sessions / "private-page.jsonl"
        self.rows = [
            event(self.end - 100000, "session_meta", {"id": TASK_A}),
            event(
                self.end - 100000,
                "turn_context",
                {
                    "turn_id": "private-turn",
                    "model": "gpt-6-astra",
                    "effort": "high",
                    "service_tier": "fast",
                },
            ),
            request(self.end - 3600, "boundary-start"),
            request(self.end - 3599, "recent"),
            request(self.end - 5000, "earlier"),
            request(self.end, "boundary-end"),
            event(
                self.end,
                "response_item",
                {"type": "message", "role": "user", "content": "DO NOT EXPORT MY PRIVATE PROMPT"},
            ),
        ]
        self.save()

    def save(self, rows=None, path=None):
        target = path or self.page
        target.write_text("\n".join(json.dumps(r) for r in (rows or self.rows)) + "\n")
        os.utime(target, (self.end, self.end))

    def report(self, **kwargs):
        return build_report(sessions=self.sessions, windows=["1h", "24h"], now=self.end, **kwargs)

    def test_exact_windows_single_capture_and_subsets(self):
        with patch(
            "codex_run_budget.report.survey_transcripts", wraps=survey_transcripts
        ) as survey:
            report = self.report()
        self.assertEqual(survey.call_count, 1)
        short, long = report["windows"]
        self.assertEqual(short["usage"]["unique_responses"], 2)
        self.assertEqual(long["usage"]["unique_responses"], 3)
        self.assertEqual(long["usage"]["total_tokens"], 3000)
        self.assertEqual(long["usage"]["reasoning_output_tokens"], 60)
        self.assertEqual(long["usage"]["uncached_input_tokens"], 300)
        self.assertTrue(short["contexts"][0]["fast_mode"])
        self.assertEqual(short["contexts"][0]["reasoning_effort"], "high")
        self.assertEqual(short["turns"][0]["contexts"][0]["service_tier"], "fast")

    def test_exact_task_filter_does_not_expand_parent_or_create_ledger(self):
        other = [
            event(
                self.end - 4000,
                "session_meta",
                {
                    "id": TASK_B,
                    "source": {"subagent": {"thread_spawn": {"parent_thread_id": TASK_A}}},
                },
            ),
            event(self.end - 4000, "turn_context", {"turn_id": "b", "model": "gpt-5.6-sol"}),
            request(self.end - 3000, "b-request"),
        ]
        self.save(other, self.sessions / "b.jsonl")
        report = self.report(thread_ids=[TASK_A], directory=self.root / "unused")
        self.assertEqual(report["windows"][0]["usage"]["unique_responses"], 2)
        self.assertFalse((self.root / "unused").exists())
        both = self.report(thread_ids=[TASK_A, TASK_B])
        self.assertEqual(len(both["windows"][0]["tasks"]), 2)
        self.assertIsNone(
            next(
                c for c in both["windows"][0]["contexts"] if c["thread_hash"] == stable_hash(TASK_B)
            )["fast_mode"]
        )

    def test_duplicate_times_are_not_chosen_to_fit_a_window(self):
        self.save(self.rows, self.sessions / "copy.jsonl")
        self.assertEqual(self.report()["windows"][0]["usage"]["unique_responses"], 2)
        changed = copy.deepcopy(self.rows)
        changed[3]["timestamp"] = iso(self.end - 5001)
        self.save(changed, self.sessions / "copy.jsonl")
        report = self.report()
        self.assertEqual(report["coverage"]["ambiguous_time_requests_excluded"], 1)
        self.assertEqual(report["windows"][0]["usage"]["unique_responses"], 1)

    def test_conflicting_task_attribution_keeps_timestamp_conflict(self):
        changed = copy.deepcopy(self.rows)
        changed[0]["payload"]["id"] = TASK_B
        changed[3]["timestamp"] = iso(self.end - 5001)
        self.save(changed, self.sessions / "copy.jsonl")
        self.assertEqual(self.report()["coverage"]["ambiguous_time_requests_excluded"], 1)

    def test_legacy_audit_does_not_grow_request_output(self):
        self.assertNotIn("request_observations", audit_transcripts([self.page]))
        result = audit_transcripts([self.page], include_requests=True)
        self.assertEqual(len(result["request_observations"]), 4)

    def test_missing_timestamp_is_counted_but_never_allocated(self):
        missing = request(self.end - 1, "no-time")
        del missing["timestamp"]
        self.rows.append(missing)
        self.save()
        report = self.report()
        self.assertEqual(report["coverage"]["ambiguous_time_requests_excluded"], 1)
        self.assertEqual(report["windows"][0]["usage"]["unique_responses"], 2)

    def test_missing_task_is_not_zero_and_detail_limits_do_not_change_totals(self):
        missing = self.report(thread_ids=[TASK_B])
        self.assertIsNone(missing["windows"][0]["usage"])
        self.assertEqual(
            missing["scope"]["selected_tasks_without_observations"], [stable_hash(TASK_B)]
        )
        self.rows.insert(
            3,
            event(
                self.end - 3599.5,
                "turn_context",
                {"turn_id": "second", "model": "gpt-5.6-sol", "effort": "low"},
            ),
        )
        self.save()
        report = self.report(detail_limit=1)
        window = report["windows"][0]
        self.assertEqual(window["usage"]["total_tokens"], 2000)
        self.assertTrue(window["turn_details_truncated"])
        self.assertTrue(window["context_details_truncated"])
        self.assertEqual(window["credit_scenarios"]["coverage"]["priced_requests"], 2)

    def test_native_saved_age_subinterval_and_reset_refusal(self):
        store = self.root / "native"
        record_snapshot(store, native(self.end - 3000))
        record_snapshot(store, native(self.end - 100, used=12))
        report = self.report(directory=store)
        self.assertEqual(report["native_latest"]["age_at_report_end_seconds"], 100)
        native_row = report["windows"][0]["native_quota"]
        self.assertEqual(native_row["status"], "observed_subinterval_only")
        self.assertEqual(native_row["comparison"]["windows"][0]["used_percentage_points"], 2)
        self.assertIn("2 百分點", render_report(report))
        record_snapshot(store, native(self.end - 10, used=13, reset=3000000))
        changed = self.report(directory=store)
        self.assertIsNone(
            changed["windows"][0]["native_quota"]["comparison"]["windows"][0][
                "used_percentage_points"
            ]
        )
        self.assertIn("剩餘 87", render_report(changed, "html"))

    def test_calendar_dst_and_monday_week(self):
        end = datetime.fromisoformat("2026-03-09T00:00:00-04:00").timestamp()
        rows = resolve_windows(
            ["24h", "today", "week", "month"], timezone_name="America/New_York", now=end
        )
        self.assertEqual(rows[0]["end"] - rows[0]["start"], 86400)
        self.assertEqual(rows[1]["start"], end)
        self.assertEqual(rows[2]["start"], end)
        self.assertTrue(rows[3]["since"].startswith("2026-03-01T00:00:00-05:00"))
        noon = datetime.fromisoformat("2026-03-08T12:00:00-04:00").timestamp()
        today = resolve_windows(["today"], timezone_name="America/New_York", now=noon)[0]
        self.assertEqual(today["end"] - today["start"], 11 * 3600)

    def test_native_intermediate_account_change_invalidates_endpoint_delta(self):
        store = self.root / "native"
        record_snapshot(store, native(self.end - 3000))
        record_snapshot(store, native(self.end - 2000, account="other"))
        record_snapshot(store, native(self.end - 1000, used=13))
        row = self.report(directory=store)["windows"][0]["native_quota"]["comparison"]["windows"][0]
        self.assertIsNone(row["used_percentage_points"])
        self.assertIn("intermediate_snapshot_discontinuity", row["issues"])

    def test_custom_adjacent_no_double_count_and_validation(self):
        a = build_report(
            sessions=self.sessions,
            since=iso(self.end - 6000),
            until=iso(self.end - 3600),
            now=self.end,
        )
        b = build_report(
            sessions=self.sessions, since=iso(self.end - 3600), until=iso(self.end), now=self.end
        )
        self.assertEqual(a["windows"][0]["usage"]["unique_responses"], 1)
        self.assertEqual(b["windows"][0]["usage"]["unique_responses"], 2)
        for kwargs in (
            {"windows": ["366d"]},
            {"windows": ["0h"]},
            {"windows": []},
            {"windows": ["1h", "1h"]},
            {"since": "2026-01-01"},
            {"timezone_name": "unknown"},
            {"until": iso(self.end + 1)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_report(sessions=self.sessions, now=self.end, **kwargs)

    def test_private_no_clobber_symlink_and_injection_escape(self):
        report = self.report()
        marker = '</td><script>alert("attack")</script>|'
        report["windows"][0]["contexts"][0]["model"] = marker
        html = render_report(report, "html")
        self.assertNotIn(marker, html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("fetch(", html)
        markdown = render_report(report)
        self.assertIn("&#124;", markdown)
        raw = render_report(report, "json")
        for secret in (TASK_A, "private-turn", "private-page", "PRIVATE PROMPT"):
            self.assertNotIn(secret, raw + html + markdown)
        output = self.root / "report.html"
        write_report(output, html)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            write_report(output, "overwrite")
        self.assertEqual(output.read_text(), html)
        link = self.root / "symlink.html"
        link.symlink_to(output)
        with self.assertRaises(ValueError):
            write_report(link, "overwrite")

    def test_empty_calendar_and_cli_no_store_write(self):
        midnight = datetime.fromisoformat("2026-01-01T00:00:00+00:00").timestamp()
        report = build_report(sessions=self.sessions, windows=["today"], now=midnight)
        self.assertIsNone(report["windows"][0]["usage"])
        self.assertIn("沒有已保存的原生快照", render_report(report))
        native_report = self.report()
        snapshot = normalize_snapshot(native(self.end - 1))
        native_report["native_latest"] = {**snapshot, "age_at_report_end_seconds": 1}
        self.assertIn("剩餘 90", render_report(native_report))
        output = self.root / "out.json"
        with (
            patch("codex_run_budget.report.time.time", return_value=self.end),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        str(self.root / "no-store"),
                        "report",
                        "--directory",
                        str(self.sessions),
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
        self.assertFalse((self.root / "no-store").exists())
        self.assertEqual(json.loads(output.read_text())["schema_version"], 1)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["report", "--windows", "bad"]), 2)


if __name__ == "__main__":
    unittest.main()
