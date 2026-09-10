from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/codex-run-budget"


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "cache/old-version"
        (self.source / "runtime").mkdir(parents=True)
        shutil.copyfile(PLUGIN / "runtime/hook.pyz", self.source / "runtime/hook.pyz")
        self.data = self.root / "budget-data"
        self.env = {
            **os.environ,
            "PLUGIN_ROOT": str(self.source),
            "CODEX_RUN_BUDGET_HOME": str(self.data),
        }
        self.hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
        self.digest = hashlib.sha256((PLUGIN / "runtime/hook.pyz").read_bytes()).hexdigest()
        self.saved = self.data / "runtimes" / (self.digest + ".pyz")
        self.transcript = self.root / "private-transcript.jsonl"
        self.transcript.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 0,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "reasoning_output_tokens": 0,
                                "total_tokens": 0,
                            }
                        },
                    },
                }
            )
            + "\n"
        )

    def invoke(self, event, **extra):
        command = shlex.split(self.hooks[event][0]["hooks"][0]["command"])
        command[0] = sys.executable
        payload = {
            "session_id": "private-bootstrap-run",
            "hook_event_name": event,
            "transcript_path": str(self.transcript),
            "cwd": str(self.root),
            "turn_id": "turn-1",
            **extra,
        }
        result = subprocess.run(
            command,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=self.env,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def evict_cache(self):
        self.source.rename(self.root / "evicted-cache")

    def test_bootstrap_survives_cache_eviction_and_keeps_enforcement(self):
        self.invoke("UserPromptSubmit", prompt="run-budget:start tokens=100k tools=2")
        self.assertTrue(self.saved.is_file())
        self.assertEqual(hashlib.sha256(self.saved.read_bytes()).hexdigest(), self.digest)
        self.evict_cache()
        self.invoke(
            "PreToolUse", tool_name="Bash", tool_use_id="call-1", tool_input={"command": "pwd"}
        )
        self.invoke(
            "PostToolUse", tool_name="Bash", tool_use_id="call-1", tool_input={}, tool_response="ok"
        )
        self.invoke("UserPromptSubmit", prompt="run-budget:halt reason=validation")
        denied = self.invoke("PreToolUse", tool_name="Bash", tool_use_id="call-2", tool_input={})
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        stopped = self.invoke("Stop")
        self.assertNotEqual(stopped.get("decision"), "block")

    def test_missing_runtime_has_structured_denial_and_no_stop_retry(self):
        self.evict_cache()
        denied = self.invoke("PreToolUse", tool_input={"private": "do-not-echo"})
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("do-not-echo", json.dumps(denied))
        self.assertEqual(self.invoke("UserPromptSubmit", prompt="private")["decision"], "block")
        for event in ("Stop", "SubagentStop", "SessionEnd", "Interrupt"):
            stopped = self.invoke(event)
            self.assertNotEqual(stopped.get("decision"), "block")
            self.assertFalse(stopped["continue"])
        self.assertFalse((self.data / "ledger.sqlite3").exists())

    def test_corrupt_saved_runtime_recovers_only_from_the_pinned_source(self):
        self.invoke("SessionStart")
        self.saved.write_bytes(b"corrupted archive")
        self.invoke("SessionStart")
        self.assertEqual(hashlib.sha256(self.saved.read_bytes()).hexdigest(), self.digest)
        self.saved.write_bytes(b"corrupted archive")
        (self.source / "runtime/hook.pyz").write_bytes(b"different release")
        result = self.invoke("PreToolUse")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.saved.read_bytes(), b"corrupted archive")

    def test_saved_version_is_used_even_when_source_changes(self):
        self.invoke("SessionStart")
        (self.source / "runtime/hook.pyz").write_bytes(b"a newer release")
        result = self.invoke("UserPromptSubmit", prompt="run-budget:start tokens=100k")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertNotEqual(result.get("decision"), "block")
        self.assertEqual(hashlib.sha256(self.saved.read_bytes()).hexdigest(), self.digest)

    def test_runtime_directory_symlink_is_rejected(self):
        self.data.mkdir()
        elsewhere = self.root / "outside"
        elsewhere.mkdir()
        (self.data / "runtimes").symlink_to(elsewhere, target_is_directory=True)
        result = self.invoke("PreToolUse")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(list(elsewhere.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
