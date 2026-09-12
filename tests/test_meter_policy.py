from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.meter import (  # noqa: E402
    estimate_summary,
    normalize_snapshot,
    snapshot_summary,
)
from codex_run_budget.meter_policy import credit_scenarios, pricing_context  # noqa: E402


def tokens(model="gpt-6-astra", **changes):
    return {
        "thread_hash": "a" * 64,
        "turn_hash": "b" * 64,
        "model": model,
        "reasoning_effort": "high",
        "fast_mode": None,
        "unique_responses": 1,
        "input_tokens": 1_000_000,
        "cached_input_tokens": 800_000,
        "output_tokens": 100_000,
        "total_tokens": 1_100_000,
        **changes,
    }


class CreditScenariosTest(unittest.TestCase):
    def test_cache_and_reasoning_are_not_double_counted(self):
        row = tokens(reasoning_output_tokens=90_000)
        result = credit_scenarios([row])
        self.assertEqual(Decimal(result["standard_scenario_credits"]), Decimal("195"))
        self.assertEqual(Decimal(result["fast_scenario_credits"]), Decimal("487.5"))
        self.assertEqual(result["coverage"], {"priced_requests": 1, "excluded_requests": 0})
        self.assertIsNone(result["actual_charge_credits"])
        self.assertIsNone(result["quota_percentage_points"])

    def test_equal_total_tokens_can_have_different_rates_and_cache_costs(self):
        astra = credit_scenarios([tokens()])
        luna = credit_scenarios([tokens("gpt-5.6-luna")])
        uncached = credit_scenarios([tokens(cached_input_tokens=0)])
        self.assertEqual(Decimal(luna["standard_scenario_credits"]), Decimal("4.4"))
        self.assertGreater(
            Decimal(uncached["standard_scenario_credits"]),
            Decimal(astra["standard_scenario_credits"]),
        )

    def test_unknown_mode_is_never_filled_or_priced_as_actual(self):
        for mode in (None, True, False):
            result = credit_scenarios([tokens(fast_mode=mode)])
            self.assertIs(result["rows"][0]["observed_fast_mode"], mode)
            self.assertIsNone(result["actual_charge_credits"])
            self.assertEqual(result["historical_rate_applicability"], "not_established")
            self.assertEqual(Decimal(result["standard_scenario_credits"]), Decimal("195"))

    def test_missing_model_rate_and_mini_fast_are_not_guessed(self):
        result = credit_scenarios([tokens(), tokens("gpt-5.3-codex-spark"), tokens("unknown")])
        self.assertEqual(result["coverage"], {"priced_requests": 1, "excluded_requests": 2})
        self.assertIsNone(result["rows"][1]["standard_scenario_credits"])
        mini = credit_scenarios([tokens(), tokens("gpt-5.4-mini")])
        self.assertIsNone(mini["fast_scenario_credits"])
        self.assertIsNotNone(mini["standard_scenario_credits"])
        self.assertIsNone(credit_scenarios([])["standard_scenario_credits"])
        self.assertIsNone(credit_scenarios([tokens("unknown")])["standard_scenario_credits"])

    def test_invalid_or_unsupported_token_bases_are_excluded(self):
        changes = [
            {"cached_input_tokens": 1_000_001},
            {"output_tokens": -1},
            {"input_tokens": True},
            {"total_tokens": 1},
            {"input_tokens": 2**63},
            {"cache_write_input_tokens": 1},
            {"cache_write_input_tokens": "0"},
            {"reasoning_output_tokens": 100_001},
        ]
        for change in changes:
            with self.subTest(change=change):
                result = credit_scenarios([tokens(**change)])
                self.assertIsNone(result["standard_scenario_credits"])
                self.assertEqual(result["coverage"]["excluded_requests"], 1)

    def test_reasoning_effort_has_no_invented_multiplier(self):
        low = credit_scenarios([tokens(reasoning_effort="low")])
        high = credit_scenarios([tokens(reasoning_effort="ultra")])
        self.assertEqual(low["standard_scenario_credits"], high["standard_scenario_credits"])

    def test_reference_age_is_not_a_historical_rate_guarantee(self):
        self.assertEqual(
            pricing_context(as_of=date(2026, 10, 13))["freshness"]["status"], "review_due"
        )
        prior = pricing_context(as_of=date(2026, 9, 1))["freshness"]
        self.assertEqual(prior["status"], "verification_after_as_of")
        self.assertFalse(prior["official_validity_period_known"])

    def test_cli_estimate_is_offline_and_uses_exact_task_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "absent"
            selected = "12345678-1234-1234-1234-123456789abc"
            observed = {"local_usage": {"request_context_usage": [tokens()]}}
            with patch("codex_run_budget.meter.meter_tasks", return_value=observed) as scan:
                with patch("codex_run_budget.meter_source.read_meter_sources") as native:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(
                            [
                                "--data-dir",
                                str(root),
                                "meter",
                                "estimate",
                                "--days",
                                "1",
                                "--thread",
                                selected,
                                "--json",
                            ]
                        )
            self.assertEqual(code, 0)
            native.assert_not_called()
            self.assertFalse(root.exists())
            self.assertEqual(scan.call_args.kwargs["thread_ids"], [selected])
            result = json.loads(output.getvalue())
            self.assertIn("NOT actual charges", estimate_summary(result))
            self.assertIsNone(result["credit_scenarios"]["quota_percentage_points"])


