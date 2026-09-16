#!/usr/bin/env python3
from __future__ import annotations

import json
import py_compile
import re
import sys
from pathlib import Path
from string import Formatter

from build_hook_runtime import MODULES, artifacts
from publisher_release import validate as validate_release

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


def validate_catalogs() -> None:
    """Build-time completeness checks; never repeated at a hook boundary."""
    directory = PLUGIN / "lib/codex_run_budget/assets/locales"
    locales = {"en", "zh-Hant", "zh-Hans", "ja", "ko", "de", "fr", "es", "pt"}
    domains = [directory, *(directory / domain for domain in ("reports", "cli", "observations"))]
    formatter = Formatter()
    for domain in domains:
        if {p.stem for p in domain.glob("*.json")} != locales:
            fail(f"incomplete language catalog: {domain.name}")
        base = json.loads((domain / "en.json").read_text(encoding="utf-8"))
        for locale in sorted(locales):
            values = json.loads((domain / (locale + ".json")).read_text(encoding="utf-8"))
            if not isinstance(values, dict) or values.keys() != base.keys():
                fail(f"language keys differ: {domain.name}/{locale}")
            for key, value in values.items():
                if not isinstance(value, str) or not value:
                    fail(f"invalid language value: {domain.name}/{locale}/{key}")
                def placeholders(text):
                    return sorted((name, spec, conversion or "")
                                  for _, name, spec, conversion in formatter.parse(text)
                                  if name is not None)
                if placeholders(value) != placeholders(base[key]):
                    fail(f"language placeholders differ: {domain.name}/{locale}/{key}")


def main() -> int:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(
        r'^\[project\]\s*$.*?^version\s*=\s*"([^"]+)"\s*$',
        project_text,
        re.MULTILINE | re.DOTALL,
    )
    package_text = (PLUGIN / "lib" / "codex_run_budget" / "__init__.py").read_text(encoding="utf-8")
    package_version = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', package_text, re.MULTILINE)

    if manifest["name"] != "codex-run-budget":
        fail("plugin name mismatch")
    if not project_version or manifest["version"] != project_version.group(1):
        fail("plugin and project versions differ")
    if not package_version or manifest["version"] != package_version.group(1):
        fail("plugin and package versions differ")
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
                if not command.startswith("python3 -I -c "):
                    fail(f"hook must start independently of the plugin cache: {event}")
                if hook.get("async"):
                    fail(f"governance hook cannot be asynchronous: {event}")

    for path, expected in artifacts(PLUGIN).items():
        if not path.is_file() or path.read_bytes() != expected:
            fail("hook runtime artifacts are stale; run scripts/build_hook_runtime.py")

    skill = (PLUGIN / "skills" / "run-budget" / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\nname: run-budget\n"):
        fail("run-budget skill frontmatter is invalid")

    source_files = sorted((PLUGIN / "lib").rglob("*.py")) + sorted(
        (PLUGIN / "scripts").glob("*.py")
    )
    sentinel = PLUGIN / "lib/codex_run_budget/update_notice.py"
    if "update_notice.py" in MODULES or "update_cli.py" in MODULES:
        fail("update checker must remain outside the governance hook runtime")
    for source in source_files:
        text = source.read_text(encoding="utf-8")
        if "[TODO:" in text:
            fail(f"placeholder remains in {source.relative_to(ROOT)}")
        # Only the independently trusted sentinel may fetch a public version manifest.
        if ("import requests" in text or "import socket" in text
                or ("urllib.request" in text and source not in {
                    sentinel, PLUGIN / "scripts/publisher_bootstrap.py"})):
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

    validate_release(PLUGIN)
    validate_catalogs()
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
