from __future__ import annotations

import copy
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.meter import (  # noqa: E402
    compare_snapshots,
    load_snapshots,
    meter_report,
    normalize_snapshot,
    record_snapshot,
    report_summary,
    snapshot_summary,
)

THREAD = "12345678-1234-1234-1234-123456789abc"


def source(stamp=1000, used=9, reset=100000):
    return {
        "started_at": stamp - 1,
        "finished_at": stamp,
        "rate_limits": {
            "accountId": "private-account-id",
            "ordinaryUsageAllowed": True,
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "planType": "pro",
                    "primary": {
                        "usedPercent": used,
                        "windowDurationMins": 10080,
                        "resetsAt": reset,
                    },
                },
            },
        },
        "account_usage": {"summary": {"lifetimeTokens": 123456}},
        "thread_usage": [],
        "errors": [],
    }


class MeterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_native_percent_scope_and_null_are_preserved(self):
        raw = source()
        raw["rate_limits"]["rateLimits"] = {"primary": {"usedPercent": 99}}
        raw["rate_limits"]["rateLimitsByLimitId"]["spark"] = {
            "primary": {"usedPercent": 0, "windowDurationMins": 300},
            "secondary": None,
        }
        snapshot = normalize_snapshot(raw)
        self.assertEqual(len(snapshot["limits"]), 2)
        weekly = snapshot["limits"][0]["windows"][0]
        self.assertEqual(weekly["duration_minutes"], 10080)
        self.assertEqual(weekly["used_percent"], 9)
        self.assertEqual(weekly["remaining_percent"], 91)
        spark = snapshot["limits"][1]["windows"][0]
        self.assertEqual(spark["remaining_percent"], 100)
        self.assertIsNone(spark["resets_at"])
        raw["rate_limits"]["rateLimitsByLimitId"] = {}
        self.assertEqual(normalize_snapshot(raw)["limits"], [])

    def test_legacy_and_out_of_range_percent(self):
        raw = source()
        raw["rate_limits"]["rateLimits"] = raw["rate_limits"].pop("rateLimitsByLimitId")["codex"]
        raw["rate_limits"]["rateLimits"]["primary"]["usedPercent"] = 105
        window = normalize_snapshot(raw)["limits"][0]["windows"][0]
        self.assertEqual(window["used_percent"], 105)
        self.assertEqual(window["remaining_percent"], 0)
        raw["rate_limits"]["rateLimits"]["primary"]["usedPercent"] = True
        window = normalize_snapshot(raw)["limits"][0]["windows"][0]
        self.assertIsNone(window["remaining_percent"])

    def test_private_payloads_never_reach_storage(self):
        raw = source()
        raw["rate_limits"].update(
            {
                "rateLimitResetCredits": {"credits": [{"id": "private-reset-credit"}]},
                "rateLimitUpsell": {"message": "private-banner"},
                "email": "private@example.com",
            }
        )
        raw["account_usage"]["prompt"] = "secret prompt"
        raw["thread_usage"] = [{"thread_id": THREAD, "response": {"threadUsage": None}}]
        saved = record_snapshot(self.root, raw)
        blob = (self.root / "meter.sqlite3").read_bytes()
        for private in (
            "private-account-id",
            "private-reset-credit",
            "private-banner",
            "private@example.com",
            "secret prompt",
            THREAD,
        ):
            self.assertNotIn(private, json.dumps(saved))
            self.assertNotIn(private.encode(), blob)
        self.assertEqual(saved["official_thread_usage"][0]["status"], "unavailable")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"meter.sqlite3"})

    def test_backend_estimates_do_not_become_percentages_or_double_count_cache(self):
        raw = source()
        raw["thread_usage"] = [
            {
                "thread_id": THREAD,
                "response": {
                    "threadUsage": {
                        "threadId": THREAD,
                        "estimatedUsageCreditsMicros": 1200000,
                        "groups": [
                            {
                                "model": "gpt-6-astra",
                                "reasoningEffort": "high",
                                "speed": "fast",
                                "inputTokens": 900,
                                "cachedInputTokens": 800,
                                "netNewInputTokens": 100,
                                "outputTokens": 100,
                                "totalTokens": 1000,
                                "estimatedUsageCreditsMicros": 1200000,
                            }
                        ],
                    }
                },
            }
        ]
        result = normalize_snapshot(raw)["official_thread_usage"][0]
        row = result["groups"][0]
        self.assertEqual(result["status"], "backend_estimate")
        self.assertEqual(row["total_tokens"], 1000)
        self.assertEqual(row["estimated_credits_per_million_tokens"], 1200)
        self.assertIsNone(row["quota_percentage_points"])
        group = raw["thread_usage"][0]["response"]["threadUsage"]["groups"][0]
        group["model"] = "private-custom-model"
        group["reasoningEffort"] = "private-note"
        group["speed"] = "private-speed"
        safe = normalize_snapshot(raw)
        self.assertNotIn("private-custom-model", json.dumps(safe))
        self.assertNotIn("private-note", json.dumps(safe))
        self.assertNotIn("private-speed", json.dumps(safe))
        raw["thread_usage"][0]["response"]["threadUsage"]["groups"][0]["totalTokens"] = 1800
        row = normalize_snapshot(raw)["official_thread_usage"][0]["groups"][0]
        self.assertEqual(row["token_status"], "conflicted")
        self.assertIsNone(row["estimated_credits_per_million_tokens"])
        raw["thread_usage"][0]["response"]["threadUsage"]["threadId"] = "another-thread"
        row = normalize_snapshot(raw)["official_thread_usage"][0]
        self.assertEqual(row["status"], "identity_conflict")
        self.assertEqual(row["groups"], [])

    def test_same_account_window_delta_is_percentage_points_not_relative_percent(self):
        before, after = normalize_snapshot(source()), normalize_snapshot(source(1100, 12))
        report = compare_snapshots(before, after)
        self.assertEqual(report["windows"][0]["used_percentage_points"], 3)
        self.assertEqual(report["model_quota_attribution"], "unavailable")
        after = normalize_snapshot(source(1100, 9))
        report = compare_snapshots(before, after)
        self.assertEqual(report["windows"][0]["status"], "below_display_resolution")

    def test_reset_account_plan_and_missing_identity_invalidate_delta(self):
        before = normalize_snapshot(source())
        alternatives = [source(1100, 10, 200000), source(1100, 8), source(1100, 10, 1050)]
        account = source(1100, 10)
        account["rate_limits"]["accountId"] = "new-account"
        alternatives.append(account)
        unknown = source(1100, 10)
        unknown["rate_limits"].pop("accountId")
        alternatives.append(unknown)
        plan = source(1100, 10)
        plan["rate_limits"]["rateLimitsByLimitId"]["codex"]["planType"] = "plus"
        alternatives.append(plan)
        alternatives.append(source(1000, 10))
        for raw in alternatives:
            with self.subTest(raw=raw):
                row = compare_snapshots(before, normalize_snapshot(raw))["windows"][0]
                self.assertEqual(row["status"], "not_comparable")
                self.assertIsNone(row["used_percentage_points"])
                self.assertTrue(row["issues"])

    def test_missing_latest_bucket_and_bad_bucket_identity_are_visible(self):
        before = normalize_snapshot(source())
        raw = source(1100)
        raw["rate_limits"]["rateLimitsByLimitId"]["codex"]["limitId"] = "different"
        after = normalize_snapshot(raw)
        self.assertIn("bucket_identity_conflict", after["diagnostics"])
        row = compare_snapshots(before, after)["windows"][0]
        self.assertIn("window_latest_unavailable", row["issues"])

    def test_unknown_plan_cannot_establish_same_plan(self):
        before, after = source(), source(1100, 10)
        for raw in (before, after):
            raw["rate_limits"]["rateLimitsByLimitId"]["codex"].pop("planType")
        row = compare_snapshots(normalize_snapshot(before), normalize_snapshot(after))["windows"][0]
        self.assertIsNone(row["used_percentage_points"])
        self.assertIn("plan_unavailable", row["issues"])

    def test_history_is_read_only_and_append_preserves_prior_rows(self):
        missing = self.root / "not-created"
        self.assertEqual(load_snapshots(missing), [])
        self.assertFalse(missing.exists())
        first = record_snapshot(missing, source())
        second = record_snapshot(missing, source(1100))
        self.assertEqual(load_snapshots(missing), [second, first])
        self.assertEqual(load_snapshots(missing, limit=1), [second])
        for limit in (0, True, 1001):
            with self.assertRaises(ValueError):
                load_snapshots(missing, limit=limit)

    def test_storage_refuses_symlink_ancestors_and_unrelated_database(self):
        target = self.root / "target"
        target.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(target, target_is_directory=True)
        for root in (alias, alias / "child"):
            with self.assertRaises(ValueError):
                record_snapshot(root, source())
        database = target / "meter.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE private_data (value TEXT)")
        original = database.read_bytes()
        with self.assertRaises(ValueError):
            record_snapshot(target, source())
        self.assertEqual(database.read_bytes(), original)

    def test_local_tokens_use_interval_and_keep_model_quota_unknown(self):
        record_snapshot(self.root / "data", source())
        record_snapshot(self.root / "data", source(2000, 10))
        sessions = self.root / "sessions"
        sessions.mkdir()

        def event(stamp, kind, payload):
            return {
                "timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                "type": kind,
                "payload": payload,
            }

        rows = [
            event(500, "session_meta", {"id": "private-local-thread"}),
            event(500, "turn_context", {"turn_id": "private-turn", "model": "gpt-6-astra"}),
        ]
        for stamp, response in ((1000, "baseline-response"), (1500, "included-response")):
            rows.append(
                event(
                    stamp,
                    "token_usage_record",
                    {
                        "response_id": response,
                        "usage": {
                            "input_tokens": 900,
                            "cached_input_tokens": 800,
                            "output_tokens": 100,
                            "total_tokens": 1000,
                        },
                    },
                )
            )
        page = sessions / "private-page.jsonl"
        page.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        os.utime(page, (1900, 1900))
        report = meter_report(self.root / "data", sessions=sessions)
        local = report["local_usage"]
        self.assertEqual(local["request_usage"]["total_tokens"], 1000)
        self.assertEqual(len(local["models"]), 1)
        self.assertEqual(local["models"][0]["model"], "gpt-6-astra")
        self.assertIsNone(local["models"][0]["quota_percentage_points"])
        self.assertEqual(local["models"][0]["observed_token_share_percent"], 100)
        self.assertNotIn("private-page", json.dumps(report))
        self.assertNotIn("private-local-thread", json.dumps(report))
        self.assertIn("quota pp", report_summary(report))

    def test_single_snapshot_does_not_charge_prior_token_history(self):
        record_snapshot(self.root, source())
        with patch("codex_run_budget.meter.survey_transcripts") as survey:
            report = meter_report(self.root)
        survey.assert_not_called()
        self.assertEqual(report["status"], "second_snapshot_needed")
        self.assertIsNone(report["local_usage"])

    def test_cli_no_save_history_report_never_create_enforcement_ledger(self):
        data = self.root / "meter-data"
        with patch("codex_run_budget.meter_source.read_meter_sources", return_value=source()):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--data-dir", str(data), "meter", "--no-save", "--json"])
            self.assertEqual(code, 0)
            self.assertFalse(data.exists())
            self.assertEqual(json.loads(output.getvalue())["limits"][0]["limit_id"], "codex")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--data-dir", str(data), "meter"]), 0)
        self.assertEqual({path.name for path in data.iterdir()}, {"meter.sqlite3"})
        for action in ("history", "report"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--data-dir", str(data), "meter", action]), 0)
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["--data-dir", str(data), "meter", "history", "--limit", "0"]), 2)
        self.assertNotIn(str(data), errors.getvalue())

    def test_unsupported_database_version_fails_without_migration(self):
        record_snapshot(self.root, source())
        with sqlite3.connect(self.root / "meter.sqlite3") as connection:
            connection.execute("PRAGMA user_version=2")
        with self.assertRaises(ValueError):
            load_snapshots(self.root)
        with self.assertRaises(ValueError):
            record_snapshot(self.root, source())

    def test_normalizer_invalid_numbers_and_unavailable_sources(self):
        raw = source()
        raw["rate_limits"]["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = float("nan")
        self.assertIsNone(normalize_snapshot(raw)["limits"][0]["windows"][0]["used_percent"])
        raw["rate_limits"] = None
        raw["account_usage"] = None
        snapshot = normalize_snapshot(raw)
        self.assertIn("unavailable", snapshot_summary(snapshot))
        self.assertIsNone(snapshot["account_usage"]["lifetime_tokens"])
        invalid = copy.deepcopy(raw)
        invalid["finished_at"] = -1
        with self.assertRaises(ValueError):
            normalize_snapshot(invalid)


if __name__ == "__main__":
    unittest.main()
