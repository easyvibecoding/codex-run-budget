from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.meter import (  # noqa: E402
    compare_snapshots,
    estimate_summary,
    normalize_snapshot,
    report_summary,
    snapshot_summary,
    tasks_summary,
)
from codex_run_budget.report_i18n import LOCALES  # noqa: E402
from codex_run_budget.survey import survey_summary  # noqa: E402

OBSERVATION_DIR = PLUGIN / "lib/codex_run_budget/assets/locales/observations"


def _source(stamp: float = 1000, used: float = 9) -> dict:
    return {
        "started_at": stamp - 1,
        "finished_at": stamp,
        "rate_limits": {
            "accountId": "private-account",
            "ordinaryUsageAllowed": True,
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "planType": "pro",
                    "primary": {
                        "usedPercent": used,
                        "windowDurationMins": 10080,
                        "resetsAt": 100000,
                    },
                }
            },
        },
        "account_usage": {"summary": {"lifetimeTokens": 123456}},
        "thread_usage": [],
        "errors": [],
    }


def _survey_report() -> dict:
    return {
        "selection": {
            "since": "2026-09-13T00:00:00+00:00",
            "until": "2026-09-13T01:00:00+00:00",
            "selected_files": 1,
            "coverage_limited": False,
        },
        "audit": {
            "threads": [{"role": "parent"}, {"role": "subagent"}],
            "request_usage": {
                "unique_responses": 2,
                "input_tokens": 1200,
                "cached_input_tokens": 200,
                "output_tokens": 300,
                "total_tokens": 1500,
            },
            "waits": [
                {
                    "calls": 2,
                    "timed_out": 1,
                    "event_returns": 1,
                    "unknown": 0,
                    "short_timeouts": 1,
                }
            ],
            "tools": [
                {
                    "unchanged_result_repeats": 1,
                    "changed_result_repeats": 0,
                    "unknown_result_repeats": 0,
                }
            ],
            "lifecycle": {
                "summary": {"turns": 1, "completed": 1},
                "turns": [],
            },
        },
    }


class ObservationI18nTest(unittest.TestCase):
    def test_catalogs_have_identical_keys_and_placeholders(self):
        catalogs = {
            locale: json.loads((OBSERVATION_DIR / f"{locale}.json").read_text())
            for locale in LOCALES
        }
        keys = set(catalogs["en"])
        self.assertTrue(keys)
        for locale, values in catalogs.items():
            self.assertEqual(set(values), keys, locale)
            for key in keys:
                self.assertEqual(
                    sorted(re.findall(r"\{([A-Za-z0-9_]+)\}", catalogs["en"][key])),
                    sorted(re.findall(r"\{([A-Za-z0-9_]+)\}", values[key])),
                    f"{locale}:{key}",
                )

    def test_all_locales_render_without_reading_preferences_or_mutating_input(self):
        snapshot = normalize_snapshot(_source())
        original = copy.deepcopy(snapshot)
        for locale in LOCALES:
            with patch("codex_run_budget.report_i18n.resolve_locale", side_effect=AssertionError):
                rendered = snapshot_summary(snapshot, locale=locale)
            self.assertTrue(rendered)
        self.assertEqual(snapshot, original)

    def test_human_values_are_translated_but_native_identifiers_and_codes_remain(self):
        snapshot = normalize_snapshot(_source())
        snapshot["official_thread_usage"] = [
            {
                "thread_hash": "a" * 64,
                "status": "backend_estimate",
                "groups": [
                    {
                        "model": "gpt-6-astra",
                        "reasoning_effort": "xhigh",
                        "speed": "fast",
                        "total_tokens": 1234567,
                        "estimated_credits_per_million_tokens": 12.5,
                    }
                ],
            }
        ]
        text = snapshot_summary(snapshot, locale="de")
        self.assertIn("Nativer Codex-Kontingentmesser", text)
        self.assertIn("gpt-6-astra", text)
        self.assertIn("backend_estimate", text)
        self.assertIn("1.234.567", text)
        self.assertNotIn("native quota meter", text)

    def test_report_keeps_known_and_unknown_issue_codes(self):
        before = normalize_snapshot(_source())
        after = normalize_snapshot(_source(1100, used=10))
        interval = compare_snapshots(before, after)
        interval["windows"][0]["issues"] = ["plan_changed", "future_issue_code"]
        report = {
            "latest": after,
            "interval": interval,
            "local_usage": {"models": [], "request_context_usage": []},
        }
        original = copy.deepcopy(report)
        rendered = report_summary(report, locale="ja")
        self.assertIn("plan_changed", rendered)
        self.assertIn("future_issue_code", rendered)
        self.assertIn("プランが変更されました", rendered)
        self.assertEqual(report, original)

    def test_tasks_and_estimate_leave_model_effort_fast_and_status_values_raw(self):
        task = {
            "thread_hash": "a" * 64,
            "turn_hash": "b" * 64,
            "model": "gpt-6-astra",
            "reasoning_effort": "ultra",
            "service_tier": "fast",
            "fast_mode": True,
            "plan_type": "pro",
            "unique_responses": 2,
            "total_tokens": 1234567,
        }
        report = {
            "since": 1000,
            "until": 2000,
            "local_usage": {
                "task_count": 1,
                "request_context_usage": [task],
                "limitations": [],
            },
        }
        rendered = tasks_summary(report, locale="fr")
        for value in ("gpt-6-astra", "ultra", "fast", "true", "pro"):
            self.assertIn(value, rendered)
        self.assertIn("Observations inter-Tasks", rendered)

        rows = [
            {
                **task,
                "input_tokens": 1_000_000,
                "cached_input_tokens": 800_000,
                "output_tokens": 100_000,
                "observed_fast_mode": True,
                "requests": 2,
                "standard_scenario_credits": "1.5",
                "fast_scenario_credits": "3.75",
                "status": "priced",
            }
        ]
        scenarios = {
            "reference": {
                "verified_on": "2026-09-12",
                "freshness": {"status": "current"},
                "token_rate_source": "fixture",
            },
            "coverage": {"priced_requests": 1, "excluded_requests": 0},
            "standard_scenario_credits": "1.5",
            "fast_scenario_credits": "3.75",
            "rows": rows,
            "limitations": [],
        }
        estimate = estimate_summary({"credit_scenarios": scenarios}, locale="pt")
        self.assertIn("gpt-6-astra", estimate)
        self.assertIn("priced", estimate)
        self.assertIn("Cenários contrafactuais", estimate)

    def test_survey_localizes_human_labels_and_preserves_status_rows(self):
        report = _survey_report()
        rendered = survey_summary(report, lifecycle_details=True, locale="zh-Hans")
        self.assertIn("Run Budget 近期 Task 调查", rendered)
        self.assertIn("wait_agent", rendered)
        self.assertIn("回合生命周期", rendered)
        self.assertIn("completed", rendered)

    def test_default_english_remains_directly_usable(self):
        snapshot = normalize_snapshot(_source())
        self.assertIn("Codex native quota meter", snapshot_summary(snapshot))
        self.assertIn(
            "Cross-task observations",
            tasks_summary({"local_usage": {}, "since": 1, "until": 2}),
        )
        self.assertIn(
            "Run Budget recent-task survey",
            survey_summary(
                {
                    "selection": {
                        "since": "a",
                        "until": "b",
                        "selected_files": 0,
                        "coverage_limited": False,
                    },
                    "audit": {},
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
