from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.audit import audit_transcript, audit_transcripts  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402


def record(kind: str, payload: dict, second: int = 0, *, stamp: str | None = None) -> dict:
    return {
        "type": kind,
        "payload": payload,
        "timestamp": stamp or f"2026-09-12T00:00:{second:02d}Z",
    }


def usage(value: int = 10) -> dict[str, int]:
    return {
        "input_tokens": value,
        "cached_input_tokens": value // 2,
        "cache_write_input_tokens": 0,
        "output_tokens": 2,
        "reasoning_output_tokens": 1,
        "total_tokens": value + 2,
    }


def token_count(plan: object, second: int, total: int = 1) -> dict:
    return record(
        "event_msg",
        {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": total}},
            "rate_limits": {"plan_type": plan},
        },
        second,
    )


def write_page(root: Path, name: str, rows: list[dict]) -> Path:
    path = root / name
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


class MeterContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_explicit_missing_quota_plan_clears_prior_observation(self):
        missing = token_count("pro", 4)
        missing["payload"]["rate_limits"] = {}
        page = write_page(
            self.root,
            "missing-plan.jsonl",
            [
                record("session_meta", {"id": "thread"}, 0),
                record("turn_context", {"turn_id": "turn", "model": "gpt-6-astra"}, 1),
                token_count("pro", 2),
                record("token_usage_record", {"response_id": "before", "usage": usage()}, 3),
                missing,
                record("token_usage_record", {"response_id": "after", "usage": usage()}, 5),
            ],
        )
        rows = audit_transcripts([page])["request_context_usage"]
        self.assertEqual({row["plan_type"] for row in rows}, {"pro", None})

    def test_cross_task_turn_role_effort_fast_and_plan_usage(self) -> None:
        parent = write_page(
            self.root,
            "parent.jsonl",
            [
                record("session_meta", {"id": "parent-thread"}),
                record(
                    "turn_context",
                    {
                        "turn_id": "parent-turn",
                        "model": "gpt-5.6-sol",
                        "effort": "low",
                        "collaboration_mode": {"settings": {"reasoning_effort": "low"}},
                        "service_tier": "fast",
                    },
                    1,
                ),
                token_count("pro", 2),
                record(
                    "token_usage_record",
                    {"response_id": "parent-response", "usage": usage(10)},
                    3,
                ),
            ],
        )
        child = write_page(
            self.root,
            "child.jsonl",
            [
                record(
                    "session_meta",
                    {"id": "child-thread", "parent_thread_id": "parent-thread"},
                ),
                record(
                    "turn_context",
                    {
                        "turn_id": "child-turn",
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "high",
                        "serviceTier": "standard",
                    },
                    1,
                ),
                token_count("plus", 2),
                record(
                    "token_usage_record",
                    {"response_id": "child-response", "usage": usage(20)},
                    3,
                ),
            ],
        )
        rows = audit_transcripts([parent, child])["request_context_usage"]
        self.assertEqual(len(rows), 2)
        by_model = {row["model"]: row for row in rows}
        self.assertEqual(by_model["gpt-5.6-sol"]["role"], "parent")
        self.assertEqual(by_model["gpt-5.6-sol"]["reasoning_effort"], "low")
        self.assertEqual(by_model["gpt-5.6-sol"]["fast_mode"], True)
        self.assertEqual(by_model["gpt-5.6-sol"]["plan_type"], "pro")
        self.assertEqual(by_model["gpt-5.6-sol"]["total_tokens"], 12)
        self.assertEqual(by_model["gpt-5.6-luna"]["role"], "subagent")
        self.assertEqual(by_model["gpt-5.6-luna"]["fast_mode"], False)
        self.assertEqual(by_model["gpt-5.6-luna"]["plan_type"], "plus")

    def test_same_turn_dynamic_context_splits_rows(self) -> None:
        page = write_page(
            self.root,
            "dynamic.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record(
                    "turn_context",
                    {"turn_id": "turn", "model": "gpt-5.6-sol", "service_tier": "fast"},
                    1,
                ),
                record(
                    "token_usage_record",
                    {"response_id": "fast-response", "usage": usage()},
                    2,
                ),
                # Repeated turn_context is an in-turn update, not a global
                # conflict that should erase the first request's context.
                record(
                    "turn_context",
                    {
                        "turn_id": "turn",
                        "model": "gpt-5.6-sol",
                        "service_tier": "standard",
                    },
                    3,
                ),
                record(
                    "token_usage_record",
                    {"response_id": "standard-response", "usage": usage(20)},
                    4,
                ),
            ],
        )
        rows = audit_transcript(page)["request_context_usage"]
        self.assertEqual({row["service_tier"] for row in rows}, {"fast", "standard"})
        self.assertEqual({row["fast_mode"] for row in rows}, {True, False})
        self.assertEqual(sum(row["unique_responses"] for row in rows), 2)
        self.assertTrue(all(row["context_status"]["service_tier"] == "observed" for row in rows))

    def test_fast_mapping_default_priority_standard_and_missing(self) -> None:
        rows = [record("session_meta", {"id": "thread"})]
        for index, tier in enumerate(("fast", "standard", "default", "priority", None), start=1):
            rows.append(
                record(
                    "turn_context",
                    {
                        "turn_id": f"turn-{index}",
                        "model": "gpt-5.6-sol",
                        **({"service_tier": tier} if tier is not None else {}),
                    },
                    index,
                )
            )
            rows.append(
                record(
                    "token_usage_record",
                    {"response_id": f"response-{index}", "usage": usage()},
                    index + 5,
                )
            )
        result = audit_transcript(write_page(self.root, "modes.jsonl", rows))
        by_tier = {row["service_tier"]: row for row in result["request_context_usage"]}
        self.assertIs(by_tier["fast"]["fast_mode"], True)
        self.assertIs(by_tier["standard"]["fast_mode"], False)
        self.assertIsNone(by_tier["default"]["fast_mode"])
        self.assertEqual(by_tier["default"]["context_status"]["fast_mode"], "default_unresolved")
        self.assertIsNone(by_tier["priority"]["fast_mode"])
        self.assertEqual(by_tier["priority"]["context_status"]["fast_mode"], "priority_unresolved")
        missing = next(
            row for row in result["request_context_usage"] if row["service_tier"] is None
        )
        self.assertIsNone(missing["fast_mode"])
        self.assertEqual(missing["context_status"]["fast_mode"], "missing")

    def test_duplicate_explicit_context_conflict_is_null(self) -> None:
        rows = [
            record("session_meta", {"id": "thread"}),
            record("turn_context", {"turn_id": "turn", "model": "gpt-5.6-sol"}, 1),
            record(
                "token_usage_record",
                {
                    "response_id": "same-response",
                    "service_tier": "fast",
                    "usage": usage(),
                },
                2,
            ),
            record(
                "token_usage_record",
                {
                    "response_id": "same-response",
                    "service_tier": "standard",
                    "usage": usage(),
                },
                3,
            ),
        ]
        rows_out = audit_transcript(write_page(self.root, "duplicate.jsonl", rows))[
            "request_context_usage"
        ]
        self.assertEqual(len(rows_out), 1)
        row = rows_out[0]
        self.assertIsNone(row["service_tier"])
        self.assertIsNone(row["fast_mode"])
        self.assertEqual(row["context_status"]["service_tier"], "conflict")
        self.assertEqual(row["context_status"]["fast_mode"], "conflict")
        self.assertEqual(row["unique_responses"], 1)

    def test_context_is_preceding_and_timestamp_bounded(self) -> None:
        rows = [
            record("session_meta", {"id": "thread"}),
            # This context is before the request in source order but has a
            # future timestamp, so it cannot attribute the request.
            record(
                "turn_context",
                {"turn_id": "future-turn", "model": "gpt-5.6-sol", "effort": "high"},
                stamp="2026-09-12T00:01:00Z",
            ),
            record(
                "token_usage_record",
                {
                    "response_id": "past-response",
                    "thread_id": "thread",
                    "turn_id": "future-turn",
                    "usage": usage(),
                },
                stamp="2026-09-12T00:00:10Z",
            ),
            # A later context must not fill the preceding request either.
            record(
                "turn_context",
                {"turn_id": "later-turn", "model": "gpt-5.6-luna", "effort": "low"},
                20,
            ),
            record(
                "token_usage_record",
                {"response_id": "later-response", "usage": usage()},
                21,
            ),
        ]
        rows_out = audit_transcript(write_page(self.root, "ordering.jsonl", rows))[
            "request_context_usage"
        ]
        self.assertEqual(len(rows_out), 2)
        past = next(row for row in rows_out if row["turn_hash"] == stable_hash("future-turn"))
        self.assertEqual(past["model"], "unknown")
        self.assertEqual(past["context_status"]["model"], "missing")
        later = next(row for row in rows_out if row["turn_hash"] == stable_hash("later-turn"))
        self.assertEqual(later["model"], "gpt-5.6-luna")
        self.assertEqual(later["reasoning_effort"], "low")

    def test_plan_changes_unknown_before_window_and_page_isolation(self) -> None:
        page = write_page(
            self.root,
            "plans.jsonl",
            [
                record("session_meta", {"id": "thread"}, stamp="2026-09-11T23:59:00Z"),
                record(
                    "turn_context",
                    {"turn_id": "turn", "model": "gpt-5.6-sol", "effort": "medium"},
                    stamp="2026-09-11T23:59:01Z",
                ),
                token_count("pro", 2),
                record("token_usage_record", {"response_id": "pro-response", "usage": usage()}, 3),
                token_count("plus", 4, total=2),
                record("token_usage_record", {"response_id": "plus-response", "usage": usage()}, 5),
                token_count("untrusted-plan", 6, total=3),
                record(
                    "token_usage_record",
                    {"response_id": "unknown-response", "usage": usage()},
                    7,
                ),
            ],
        )
        report = audit_transcripts([page], since=1789171200.0, until=1789171300.0)
        rows = report["request_context_usage"]
        self.assertEqual({row["plan_type"] for row in rows}, {"pro", "plus", None})
        unknown = next(row for row in rows if row["plan_type"] is None)
        self.assertEqual(unknown["context_status"]["plan_type"], "unknown")
        for row in rows:
            if row["plan_type"] is not None:
                self.assertEqual(row["context_status"]["plan_type"], "nearby_observation")
                self.assertEqual(
                    row["context_sources"]["plan_type"], ["token_count.rate_limits.plan_type"]
                )
        self.assertEqual(rows[0]["reasoning_effort"], "medium")

        unknown_a = write_page(
            self.root,
            "unknown-a.jsonl",
            [record("token_usage_record", {"response_id": "a", "usage": usage()})],
        )
        unknown_b = write_page(
            self.root,
            "unknown-b.jsonl",
            [record("token_usage_record", {"response_id": "b", "usage": usage()})],
        )
        isolated = audit_transcripts([unknown_a, unknown_b])["request_context_usage"]
        self.assertEqual(len(isolated), 2)
        self.assertEqual({row["thread_hash"] for row in isolated}, {"unknown"})

    def test_context_privacy_and_full_token_dimensions(self) -> None:
        page = write_page(
            self.root,
            "privacy.jsonl",
            [
                record("session_meta", {"id": "private-thread"}),
                record(
                    "turn_context",
                    {
                        "turn_id": "private-turn",
                        "model": "private-model",
                        "effort": "xhigh",
                        "service_tier": "fast",
                    },
                    1,
                ),
                record(
                    "token_usage_record",
                    {"response_id": "private-response", "usage": usage(100)},
                    2,
                ),
            ],
        )
        result = audit_transcript(page)
        row = result["request_context_usage"][0]
        self.assertEqual(row["cached_input_tokens"], 50)
        self.assertEqual(row["cache_write_input_tokens"], 0)
        self.assertEqual(row["uncached_input_tokens"], 50)
        self.assertEqual(row["reasoning_output_tokens"], 1)
        self.assertEqual(row["total_tokens"], 102)
        serialized = json.dumps(result, sort_keys=True)
        for secret in ("private-thread", "private-turn", "private-model", "private-response"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(row["thread_hash"], stable_hash("private-thread"))
        self.assertRegex(row["model"], r"^hash:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
