from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class Usage:
    total: int = 0
    input: int = 0
    cached_input: int = 0
    output: int = 0
    reasoning_output: int = 0

    def delta(self, prior: Usage) -> Usage:
        return Usage(
            total=max(0, self.total - prior.total),
            input=max(0, self.input - prior.input),
            cached_input=max(0, self.cached_input - prior.cached_input),
            output=max(0, self.output - prior.output),
            reasoning_output=max(0, self.reasoning_output - prior.reasoning_output),
        )


def _as_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return 0


def _usage_from_line(record: Any) -> Usage | None:
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    totals = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(totals, dict):
        return None
    return Usage(
        total=_as_nonnegative_int(totals.get("total_tokens")),
        input=_as_nonnegative_int(totals.get("input_tokens")),
        cached_input=_as_nonnegative_int(totals.get("cached_input_tokens")),
        output=_as_nonnegative_int(totals.get("output_tokens")),
        reasoning_output=_as_nonnegative_int(totals.get("reasoning_output_tokens")),
    )


def latest_usage(transcript_path: str | None) -> Usage:
    if not transcript_path:
        return Usage()
    path = Path(transcript_path)
    try:
        stat = path.stat()
    except OSError:
        return Usage()
    if not path.is_file() or stat.st_size > MAX_TRANSCRIPT_BYTES:
        return Usage()

    latest = Usage()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "token_count" not in line:
                    continue
                try:
                    usage = _usage_from_line(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if usage is not None:
                    latest = usage
    except OSError:
        return Usage()
    return latest
