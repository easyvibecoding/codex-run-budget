from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.meter import (  # noqa: E402
    compare_snapshots,
    load_snapshots,
    meter_report,
    meter_tasks,
    normalize_snapshot,
    record_snapshot,
    snapshot_summary,
    tasks_summary,
)
from codex_run_budget.meter_policy import pricing_context  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402

THREAD_A = "12345678-1234-1234-1234-123456789abc"
THREAD_B = "22345678-1234-1234-1234-123456789abc"


def sources(stamp, plan="pro", used=10):
    return {
        "started_at": stamp - 1,
        "finished_at": stamp,
        "account_response": {"account": {"type": "chatgpt", "planType": plan}},
        "rate_limits": {
            "accountId": "private",
            "rateLimitsByLimitId": {
                "codex": {
                    "planType": plan,
                    "primary": {
                        "usedPercent": used,
                        "windowDurationMins": 10080,
                        "resetsAt": 100000,
                    },
                },
            },
        },
    }


class MeterTasksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        for number, thread in enumerate((THREAD_A, THREAD_B)):

            def event(stamp, kind, payload):
                return {
                    "timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                    "type": kind,
                    "payload": payload,
                }

            rows = [
                event(1100, "session_meta", {"id": thread}),
                event(
                    1200,
                    "turn_context",
                    {
                        "turn_id": "private-turn",
                        "model": "gpt-6-astra",
                        "effort": "low" if number == 0 else "high",
                        "service_tier": "fast" if number == 0 else "standard",
                    },
                ),
                event(
                    1300,
                    "token_usage_record",
                    {
                        "response_id": "private-response-" + str(number),
                        "usage": {
                            "input_tokens": 900,
                            "cached_input_tokens": 800,
                            "output_tokens": 100,
                            "total_tokens": 1000,
                        },
                    },
                ),
            ]
            page = self.sessions / f"private-{number}.jsonl"
            page.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            os.utime(page, (1900, 1900))

    def test_cross_task_filter_and_privacy(self):
        all_tasks = meter_tasks(sessions=self.sessions, days=0.02, now=2000)
        self.assertEqual(all_tasks["local_usage"]["task_count"], 2)
        self.assertEqual(all_tasks["local_usage"]["request_usage"]["total_tokens"], 2000)
        selected = meter_tasks(
            sessions=self.sessions, days=0.02, now=2000, thread_ids=[THREAD_A.upper(), THREAD_A]
        )
        self.assertEqual(selected["local_usage"]["task_count"], 1)
        self.assertEqual(selected["local_usage"]["request_usage"]["total_tokens"], 1000)
        self.assertEqual(selected["local_usage"]["request_usage"]["unique_responses"], 1)
        rows = selected["local_usage"]["request_context_usage"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["thread_hash"], stable_hash(THREAD_A))
        self.assertEqual(rows[0]["reasoning_effort"], "low")
        self.assertIs(rows[0]["fast_mode"], True)
        text = json.dumps(selected)
        for private in (THREAD_A, THREAD_B, "private-turn", "private-response", "private-0"):
            self.assertNotIn(private, text)
        self.assertIn("Fast", tasks_summary(selected))

    def test_missing_task_is_not_zero_and_bad_selection_fails(self):
        report = meter_tasks(
            sessions=self.sessions,
            days=0.02,
            now=2000,
            thread_ids=["32345678-1234-1234-1234-123456789abc"],
        )
        self.assertIsNone(report["local_usage"]["request_usage"])
        self.assertTrue(report["local_usage"]["missing_selected_thread_hashes"])
        with self.assertRaises(ValueError):
            meter_tasks(sessions=self.sessions, thread_ids=["bad-id"])

    def test_report_filters_tokens_but_account_quota_stays_account_wide(self):
        record_snapshot(self.root, sources(1000, used=9))
        record_snapshot(self.root, sources(2000))
        report = meter_report(self.root, sessions=self.sessions, thread_ids=[THREAD_B])
        self.assertEqual(report["interval"]["windows"][0]["used_percentage_points"], 1)
        self.assertEqual(report["local_usage"]["request_usage"]["total_tokens"], 1000)
        self.assertIsNone(report["local_usage"]["models"][0]["quota_percentage_points"])

    def test_subscription_route_changes_and_old_snapshot_compatibility(self):
        before = normalize_snapshot(sources(1000))
        after = normalize_snapshot(sources(2000, plan="plus"))
        self.assertIn(
            "subscription_changed", compare_snapshots(before, after)["windows"][0]["issues"]
        )
        after = normalize_snapshot(sources(2000))
        after["subscription"]["auth_type"] = "apiKey"
        self.assertIn(
            "billing_route_changed", compare_snapshots(before, after)["windows"][0]["issues"]
        )
        record_snapshot(self.root, sources(1000))
        old = {k: v for k, v in before.items() if k != "subscription"}
        old["schema_version"] = 1
        with sqlite3.connect(self.root / "meter.sqlite3") as connection:
            connection.execute("UPDATE snapshots SET payload=? WHERE id=1", (json.dumps(old),))
        self.assertEqual(load_snapshots(self.root)[0]["schema_version"], 1)
        self.assertIn("not_recorded", snapshot_summary(load_snapshots(self.root)[0]))

    def test_non_chatgpt_route_never_claims_subscription_from_extra_plan_field(self):
        raw = sources(1000)
        raw["account_response"]["account"]["type"] = "apiKey"
        subscription = normalize_snapshot(raw)["subscription"]
        self.assertIsNone(subscription["plan_type"])
        self.assertEqual(subscription["status"], "conflicted")

    def test_unknown_quota_labels_are_hashed_and_still_comparable(self):
        raw = sources(1000)
        bucket = raw["rate_limits"]["rateLimitsByLimitId"].pop("codex")
        bucket.update(limitId="secret-account-id", limitName="private-workspace")
        raw["rate_limits"]["rateLimitsByLimitId"]["secret-account-id"] = bucket
        first = normalize_snapshot(raw)
        raw.update(started_at=1999, finished_at=2000)
        second = normalize_snapshot(raw)
        encoded = json.dumps(first)
        self.assertNotIn("secret-account-id", encoded)
        self.assertNotIn("private-workspace", encoded)
        self.assertTrue(first["limits"][0]["limit_id"].startswith("hash:"))
        self.assertEqual(
            compare_snapshots(first, second)["windows"][0]["used_percentage_points"], 0
        )

    def test_cli_tasks_and_rates_do_not_read_native_or_write_storage(self):
        destination = self.root / "not-created"
        for action in ("tasks", "rates", "estimate"):
            output = io.StringIO()
            with patch("codex_run_budget.meter_source.read_meter_sources") as native:
                with redirect_stdout(output):
                    result = main(
                        [
                            "--data-dir",
                            str(destination),
                            "meter",
                            action,
                            "--directory",
                            str(self.sessions),
                            "--json",
                        ]
                    )
            self.assertEqual(result, 0)
            native.assert_not_called()
            json.loads(output.getvalue())
            self.assertFalse(destination.exists())
        reference = pricing_context()
        self.assertFalse(reference["measured_charge"])
        self.assertEqual(reference["verified_on"], "2026-09-12")


if __name__ == "__main__":
    unittest.main()
