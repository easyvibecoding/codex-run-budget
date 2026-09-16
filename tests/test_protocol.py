from __future__ import annotations

import base64
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"


class ProtocolTest(unittest.TestCase):
    def test_hook_runner_emits_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            transcript = Path(temporary) / "transcript.jsonl"
            transcript.write_text('{"type":"session_meta","payload":{}}\n')
            payload = {
                "session_id": "protocol-run",
                "transcript_path": str(transcript),
                "cwd": temporary,
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "turn-1",
                "prompt": "run-budget:start tokens=10k",
            }
            completed = subprocess.run(
                [sys.executable, str(PLUGIN / "scripts" / "hook.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                env={"CODEX_RUN_BUDGET_HOME": temporary},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_governance_hooks_use_plugin_root_and_no_network(self) -> None:
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands: list[str] = []
        for event, groups in hooks["hooks"].items():
            for group_index, group in enumerate(groups):
                for index, hook in enumerate(group["hooks"]):
                    # Only the separately trusted update sentinel reads public versions.
                    if (event, group_index, index) == ("UserPromptSubmit", 0, 1):
                        continue
                    commands.append(hook["command"])
        self.assertTrue(commands)
        source = (PLUGIN / "scripts/publisher_bootstrap.py").read_bytes()
        encoded = base64.b64encode(source).decode()
        self.assertTrue(all(encoded in shlex.split(command)[3] for command in commands))
        # Downloads run only in a separate bounded worker; the policy module stays offline.
        governor = (PLUGIN / "lib/codex_run_budget/governor.py").read_text()
        self.assertNotIn("urllib", governor)
        self.assertIn('if event == "UserPromptSubmit"', source.decode())
        self.assertTrue(all(command.startswith("python3 -I -c ") for command in commands))
        self.assertTrue(all("http" not in command for command in commands))


if __name__ == "__main__":
    unittest.main()
