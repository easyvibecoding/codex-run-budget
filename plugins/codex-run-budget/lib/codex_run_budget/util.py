from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

COUNT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$")


def parse_count(value: str) -> int:
    match = COUNT_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid count: {value!r}")
    number = float(match.group(1))
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2).lower()]
    result = int(number * multiplier)
    if result <= 0:
        raise ValueError("count must be positive")
    return result


def parse_ratio(value: str) -> float:
    raw = value.strip()
    if raw.endswith("%"):
        result = float(raw[:-1]) / 100.0
    else:
        result = float(raw)
    if not 0.0 < result < 1.0:
        raise ValueError("ratio must be between 0 and 1")
    return result


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8", errors="replace")
    else:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def data_dir() -> Path:
    configured = os.environ.get("CODEX_RUN_BUDGET_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex" / "run-budget"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def safe_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
