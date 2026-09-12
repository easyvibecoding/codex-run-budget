from __future__ import annotations

import itertools
import json
import stat
import sys
import tempfile
import textwrap
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"

sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.meter_source import (  # noqa: E402
    ERR_EOF,
    ERR_MALFORMED_OUTPUT,
    ERR_MISSING_RESPONSE,
    ERR_NOT_ATTEMPTED,
    ERR_PROCESS_EXIT,
    ERR_TIMEOUT,
    ERR_UNSUPPORTED_RPC,
    read_meter_sources,
)


class MeterSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def server(self, body: str) -> Path:
        path = self.root / "fake-codex"
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_normal_notifications_chunking_and_deduplication(self) -> None:
        fake = self.server(
            """
            import json, sys

            def emit(value, split=False):
                encoded = (json.dumps(value, separators=(",", ":")) + "\\n").encode()
                if split:
                    for offset in range(0, len(encoded), 3):
                        sys.stdout.buffer.write(encoded[offset:offset + 3])
                        sys.stdout.buffer.flush()
                else:
                    sys.stdout.buffer.write(encoded)
                    sys.stdout.buffer.flush()

            for line in sys.stdin.buffer:
                request = json.loads(line)
                method = request.get("method")
                request_id = request.get("id")
                if method == "initialize":
                    emit({"method": "server/notice", "params": {}})
                    emit({"id": request_id, "result": {"ok": True}}, split=True)
                elif method == "initialized":
                    pass
                elif method == "account/rateLimits/read":
                    emit({"method": "account/rateLimits/updated", "params": {"rateLimits": {}}})
                    emit({"id": request_id, "result": {
                        "accountId": "acct-private",
                        "rateLimits": {},
                        "rateLimitsByLimitId": {"codex": {}, "spark": {}},
                    }}, split=True)
                elif method == "account/usage/read":
                    emit({"id": request_id, "result": {
                        "summary": {}, "threadUsage": None,
                    }}, split=True)
            """
        )
        thread_id = str(uuid.uuid4())
        result = read_meter_sources(
            codex_binary=str(fake),
            thread_ids=[thread_id, thread_id.upper(), thread_id],
            timeout=2,
            codex_home=self.root / "codex-home",
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["rate_limits"]["rateLimitsByLimitId"].keys(), {"codex", "spark"})
        self.assertEqual(result["account_usage"]["summary"], {})
        self.assertEqual(len(result["thread_usage"]), 1)
        self.assertEqual(result["thread_usage"][0]["thread_id"], thread_id)
        self.assertIsNone(result["thread_usage"][0]["error"])
        self.assertIsInstance(result["started_at"], float)
        self.assertIsInstance(result["finished_at"], float)

    def test_partial_account_usage_rpc_failure_keeps_thread_success(self) -> None:
        fake = self.server(
            """
            import json, sys
            for line in sys.stdin.buffer:
                request = json.loads(line)
                method, request_id = request.get("method"), request.get("id")
                if method == "initialize":
                    print(json.dumps({"id": request_id, "result": {}}), flush=True)
                elif method == "account/rateLimits/read":
                    print(json.dumps({"id": request_id, "result": {"rateLimits": {}}}), flush=True)
                elif method == "account/usage/read":
                    if request.get("params", {}).get("threadId"):
                        print(json.dumps({"id": request_id, "result": {
                            "summary": {}, "threadUsage": None,
                        }}), flush=True)
                    else:
                        print(json.dumps({"id": request_id, "error": {
                            "code": -32000, "message": "do-not-return-this-secret",
                        }}), flush=True)
            """
        )
        thread_id = str(uuid.uuid4())
        result = read_meter_sources(codex_binary=str(fake), thread_ids=[thread_id], timeout=2)
        self.assertIsNone(result["account_usage"])
        self.assertEqual(result["thread_usage"][0]["error"], None)
        self.assertIsNotNone(result["thread_usage"][0]["response"])
        self.assertIn({"source": "account_usage", "code": "rpc_error"}, result["errors"])
        self.assertNotIn("do-not-return-this-secret", json.dumps(result))

    def test_unsupported_rpc_is_safe_and_does_not_expose_message(self) -> None:
        fake = self.server(
            """
            import json, sys
            for line in sys.stdin.buffer:
                request = json.loads(line)
                if request.get("method") == "initialize":
                    print(json.dumps({"id": request["id"], "result": {}}), flush=True)
                elif request.get("method") == "account/rateLimits/read":
                    print(json.dumps({"id": request["id"], "error": {
                        "code": -32601, "message": "secret unsupported endpoint",
                    }}), flush=True)
                elif request.get("method") == "account/usage/read":
                    print(json.dumps({"id": request["id"], "result": {
                        "summary": {}, "threadUsage": None,
                    }}), flush=True)
            """
        )
        result = read_meter_sources(codex_binary=str(fake), timeout=2)
        self.assertIn({"source": "rate_limits", "code": ERR_UNSUPPORTED_RPC}, result["errors"])
        self.assertNotIn("secret unsupported endpoint", json.dumps(result))

    def test_initialize_error_stops_all_account_calls(self) -> None:
        fake = self.server(
            """
            import json, sys
            for line in sys.stdin.buffer:
                request = json.loads(line)
                if request.get("method") == "initialize":
                    print(json.dumps({"id": request["id"], "error": {
                        "code": -32000, "message": "private handshake failure",
                    }}), flush=True)
                else:
                    raise SystemExit(2)
            """
        )
        result = read_meter_sources(
            codex_binary=str(fake), thread_ids=[str(uuid.uuid4())], timeout=1
        )
        self.assertIsNone(result["rate_limits"])
        self.assertIsNone(result["account_usage"])
        self.assertEqual(result["errors"], [{"source": "initialize", "code": "rpc_error"}])
        self.assertEqual(result["thread_usage"][0]["error"], ERR_NOT_ATTEMPTED)
        self.assertNotIn("private handshake failure", json.dumps(result))

    def test_timeout_and_eof_are_bounded_and_leave_rows(self) -> None:
        hanging = self.server(
            """
            import json, sys, time
            for line in sys.stdin.buffer:
                request = json.loads(line)
                if request.get("method") == "initialize":
                    print(json.dumps({"id": request["id"], "result": {}}), flush=True)
                elif request.get("method") == "account/rateLimits/read":
                    time.sleep(10)
            """
        )
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        started = time.monotonic()
        result = read_meter_sources(
            codex_binary=str(hanging), thread_ids=[first, second], timeout=1
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3)
        self.assertIn({"source": "rate_limits", "code": ERR_TIMEOUT}, result["errors"])
        self.assertEqual([row["error"] for row in result["thread_usage"]], [ERR_NOT_ATTEMPTED] * 2)

        eof = self.server(
            """
            import json, sys
            line = sys.stdin.buffer.readline()
            if line:
                request = json.loads(line)
                print(json.dumps({"id": request["id"], "result": {}}), flush=True)
            """
        )
        result = read_meter_sources(codex_binary=str(eof), timeout=1)
        codes = {entry["code"] for entry in result["errors"]}
        self.assertTrue(codes & {ERR_PROCESS_EXIT, ERR_EOF})

    def test_malformed_output_is_safe(self) -> None:
        fake = self.server(
            """
            import sys
            for line in sys.stdin.buffer:
                sys.stdout.write("not-json\\n")
                sys.stdout.flush()
                break
            """
        )
        result = read_meter_sources(codex_binary=str(fake), timeout=1)
        self.assertIn({"source": "initialize", "code": ERR_MALFORMED_OUTPUT}, result["errors"])

        unmatched = self.server(
            """
            import json, sys
            for line in sys.stdin.buffer:
                request = json.loads(line)
                print(json.dumps({"id": "different", "result": {}}), flush=True)
            """
        )
        result = read_meter_sources(codex_binary=str(unmatched), timeout=1)
        self.assertIn({"source": "initialize", "code": ERR_MISSING_RESPONSE}, result["errors"])

        recursive = self.server(
            """
            import sys
            for _line in sys.stdin.buffer:
                sys.stdout.buffer.write((b"[" * 10000) + (b"]" * 10000) + b"\\n")
                sys.stdout.buffer.flush()
                break
            """
        )
        result = read_meter_sources(codex_binary=str(recursive), timeout=1)
        self.assertIn({"source": "initialize", "code": ERR_MALFORMED_OUTPUT}, result["errors"])

    def test_invalid_thread_ids_raise_before_spawn(self) -> None:
        too_many = tuple(str(uuid.uuid4()) for _ in range(9))
        for values in (("bad",), too_many):
            with self.assertRaises(ValueError):
                read_meter_sources(thread_ids=values)
        with self.assertRaises(ValueError):
            read_meter_sources(thread_ids=itertools.repeat(str(uuid.uuid4())))


if __name__ == "__main__":
    unittest.main()