class NativeControlsTest(unittest.TestCase):
    def test_contradictory_backend_cache_split_suppresses_ratio(self):
        thread = "12345678-1234-1234-1234-123456789abc"
        report = normalize_snapshot(
            {
                "started_at": 1,
                "finished_at": 2,
                "thread_usage": [
                    {
                        "thread_id": thread,
                        "response": {
                            "threadUsage": {
                                "threadId": thread,
                                "groups": [
                                    {
                                        "model": "gpt-6-astra",
                                        "inputTokens": 10,
                                        "cachedInputTokens": 6,
                                        "netNewInputTokens": 8,
                                        "outputTokens": 2,
                                        "totalTokens": 12,
                                        "estimatedUsageCreditsMicros": 1000,
                                    }
                                ],
                            }
                        },
                    }
                ],
            }
        )
        group = report["official_thread_usage"][0]["groups"][0]
        self.assertEqual(group["token_status"], "conflicted")
        self.assertIsNone(group["estimated_credits_per_million_tokens"])

    def snapshot(self, **bucket):
        return normalize_snapshot(
            {
                "started_at": 1,
                "finished_at": 2,
                "rate_limits": {"rateLimitsByLimitId": {"codex": bucket}},
            }
        )

    def test_credits_only_account_is_available_without_inventing_percent(self):
        report = self.snapshot(credits={"hasCredits": True, "unlimited": False, "balance": "42.5"})
        self.assertEqual(report["source_status"], "available")
        self.assertEqual(report["limits"][0]["windows"], [])
        self.assertIsNone(report["ordinary_usage_allowed"])
        self.assertIn("credit balance 42.5", snapshot_summary(report))
        self.assertIn("permission: unknown", snapshot_summary(report))

    def test_backend_limit_reasons_are_allowlisted_not_guessed_from_quota(self):
        for reason in (
            "rate_limit_reached",
            "workspace_owner_credits_depleted",
            "workspace_member_credits_depleted",
            "workspace_owner_usage_limit_reached",
            "workspace_member_usage_limit_reached",
        ):
            report = self.snapshot(rateLimitReachedType=reason)
            self.assertEqual(report["limits"][0]["rate_limit_reached_type"], reason)
            self.assertEqual(report["source_status"], "available")
        private = self.snapshot(rateLimitReachedType="private-backend-detail")
        self.assertNotIn("private-backend-detail", json.dumps(private))
        self.assertEqual(private["source_status"], "unavailable")
        numeric = self.snapshot(primary={"usedPercent": 100})
        self.assertIsNone(numeric["limits"][0]["rate_limit_reached_type"])
        self.assertIsNone(numeric["ordinary_usage_allowed"])

    def test_native_denial_is_not_overridden_by_empty_window_or_credits(self):
        source = {
            "started_at": 1,
            "finished_at": 2,
            "rate_limits": {
                "ordinaryUsageAllowed": False,
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 0},
                        "credits": {"hasCredits": True, "unlimited": True},
                    }
                },
            },
        }
        report = normalize_snapshot(source)
        self.assertIn("permission: not_allowed", snapshot_summary(report))
        old = copy.deepcopy(report)
        old["limits"][0].pop("rate_limit_reached_type")
        self.assertIn("reached type unknown", snapshot_summary(old))

    def test_missing_and_false_controls_remain_distinct(self):
        report = self.snapshot(
            spendControlReached=False,
            individualLimit={
                "limit": "100",
                "used": "25",
                "remainingPercent": 75,
                "resetsAt": 10000,
            },
        )
        self.assertIs(report["limits"][0]["spend_control_reached"], False)
        self.assertIn("spend control reached false", snapshot_summary(report))
        self.assertIn("used 25 / 100", snapshot_summary(report))
        self.assertIsNone(self.snapshot()["limits"][0]["spend_control_reached"])


if __name__ == "__main__":
    unittest.main()
