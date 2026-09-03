#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "lib"))

from codex_run_budget import Governor  # noqa: E402

MAX_INPUT_BYTES = 2 * 1024 * 1024


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print(json.dumps({"systemMessage": "Run Budget hook input exceeded 2 MiB."}))
        return 0
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(json.dumps({"systemMessage": "Run Budget received invalid hook JSON."}))
        return 0
    if not isinstance(payload, dict):
        return 0

    governor = Governor()
    try:
        result = governor.handle(payload)
    finally:
        governor.close()
    if result is not None:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
