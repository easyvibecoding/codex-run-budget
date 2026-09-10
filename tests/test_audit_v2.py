from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.audit import audit_transcript, audit_transcripts  # noqa: E402


def record(kind: str, payload: dict, second: int = 0, *, stamp: str | None = None) -> dict:
    return {
        "type": kind,
        "payload": payload,
        "timestamp": stamp or f"2026-09-10T00:00:{second:02d}Z",
    }


def write_page(root: Path, name: str, records: list[dict]) -> Path:
    path = root / name
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    return path


def usage(input_tokens: int = 10, output_tokens: int = 2) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": 0,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class AuditV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_native_items_inherit_preceding_metadata_and_sequential_boundaries(self) -> None:
        page = write_page(
            self.root,
            "native.jsonl",
            [
                record(
                    "session_meta",
                    {
                        "id": "parent-thread",
                        "session_id": "shared-session",
                        "timestamp": "2026-09-09T00:00:00Z",
                    },
                ),
                record("turn_context", {"turn_id": "parent-turn", "model": "gpt-5.6-sol"}),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "parent-call", "name": "private-tool"},
                    1,
                ),
                record(
                    "session_meta",
                    {
                        "id": "child-thread",
                        "parent_thread_id": "parent-thread",
                        "session_id": "shared-session",
                        "timestamp": "2026-09-10T00:00:02Z",
                    },
                    2,
                ),
                record("turn_context", {"turn_id": "child-turn", "model": "gpt-5.6-luna"}, 3),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "child-call", "name": "private-tool"},
                    4,
                ),
            ],
        )
        result = audit_transcript(page)
        models = {(row["thread_hash"], row["model"]): row["calls"] for row in result["model_usage"]}
        self.assertEqual(len(models), 2)
        self.assertEqual(
            {row["model"] for row in result["model_usage"]}, {"gpt-5.6-sol", "gpt-5.6-luna"}
        )
        self.assertEqual(result["diagnostics"]["ambiguous_thread_metadata"], 0)
        self.assertEqual(result["diagnostics"]["missing_model_attribution"], 0)
        threads = {row["role"]: row for row in result["threads"]}
        self.assertEqual(threads["parent"]["started_at"], 1788912000.0)
        self.assertEqual(threads["subagent"]["parent_hash"], threads["parent"]["thread_hash"])

    def test_metadata_is_preceding_only_and_malformed_boundary_does_not_reuse_old_thread(
        self,
    ) -> None:
        page = write_page(
            self.root,
            "boundaries.jsonl",
            [
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "before", "name": "tool"},
                ),
                record("session_meta", {"id": "thread"}, 1),
                record("turn_context", {"turn_id": "turn", "model": "gpt-5.6-sol"}, 2),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "bound", "name": "tool"},
                    3,
                ),
                record("session_meta", {}, 4),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "after", "name": "tool"},
                    5,
                ),
            ],
        )
        result = audit_transcript(page)
        by_thread = {row["thread_hash"]: row["calls"] for row in result["model_usage"]}
        self.assertEqual(sum(by_thread.values()), 3)
        self.assertEqual(by_thread["unknown"], 2)
        self.assertEqual(result["diagnostics"]["missing_thread_metadata"], 1)

    def test_reverse_page_order_is_identical_and_request_dedup_is_stable(self) -> None:
        first = write_page(
            self.root,
            "first.jsonl",
            [
                record("session_meta", {"id": "thread-a"}),
                record("turn_context", {"turn_id": "turn-a", "model": "gpt-5.6-sol"}),
                record("token_usage_record", {"response_id": "same", "usage": usage()}, 1),
            ],
        )
        second = write_page(
            self.root,
            "second.jsonl",
            [
                record("session_meta", {"id": "thread-a"}),
                record("turn_context", {"turn_id": "turn-a", "model": "gpt-5.6-sol"}),
                record("token_usage_record", {"response_id": "same", "usage": usage()}, 2),
            ],
        )
        forward = audit_transcripts([first, second])
        reverse = audit_transcripts([second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["request_usage"]["unique_responses"], 1)
        self.assertEqual(forward["diagnostics"]["duplicate_usage_records"], 1)

    def test_cumulative_decreases_stay_within_source_page_and_latest_is_not_added(self) -> None:
        first = write_page(
            self.root,
            "cumulative-a.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record(
                    "event_msg",
                    {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 100}}},
                    1,
                ),
            ],
        )
        second = write_page(
            self.root,
            "cumulative-b.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record(
                    "event_msg",
                    {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 80}}},
                    2,
                ),
            ],
        )
        report = audit_transcripts([first, second])
        self.assertEqual(report["diagnostics"]["cumulative_decreases"], 0)
        self.assertEqual(report["diagnostics"]["cumulative_multiple_sources"], 1)
        self.assertEqual(report["latest_cumulative_tokens"], 80)
        self.assertEqual(
            sorted(row["total_tokens"] for row in report["latest_cumulative_tokens_by_source"]),
            [80, 100],
        )

    def test_call_and_result_identity_is_thread_scoped_not_session_scoped(self) -> None:
        page = write_page(
            self.root,
            "threads.jsonl",
            [
                record("session_meta", {"id": "thread-a", "session_id": "shared"}),
                record("turn_context", {"turn_id": "turn-a", "model": "gpt-5.6-sol"}),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "same-call", "name": "tool"},
                    1,
                ),
                record(
                    "response_item",
                    {"type": "function_call_output", "call_id": "same-call", "output": "a"},
                    2,
                ),
                record("session_meta", {"id": "thread-b", "session_id": "shared"}, 3),
                record("turn_context", {"turn_id": "turn-b", "model": "gpt-5.6-luna"}, 4),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "same-call", "name": "tool"},
                    5,
                ),
                record(
                    "response_item",
                    {"type": "function_call_output", "call_id": "same-call", "output": "b"},
                    6,
                ),
            ],
        )
        result = audit_transcript(page)
        self.assertEqual(sum(row["calls"] for row in result["tools"]), 2)
        self.assertEqual(sum(row["completed_calls"] for row in result["tools"]), 2)
        self.assertEqual(result["diagnostics"]["call_id_collisions"], 1)
        self.assertEqual(result["diagnostics"]["duplicate_call_records"], 0)

    def test_explicit_event_ids_override_active_metadata_context(self) -> None:
        page = write_page(
            self.root,
            "explicit.jsonl",
            [
                record("session_meta", {"id": "active"}),
                record("turn_context", {"turn_id": "active-turn", "model": "gpt-5.6-sol"}),
                record(
                    "token_usage_record",
                    {
                        "response_id": "response",
                        "thread_id": "explicit-thread",
                        "turn_id": "explicit-turn",
                        "usage": usage(),
                    },
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "call",
                        "thread_id": "explicit-thread",
                        "turn_id": "explicit-turn",
                        "name": "tool",
                    },
                    1,
                ),
            ],
        )
        result = audit_transcript(page)
        active_hash = next(
            row["thread_hash"] for row in result["threads"] if row["role"] == "parent"
        )
        self.assertNotEqual(result["model_usage"][0]["thread_hash"], active_hash)
        self.assertEqual(result["model_usage"][0]["model"], "unknown")
        self.assertEqual(result["diagnostics"]["missing_model_attribution"], 2)
        self.assertEqual(result["diagnostics"]["conflicting_response_attribution"], 0)

    def test_conflicting_response_id_is_explicit_and_deterministic(self) -> None:
        pages = [
            write_page(
                self.root,
                "usage-a.jsonl",
                [record("token_usage_record", {"response_id": "same", "usage": usage(10, 2)})],
            ),
            write_page(
                self.root,
                "usage-b.jsonl",
                [record("token_usage_record", {"response_id": "same", "usage": usage(20, 2)})],
            ),
        ]
        forward = audit_transcripts(pages)
        reverse = audit_transcripts(pages[::-1])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["request_usage"]["unique_responses"], 1)
        self.assertEqual(forward["diagnostics"]["conflicting_usage_records"], 1)
        self.assertEqual(forward["diagnostics"]["conflicting_response_attribution"], 1)

    def test_wait_outcomes_are_mutually_exclusive_and_short_uses_actual_duration(self) -> None:
        page = write_page(
            self.root,
            "waits.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record("turn_context", {"turn_id": "turn", "model": "gpt-5.6-sol"}),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "timeout",
                        "namespace": "collaboration",
                        "name": "wait_agent",
                        "arguments": '{"timeout_ms": 3600000}',
                    },
                    1,
                ),
                record(
                    "event_msg",
                    {
                        "type": "item_completed",
                        "item": {"id": "timeout"},
                        "started_at_ms": 1000,
                        "completed_at_ms": 2000,
                    },
                    2,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call_output",
                        "call_id": "timeout",
                        "output": '{"timed_out":true}',
                    },
                    3,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "return",
                        "namespace": "collaboration",
                        "name": "wait_agent",
                        "arguments": '{"timeout_ms": 3600000}',
                    },
                    4,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call_output",
                        "call_id": "return",
                        "output": '{"timed_out":false}',
                    },
                    5,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "unknown",
                        "namespace": "collaboration",
                        "name": "wait_agent",
                        "arguments": "not-json",
                    },
                    6,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call_output",
                        "call_id": "unknown",
                        "output": "{}",
                    },
                    7,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "ignored",
                        "namespace": "untrusted",
                        "name": "wait_agent",
                        "arguments": '{"timeout_ms": 1}',
                    },
                    8,
                ),
            ],
        )
        result = audit_transcript(page)
        self.assertEqual(len(result["waits"]), 1)
        wait = result["waits"][0]
        self.assertEqual(wait["calls"], 3)
        self.assertEqual(wait["timed_out"] + wait["event_returns"] + wait["unknown"], 3)
        self.assertEqual(wait["timed_out"], 1)
        self.assertEqual(wait["event_returns"], 1)
        self.assertEqual(wait["unknown"], 1)
        self.assertEqual(wait["short_timeouts"], 1)
        self.assertEqual(wait["actual_duration_ms"], {"count": 3, "p50": 1000, "p90": 1000})
        self.assertEqual(result["diagnostics"]["invalid_wait_arguments"], 1)
        self.assertEqual(result["diagnostics"]["invalid_wait_results"], 1)

    def test_window_excludes_outputs_and_timing_but_keeps_unknown_outcome(self) -> None:
        page = write_page(
            self.root,
            "window.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record("turn_context", {"turn_id": "turn", "model": "gpt-5.6-sol"}),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "wait",
                        "namespace": "collaboration",
                        "name": "wait_agent",
                        "arguments": '{"timeout_ms": 1000}',
                    },
                    1,
                ),
                record(
                    "response_item",
                    {
                        "type": "function_call_output",
                        "call_id": "wait",
                        "output": '{"timed_out":true}',
                    },
                    9,
                ),
                record(
                    "event_msg",
                    {
                        "type": "item_completed",
                        "item": {"id": "wait"},
                        "started_at_ms": 100,
                        "completed_at_ms": 200,
                    },
                    9,
                ),
            ],
        )
        since = 1788998401.0
        until = 1788998402.0
        result = audit_transcripts([page], since=since, until=until)
        self.assertEqual(result["tools"][0]["calls"], 1)
        self.assertEqual(result["tools"][0]["completed_calls"], 0)
        self.assertEqual(result["waits"][0]["timed_out"], 0)
        self.assertEqual(result["waits"][0]["unknown"], 1)
        self.assertEqual(result["waits"][0]["actual_duration_ms"]["count"], 0)

    def test_explicit_item_timing_wins_over_call_output_span(self) -> None:
        page = write_page(
            self.root,
            "timing.jsonl",
            [
                record("session_meta", {"id": "thread"}),
                record("turn_context", {"turn_id": "turn", "model": "gpt-5.6-sol"}),
                record(
                    "response_item",
                    {"type": "function_call", "call_id": "call", "namespace": "x", "name": "tool"},
                    1,
                ),
                record(
                    "response_item",
                    {"type": "function_call_output", "call_id": "call", "output": "ok"},
                    9,
                ),
                record(
                    "event_msg",
                    {
                        "type": "item_completed",
                        "item": {"id": "call"},
                        "started_at_ms": 10,
                        "completed_at_ms": 25,
                    },
                    9,
                ),
            ],
        )
        stats = audit_transcript(page)["tools"][0]
        self.assertEqual(stats["observed_span_ms"], 8000)
        self.assertEqual(stats["explicit_timed_calls"], 1)
        self.assertEqual(stats["explicit_span_ms"], 15)

    def test_custom_models_and_identifiers_are_hashed(self) -> None:
        page = write_page(
            self.root,
            "privacy.jsonl",
            [
                record("session_meta", {"id": "private-thread"}),
                record("turn_context", {"turn_id": "private-turn", "model": "private-model"}),
                record(
                    "response_item",
                    {
                        "type": "function_call",
                        "call_id": "private-call",
                        "namespace": "private-namespace",
                        "name": "private-tool",
                        "arguments": '{"secret":"private-argument"}',
                    },
                ),
            ],
        )
        serialized = json.dumps(audit_transcript(page), sort_keys=True)
        for secret in (
            "private-thread",
            "private-turn",
            "private-model",
            "private-call",
            "private-namespace",
            "private-tool",
            "private-argument",
        ):
            self.assertNotIn(secret, serialized)
        self.assertRegex(serialized, r'"model": "hash:[0-9a-f]{64}"')

    def test_resource_limits_and_symlink_diagnostics_are_visible(self) -> None:
        oversized = write_page(self.root, "oversized.jsonl", [record("task_started", {})])
        regular = write_page(self.root, "regular.jsonl", [record("task_started", {})])
        alias = self.root / "alias.jsonl"
        alias.symlink_to(regular)
        with patch("codex_run_budget.audit.MAX_TRANSCRIPT_BYTES", 1):
            report = audit_transcripts([oversized, alias])
        self.assertEqual(report["diagnostics"]["oversized_files"], 1)
        self.assertEqual(report["diagnostics"]["not_regular_files"], 1)
        self.assertGreaterEqual(report["diagnostics"]["resource_limited"], 1)

    def test_record_and_total_limits_do_not_read_unbounded_data(self) -> None:
        page = write_page(
            self.root,
            "bounded.jsonl",
            [record("task_started", {}) for _ in range(3)],
        )
        with patch("codex_run_budget.audit.MAX_AUDIT_RECORDS", 1):
            result = audit_transcript(page)
        self.assertEqual(result["diagnostics"]["records"], 1)
        self.assertEqual(result["diagnostics"]["record_limit_skips"], 1)
        self.assertEqual(result["diagnostics"]["resource_limited"], 1)


if __name__ == "__main__":
    unittest.main()
