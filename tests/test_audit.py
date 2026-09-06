from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.audit import audit_transcript  # noqa: E402


def record(kind, payload, second=0):
    return {"type": kind, "payload": payload, "timestamp": f"2026-09-06T00:00:{second:02d}Z"}


class AuditTest(unittest.TestCase):
    def test_cumulative_reset_is_reported_not_silently_added(self):
        records = [
            record(
                "event_msg",
                {"type": "token_count", "info": {"total_token_usage": {"total_tokens": value}}},
            )
            for value in (100, 100, 20)
        ]
        result = self.audit(records)
        self.assertEqual(result["diagnostics"]["cumulative_decreases"], 1)
        self.assertEqual(result["latest_cumulative_tokens"], 20)
        self.assertIsNone(result["request_minus_latest_cumulative_tokens"])

    def audit(self, records, suffix=""):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-transcript.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in records) + suffix)
            return audit_transcript(path)

    def test_deduplicates_requests_without_adding_cumulative_or_reasoning(self):
        usage = {
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "output_tokens": 10,
            "reasoning_output_tokens": 5,
            "total_tokens": 110,
        }
        request = record("token_usage_record", {"response_id": "private-response", "usage": usage})
        result = self.audit(
            [
                request,
                request,
                record("event_msg", {"type": "token_count", "info": {"total_token_usage": usage}}),
            ]
        )
        self.assertEqual(result["request_usage"]["total_tokens"], 110)
        self.assertEqual(result["request_usage"]["uncached_input_tokens"], 20)
        self.assertEqual(result["request_usage"]["unique_responses"], 1)
        self.assertEqual(result["latest_cumulative_tokens"], 110)
        self.assertEqual(result["diagnostics"]["duplicate_usage_records"], 1)

    def test_repeated_calls_compaction_timing_and_privacy(self):
        def call(identity, arguments, second):
            return record(
                "response_item",
                {
                    "type": "function_call",
                    "call_id": identity,
                    "name": "private-tool",
                    "arguments": arguments,
                },
                second,
            )

        first = call("a", '{"secret":1,"b":2}', 1)
        output = record(
            "response_item",
            {"type": "function_call_output", "call_id": "a", "output": "private-output"},
            3,
        )
        result = self.audit(
            [
                first,
                first,
                output,
                output,
                record("compacted", {}, 4),
                call("b", '{"b":2,"secret":1}', 5),
            ]
        )
        stats = result["tools"][0]
        self.assertEqual(stats["calls"], 2)
        self.assertEqual(stats["completed_calls"], 1)
        self.assertEqual(stats["repeated_calls"], 1)
        self.assertEqual(stats["repeated_after_compaction"], 1)
        self.assertEqual(stats["observed_span_ms"], 2000)
        self.assertEqual(stats["output_bytes"], len("private-output"))
        self.assertIsNone(result["request_usage"])
        serialized = json.dumps(result)
        for secret in ("private-tool", "private-output", "secret", "private-transcript"):
            self.assertNotIn(secret, serialized)

    def test_invalid_usage_conflicts_and_partial_line_are_visible(self):
        usage = {
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "output_tokens": 10,
            "total_tokens": 110,
        }
        result = self.audit(
            [
                record("token_usage_record", {"response_id": "r", "usage": usage}),
                record(
                    "token_usage_record",
                    {
                        "response_id": "r",
                        "usage": {**usage, "input_tokens": 110, "total_tokens": 120},
                    },
                ),
                record(
                    "token_usage_record",
                    {"response_id": "invalid", "usage": {**usage, "cached_input_tokens": 200}},
                ),
            ],
            suffix='bad-json\n{"partial":',
        )
        self.assertEqual(result["diagnostics"]["invalid_usage_records"], 1)
        self.assertEqual(result["diagnostics"]["conflicting_usage_records"], 1)
        self.assertEqual(result["diagnostics"]["invalid_records"], 1)
        self.assertEqual(result["diagnostics"]["incomplete_lines"], 1)
        self.assertEqual(result["request_usage"]["total_tokens"], 110)

    def test_cli_does_not_create_ledger_and_redacts_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "private.jsonl"
            transcript.write_text(json.dumps(record("session_meta", {})) + "\n")
            ledger = root / "must-not-exist"
            command = [sys.executable, str(PLUGIN / "scripts" / "run_budget.py"), "audit"]
            env = {**os.environ, "CODEX_RUN_BUDGET_HOME": str(ledger)}
            result = subprocess.run(
                [*command, str(transcript)], env=env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)["request_usage"])
            self.assertFalse(ledger.exists())
            result = subprocess.run(
                [*command, str(root / "sensitive-missing")], env=env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("sensitive-missing", result.stderr)
            self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
