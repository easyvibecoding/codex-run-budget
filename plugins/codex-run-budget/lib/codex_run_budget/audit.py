"""Read-only transcript diagnostics; no policy decisions or ledger writes."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .transcript import MAX_TRANSCRIPT_BYTES, _usage_from_line
from .util import stable_hash


def _timestamp(record: dict[str, Any]) -> float | None:
    try:
        return datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def _usage(value: Any) -> dict[str, int] | None:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    if not isinstance(value, dict):
        return None
    if any(type(value.get(k)) is not int or value[k] < 0 for k in keys):
        return None
    if value["cached_input_tokens"] > value["input_tokens"]:
        return None
    if value["total_tokens"] != value["input_tokens"] + value["output_tokens"]:
        return None
    return {k: value[k] for k in keys}


def audit_transcript(path: Path) -> dict[str, Any]:
    """Analyze one bounded snapshot. Never combine parent/child accounting scopes.

    Request usage is deduplicated by response id, independently of cumulative
    token_count snapshots. Tool timings describe call/output spans, not CPU time.
    """
    size = path.stat().st_size
    if not path.is_file() or size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("audit requires a regular transcript no larger than 256 MiB")
    requests: dict[str, dict[str, int]] = {}
    calls: dict[str, tuple[str, float | None]] = {}
    completed: set[str] = set()
    fingerprints: dict[str, int] = {}
    tools: dict[str, Counter] = {}
    counters: Counter = Counter()
    latest = None
    first_time = last_time = None
    generation = 0
    with path.open("rb") as handle:
        remaining = size
        while remaining:
            line = handle.readline(remaining)
            if not line:
                break
            remaining -= len(line)
            counters["records"] += 1
            if not line.endswith(b"\n"):
                counters["incomplete_lines"] += 1
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                counters["invalid_records"] += 1
                continue
            if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                counters["invalid_records"] += 1
                continue
            payload = record["payload"]
            stamp = _timestamp(record)
            if stamp is not None:
                first_time = stamp if first_time is None else min(first_time, stamp)
                last_time = stamp if last_time is None else max(last_time, stamp)
            kind = payload.get("type", record.get("type"))
            if record.get("type") == "compacted":
                generation += 1
            if record.get("type") == "token_usage_record":
                usage = _usage(payload.get("usage"))
                response = payload.get("response_id")
                if usage is None or not isinstance(response, str) or not response:
                    counters["invalid_usage_records"] += 1
                else:
                    key = stable_hash(response)
                    if key in requests:
                        counters["duplicate_usage_records"] += 1
                        if requests[key] != usage:
                            counters["conflicting_usage_records"] += 1
                    else:
                        requests[key] = usage
            observed = _usage_from_line(record)
            if observed is not None:
                if latest is not None and observed.total < latest.total:
                    counters["cumulative_decreases"] += 1
                latest = observed
            if kind in ("task_started", "task_complete", "turn_aborted"):
                counters[kind] += 1
            if kind in ("function_call", "custom_tool_call"):
                call_id = payload.get("call_id")
                if not isinstance(call_id, str) or not call_id:
                    counters["unidentified_calls"] += 1
                    continue
                call_id = stable_hash(call_id)
                if call_id in calls:
                    counters["duplicate_call_records"] += 1
                    continue
                # Hash names too: arbitrary tool names can contain private data.
                name = payload.get("name")
                tool = stable_hash(name)
                stats = tools.setdefault(tool, Counter())
                stats["calls"] += 1
                arguments = payload.get("arguments", payload.get("input"))
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        pass
                fingerprint = stable_hash([name, arguments])
                if fingerprint in fingerprints:
                    stats["repeated_calls"] += 1
                    if fingerprints[fingerprint] < generation:
                        stats["repeated_after_compaction"] += 1
                fingerprints[fingerprint] = generation
                calls[call_id] = (tool, stamp)
            elif kind in ("function_call_output", "custom_tool_call_output"):
                key = stable_hash(payload.get("call_id"))
                if key in completed:
                    counters["duplicate_output_records"] += 1
                    continue
                completed.add(key)
                if key not in calls:
                    counters["unmatched_outputs"] += 1
                    continue
                tool, start = calls[key]
                stats = tools[tool]
                stats["completed_calls"] += 1
                output = payload.get("output", "")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False)
                byte_count = len(output.encode("utf-8", errors="replace"))
                stats["output_bytes"] += byte_count
                stats["largest_output_bytes"] = max(stats["largest_output_bytes"], byte_count)
                if start is not None and stamp is not None and stamp >= start:
                    stats["timed_calls"] += 1
                    stats["observed_span_ms"] += round((stamp - start) * 1000)
    totals = {
        k: sum(u[k] for u in requests.values())
        for k in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    }
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    fields = (
        "calls",
        "completed_calls",
        "timed_calls",
        "observed_span_ms",
        "output_bytes",
        "largest_output_bytes",
        "repeated_calls",
        "repeated_after_compaction",
    )
    return {
        "schema_version": 1,
        "source_hash": stable_hash(str(path.resolve())),
        "snapshot_bytes": size,
        "observed_elapsed_ms": round((last_time - first_time) * 1000)
        if last_time is not None and first_time is not None
        else None,
        "compactions": generation,
        "diagnostics": dict(counters),
        "request_usage": {"unique_responses": len(requests), **totals} if requests else None,
        "largest_request_tokens": max(u["total_tokens"] for u in requests.values())
        if requests
        else None,
        "latest_cumulative_tokens": latest.total if latest is not None else None,
        "request_minus_latest_cumulative_tokens": totals["total_tokens"] - latest.total
        if requests and latest is not None
        else None,
        "tools": [
            {"tool_hash": name, **{k: stats[k] for k in fields}}
            for name, stats in sorted(tools.items())
        ],
        "limitations": [
            "Single transcript only; parent and child totals must not be blindly added.",
            "Request usage and cumulative snapshots are separate, never summed together.",
            "Missing request records mean unknown coverage, not zero model usage.",
            "Cached input is included in input; reasoning output is included in output.",
            "Call/output spans can overlap and include waiting; they are not CPU time.",
            "Repeated calls need review; they do not prove waste or justify skipping checks.",
            "Nested exec calls are opaque; only recorded outer calls are counted.",
            "This report is not billing data and does not change enforcement.",
        ],
    }
