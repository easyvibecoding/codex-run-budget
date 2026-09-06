#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from codex_run_budget import Governor  # noqa: E402

MAX_INPUT_BYTES = 2 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--event",
        choices=(
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
        ),
    )
    event = parser.parse_args().event

    def reject(reason: str) -> int:
        message = "Run Budget rejected hook input: " + reason + ". Private input omitted."
        if event:
            print(json.dumps(Governor.failure_output(event, message)))
            return 0
        # Legacy direct invocations lack the event needed for structured output.
        print(message, file=sys.stderr)
        return 2

    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return reject("input exceeded 2 MiB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return reject("invalid JSON")
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("session_id"), str)
        or not payload.get("session_id")
    ):
        return reject("missing session identity")
    if event and payload.get("hook_event_name") != event:
        return reject("event mismatch")
    if not event:
        event = payload.get("hook_event_name")
        if not isinstance(event, str) or not event:
            return reject("missing event identity")

    result = Governor.dispatch(payload)
    if result is not None:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
