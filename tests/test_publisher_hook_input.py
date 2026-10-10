"""Offline hook-input boundaries; synthetic only, no installed hooks or real stores."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publisher_hook_input_test", ROOT / "plugins/codex-run-budget/scripts/publisher_bootstrap.py")
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


def payload_bytes(size=256, event="PreToolUse"):
    payload = {"hook_event_name": event, "session_id": "synthetic-only", "payload": ""}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    payload["payload"] = "x" * (size - len(raw))
    raw = json.dumps(payload, separators=(",", ":")).encode()
    assert len(raw) == size
    return raw


class PublisherHookInputTest(unittest.TestCase):
    def invoke(self, raw, event="PreToolUse", *, publisher_error=None,
               seed_error=None, select_error=None, runtime_error=None, runtime_output="{}"):
        publisher = Mock()
        publisher.seed.side_effect = seed_error
        publisher.select.side_effect = select_error
        publisher.select.return_value = ({}, b"synthetic-runtime", False)
        output = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")

        def run(args):
            self.assertEqual(args, ["--event", event])
            self.assertEqual(sys.stdin.buffer.read(), raw)
            if runtime_error:
                raise runtime_error
            print(runtime_output)

        with patch.object(BOOT, "Publisher", side_effect=publisher_error,
                          return_value=publisher), patch.object(BOOT, "RuntimeLoader") as loader, \
                patch.object(BOOT, "data_root", return_value=Path("synthetic-store")), \
                patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", output):
            loader.return_value.run.side_effect = run
            code = BOOT.main(b"synthetic-source",
                             {"plugin": "codex-run-budget", "events": [event]}, [event])
        self.assertEqual(code, 0)
        return json.loads(output.getvalue()), publisher, loader

    def test_complete_large_input_is_accepted_without_transformation(self):
        for size in (2 * 1024 * 1024, 2 * 1024 * 1024 + 1, 5 * 1024 * 1024):
            with self.subTest(size=size):
                raw = payload_bytes(size)
                stream = Mock(wraps=io.BytesIO(raw))
                retained, payload = BOOT.read_hook_input(stream, "PreToolUse")
                stream.read.assert_called_once_with()
                self.assertEqual(retained, raw)
                self.assertEqual(payload["session_id"], "synthetic-only")

    def test_unicode_counts_bytes_and_preserves_complete_utf8(self):
        payload = {"hook_event_name": "PreToolUse", "session_id": "synthetic-only",
                   "payload": "字" * (1024 * 1024)}
        raw = json.dumps(payload, ensure_ascii=False).encode()
        retained, _ = BOOT.read_hook_input(io.BytesIO(raw), "PreToolUse")
        self.assertEqual(retained, raw)
        self.assertGreater(len(raw), 2 * 1024 * 1024)

    def test_invalid_json_utf8_and_duplicates_are_rejected(self):
        for raw in (b"{", bytes([255]), b'{"session_id":"a","session_id":"b"}'):
            with self.subTest(raw_bytes=len(raw)):
                with self.assertRaises(BOOT.HookInputError) as caught:
                    BOOT.read_hook_input(io.BytesIO(raw), "PreToolUse")
                self.assertEqual(caught.exception.code, "HOOK_INPUT_INVALID_JSON")

    def test_parser_recursion_failure_remains_rejected(self):
        with patch.object(BOOT, "parse", side_effect=RecursionError("synthetic-depth")):
            with self.assertRaises(BOOT.HookInputError) as caught:
                BOOT.read_hook_input(io.BytesIO(payload_bytes()), "PreToolUse")
        self.assertEqual(caught.exception.code, "HOOK_INPUT_INVALID_JSON")
        self.assertIn("RecursionError", BOOT.failure_message("hook-input", caught.exception))

    def test_metadata_and_identity_checks_remain_rejected(self):
        for payload, code in [
            ([], "HOOK_INPUT_INVALID_METADATA"),
            ({"hook_event_name": "other"}, "HOOK_INPUT_INVALID_METADATA"),
            ({"hook_event_name": "PreToolUse"}, "HOOK_INPUT_INVALID_SESSION"),
            ({"hook_event_name": "PreToolUse", "session_id": True}, "HOOK_INPUT_INVALID_SESSION"),
            ({"hook_event_name": "PreToolUse", "session_id": ""}, "HOOK_INPUT_INVALID_SESSION"),
            ({"hook_event_name": "PreToolUse", "session_id": "x" * 257},
             "HOOK_INPUT_INVALID_SESSION"),
        ]:
            with self.subTest(code=code), self.assertRaises(BOOT.HookInputError) as caught:
                BOOT.read_hook_input(io.BytesIO(json.dumps(payload).encode()), "PreToolUse")
            self.assertEqual(caught.exception.code, code)

    def test_invalid_large_input_denies_without_pin_selection_or_runtime(self):
        raw = payload_bytes(5 * 1024 * 1024)[:-1]
        result, publisher, loader = self.invoke(raw)
        decision = result["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("HOOK_INPUT_INVALID_JSON", decision["permissionDecisionReason"])
        self.assertIn(f"input_bytes={len(raw)}", result["systemMessage"])
        self.assertIn("hook-input; JSONDecodeError", result["systemMessage"])
        self.assertNotIn("runtime unavailable", result["systemMessage"])
        publisher.select.assert_not_called()
        loader.assert_not_called()
        publisher.close.assert_called_once()

    def test_valid_input_keeps_original_pin_and_runtime_dispatch(self):
        raw = payload_bytes(5 * 1024 * 1024)
        result, publisher, loader = self.invoke(raw)
        self.assertEqual(result, {})
        publisher.select.assert_called_once_with("synthetic-only")
        loader.assert_called_once_with(b"synthetic-runtime", "codex_run_budget")
        publisher.close.assert_called_once()

    def test_failure_phases_do_not_echo_exception_text(self):
        marker = "EXCEPTION_TEXT_MUST_STAY_PRIVATE"
        for kwargs, phase in [
            ({"publisher_error": OSError(marker)}, "publisher-initialize"),
            ({"seed_error": ValueError(marker)}, "publisher-seed"),
            ({"select_error": ValueError(marker)}, "runtime-select"),
            ({"runtime_error": RuntimeError(marker)}, "runtime-execute"),
            ({"runtime_output": marker}, "runtime-output"),
        ]:
            with self.subTest(phase=phase):
                result, _, _ = self.invoke(payload_bytes(), **kwargs)
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertIn(phase, result["systemMessage"])
                self.assertNotIn(marker, json.dumps(result))

    def test_prompt_lifecycle_and_reporting_failure_semantics_are_unchanged(self):
        error = BOOT.HookInputError("HOOK_INPUT_INVALID_JSON", 5 * 1024 * 1024)
        for event in ("UserPromptSubmit", "SessionStart", "PostToolUse"):
            result = BOOT.unavailable(event, True, phase="hook-input", error=error)
            if event == "UserPromptSubmit":
                self.assertEqual(result["decision"], "block")
            else:
                self.assertFalse(result["continue"])
        self.assertEqual(BOOT.unavailable("PreToolUse", False,
                                         phase="hook-input", error=error), {})

    def test_unknown_exception_class_or_phase_cannot_echo_custom_labels(self):
        error = type("EXCEPTION_TEXT_MUST_STAY_PRIVATE", (Exception,), {})()
        message = BOOT.failure_message("EXCEPTION_TEXT_MUST_STAY_PRIVATE", error)
        self.assertIn("[runtime; Exception]", message)
        self.assertNotIn("EXCEPTION_TEXT_MUST_STAY_PRIVATE", message)


if __name__ == "__main__":
    unittest.main()
