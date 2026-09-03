#!/usr/bin/env python3
from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"
REQUIRED_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "Stop",
    "SessionEnd",
    "Interrupt",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    if manifest["name"] != "codex-run-budget":
        fail("plugin name mismatch")
    if manifest["version"] != project["project"]["version"]:
        fail("plugin and project versions differ")
    entries = [item for item in marketplace["plugins"] if item["name"] == manifest["name"]]
    if len(entries) != 1:
        fail("marketplace must contain exactly one codex-run-budget entry")
    if entries[0]["source"]["path"] != "./plugins/codex-run-budget":
        fail("marketplace source path mismatch")
    if set(hooks["hooks"]) != REQUIRED_EVENTS:
        fail("hook event set is incomplete or unexpected")

    for event, groups in hooks["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                command = hook.get("command", "")
                if command != 'python3 "${PLUGIN_ROOT}/scripts/hook.py"':
                    fail(f"unexpected hook command for {event}: {command}")
                if hook.get("async"):
                    fail(f"governance hook cannot be asynchronous: {event}")

    skill = (PLUGIN / "skills" / "run-budget" / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\nname: run-budget\n"):
        fail("run-budget skill frontmatter is invalid")

    source_files = sorted((PLUGIN / "lib").rglob("*.py")) + sorted(
        (PLUGIN / "scripts").glob("*.py")
    )
    for source in source_files:
        text = source.read_text(encoding="utf-8")
        if "[TODO:" in text:
            fail(f"placeholder remains in {source.relative_to(ROOT)}")
        if "import requests" in text or "urllib.request" in text or "import socket" in text:
            fail(f"runtime network dependency found in {source.relative_to(ROOT)}")
        py_compile.compile(str(source), doraise=True)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_phrases = (
        "not a billing meter or a zero-overshoot guarantee",
        "Hosted tools",
        "does not intentionally record prompts",
        "Microsoft TokenOps",
    )
    for phrase in required_phrases:
        if phrase not in readme:
            fail(f"README is missing required disclosure: {phrase}")

    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
