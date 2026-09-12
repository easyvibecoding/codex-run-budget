from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
MAX_USAGE_SCAN_BYTES = 8 * 1024 * 1024


def request_usage(value: Any) -> dict[str, int] | None:
    """Validate native per-request usage, shared by offline and inline reports."""
    if not isinstance(value, dict):
        return None
    required_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    optional_keys = ("cache_write_input_tokens", "reasoning_output_tokens")
    if any(key not in value for key in required_keys):
        return None
    values: dict[str, int] = {}
    for key in required_keys + optional_keys:
        raw = value.get(key, 0)
        if type(raw) is not int or raw < 0:
            return None
        values[key] = raw
    if values["cached_input_tokens"] > values["input_tokens"]:
        return None
    if values["cache_write_input_tokens"] > values["input_tokens"]:
        return None
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return None
    if values["total_tokens"] != values["input_tokens"] + values["output_tokens"]:
        return None
    return values


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


@dataclass(frozen=True)
class Observation:
    usage: Usage | None
    state: str
    reason: str | None = None


def _usage_from_line(record: Any) -> Usage | None:
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    totals = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(totals, dict) or "total_tokens" not in totals:
        return None
    keys = (
        "total_tokens",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    values = {key: totals.get(key, 0) for key in keys}
    if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in values.values()):
        return None
    if values["cached_input_tokens"] > values["input_tokens"]:
        return None
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return None
    if ("input_tokens" in totals or "output_tokens" in totals) and (
        values["total_tokens"] != values["input_tokens"] + values["output_tokens"]
    ):
        return None
    return Usage(
        total=values["total_tokens"],
        input=values["input_tokens"],
        cached_input=values["cached_input_tokens"],
        output=values["output_tokens"],
        reasoning_output=values["reasoning_output_tokens"],
    )


def observe_usage(transcript_path: str | None) -> Observation:
    """Inspect a bounded tail, newest first; missing evidence never means zero usage."""
    if not transcript_path:
        return Observation(None, "unavailable", "missing_path")
    path = Path(transcript_path)
    try:
        stat = path.stat()
    except OSError:
        return Observation(None, "unavailable", "unreadable")
    if not path.is_file():
        return Observation(None, "unavailable", "not_regular_file")
    try:
        with path.open("rb") as handle:
            offset = max(0, stat.st_size - MAX_USAGE_SCAN_BYTES)
            handle.seek(offset)
            raw = handle.read(stat.st_size - offset)
            if len(raw) != stat.st_size - offset:
                return Observation(None, "unavailable", "snapshot_changed")
    except OSError:
        return Observation(None, "unavailable", "unreadable")
    lines = raw.split(b"\n")
    partial = lines.pop()
    if partial:
        try:
            json.loads(partial)
        except (ValueError, UnicodeError, RecursionError):
            pass  # A writer may not have finished the trailing record yet.
        else:
            lines.append(partial)
            partial = b""
    if offset:
        lines = lines[1:]  # The first record may start outside the bounded tail.
    completed = False
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            return Observation(None, "unavailable", "invalid_record")
        usage = _usage_from_line(record)
        if usage is not None:
            return Observation(usage, "ok")
        payload = record.get("payload") if isinstance(record, dict) else None
        if isinstance(payload, dict) and record.get("type") == "event_msg":
            if payload.get("type") == "token_count" and payload.get("info") is not None:
                return Observation(None, "unavailable", "invalid_usage")
            completed = completed or payload.get("type") == "task_complete"
    if offset:
        return Observation(None, "unavailable", "scan_limit")
    if partial or completed:
        return Observation(None, "unavailable", "missing_usage")
    return Observation(None, "pending")


def latest_usage(transcript_path: str | None) -> Usage | None:
    return observe_usage(transcript_path).usage
