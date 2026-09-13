"""Codex hook protocol adapter, shared by the source script and durable zipapp."""

from __future__ import annotations

import argparse
import json
import sys

from .governor import Governor

MAX_INPUT_BYTES = 2 * 1024 * 1024
EVENTS = (
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
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", choices=EVENTS)
    parser.add_argument("--preview", nargs=2, metavar=("SESSION", "TURN"))
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--output-dir")
    parser.add_argument("--data-dir")
    parser.add_argument("--codex-home")
    args = parser.parse_args()
    event = args.event
    if args.preview is not None:
        from pathlib import Path

        from .auto_preview import preview
        from .util import data_path

        if event or args.reconcile or not args.output_dir:
            parser.error("preview needs --output-dir and cannot run as a hook event")
        try:
            result = preview(
                Path(args.data_dir) if args.data_dir else data_path(),
                *args.preview, output_dir=Path(args.output_dir),
            )
        except Exception:
            result = {"status": "unavailable", "reason": "preview not generated; do not retry"}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.reconcile:
        # This child only reconciles reports. It must not dispatch a Governor
        # event, emit an admission decision, or resume model work on failure.
        try:
            from pathlib import Path

            from .reconcile import worker
            from .util import data_path

            if event:
                return 0
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                return 0
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return 0
            worker(payload, Path(args.data_dir) if args.data_dir else data_path(),
                   home=Path(args.codex_home) if args.codex_home else None)
        except Exception:
            pass
        return 0

    def reject(reason: str) -> int:
        message = "Run Budget rejected hook input: " + reason + ". Private input omitted."
        if event:
            print(json.dumps(Governor.failure_output(event, message)))
            return 0
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
    if event == "Stop":
        try:
            from .reconcile import schedule
            from .util import data_path

            schedule(payload, data_path())
        except Exception:
            pass
    if result is not None:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    return 0
