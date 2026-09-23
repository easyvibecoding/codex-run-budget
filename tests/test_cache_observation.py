from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.cache_observation import observe_cache  # noqa: E402


def request(stamp, cached, *, model="gpt-6-sol", effort="low", status="observed",
            thread="parent"):
    return {
        "observed_at": stamp, "thread_hash": thread,
        "input_tokens": 2000, "cached_input_tokens": cached,
        "model": model, "reasoning_effort": effort, "service_tier": "standard",
        "context_status": {"model": status, "reasoning_effort": status,
                           "service_tier": "observed"},
    }


class CacheObservationTest(unittest.TestCase):
    def test_empty_is_unknown_not_zero_hit_rate(self):
        observed = observe_cache([])
        self.assertEqual(observed["status"], "no_observations")
        self.assertIsNone(observed["read_share_percent"])

    def test_reads_and_setting_changes_are_separate_evidence(self):
        observed = observe_cache([
            request(1, 0), request(2, 1500),
            request(3, 0, model="gpt-6-astra", effort="high"),
            request(4, 0, model="gpt-6-astra", effort="high", status="missing"),
            request(2, 1000, thread="child"),
        ])
        self.assertEqual(observed["read_share_percent"], 25.0)
        self.assertEqual(observed["requests_with_cache_read"], 2)
        self.assertEqual(observed["adjacent_pairs"], 3)
        self.assertEqual(observed["observed_setting_changes"]["model"], 1)
        self.assertEqual(observed["observed_setting_changes"]["reasoning_effort"], 1)
        self.assertEqual(observed["unresolved_setting_pairs"]["model"], 1)
        self.assertEqual(observed["interpretation"], "local_observation_not_server_diagnostics")

    def test_same_timestamp_does_not_establish_order(self):
        observed = observe_cache([request(1, 0), request(1, 0, model="gpt-6-astra"),
                                  request(2, 0)])
        self.assertEqual(observed["adjacent_pairs"], 0)
        self.assertEqual(observed["observed_setting_changes"]["model"], 0)


if __name__ == "__main__":
    unittest.main()
