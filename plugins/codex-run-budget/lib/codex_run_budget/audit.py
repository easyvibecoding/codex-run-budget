"""Read-only, privacy-preserving transcript diagnostics.

The audit deliberately has no dependency on the governance ledger.  It reads
bounded snapshots of JSONL transcripts and keeps only hashes and small numeric
summaries in memory.  ``audit_transcript`` is the backwards-compatible
single-file entry point; ``audit_transcripts`` is the page-aware entry point
used by discovery and reporting tools.
"""

from __future__ import annotations

import json
import math
import os
import stat as stat_module
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .lifecycle import aggregate_lifecycle
from .transcript import MAX_TRANSCRIPT_BYTES, _usage_from_line
from .util import stable_hash

# A caller can inspect many transcript pages, but the captured snapshots are
# still bounded.  This is a cap on stat() snapshots, not on the number of
# records retained (records are never retained verbatim).
MAX_AUDIT_BYTES = 4 * 1024 * 1024 * 1024
MAX_AUDIT_LINE_BYTES = 8 * 1024 * 1024
MAX_AUDIT_RECORDS = 500_000

KNOWN_MODELS = frozenset(
    {
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex-spark",
    }
)

_DIAGNOSTIC_KEYS = (
    "records",
    "invalid_records",
    "incomplete_lines",
    "unterminated_records",
    "oversized_lines",
    "invalid_usage_records",
    "duplicate_usage_records",
    "conflicting_usage_records",
    "conflicting_response_attribution",
    "invalid_cumulative_records",
    "cumulative_decreases",
    "cumulative_multiple_sources",
    "duplicate_call_records",
    "conflicting_call_records",
    "duplicate_output_records",
    "conflicting_output_records",
    "unmatched_outputs",
    "unidentified_calls",
    "unidentified_outputs",
    "call_id_collisions",
    "missing_thread_metadata",
    "ambiguous_thread_metadata",
    "missing_model_context",
    "missing_model_attribution",
    "conflicting_model_attribution",
    "missing_timing_records",
    "invalid_item_timing",
    "duplicate_item_timing",
    "conflicting_item_timing",
    "invalid_wait_arguments",
    "invalid_wait_results",
    "short_timeouts",
    "unchanged_result_repeats",
    "changed_result_repeats",
    "unknown_result_repeats",
    "snapshot_changed",
    "snapshot_cap",
    "oversized_files",
    "unreadable_files",
    "not_regular_files",
    "record_limit_skips",
    "resource_limited",
)


def _timestamp_value(value: Any) -> float | None:
    """Parse an ISO/numeric timestamp without retaining its source text."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
        except (OverflowError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def _timestamp(record: dict[str, Any]) -> float | None:
    """Return a top-level ISO timestamp without exposing the source value."""

    return _timestamp_value(record.get("timestamp"))


def _identifier_hash(value: Any) -> str | None:
    """Hash a non-empty identifier; never make ``hash(None)`` an identity."""

    if isinstance(value, str) and value:
        return stable_hash(value)
    return None


def _payload_identifier(payload: dict[str, Any], key: str) -> tuple[str | None, bool]:
    """Return a hashed payload identifier and whether the field was present.

    A missing identifier may safely inherit the active page context.  A
    present-but-invalid identifier must not silently inherit that context: doing
    so would attribute an item to the wrong thread or turn.
    """

    if key not in payload or payload.get(key) in (None, ""):
        return None, False
    return _identifier_hash(payload.get(key)), True


def _event_context(
    payload: dict[str, Any], page: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Resolve explicit event IDs before falling back to preceding metadata."""

    explicit_thread, has_thread = _payload_identifier(payload, "thread_id")
    thread_hash = explicit_thread if has_thread else page.get("active_thread_hash")
    explicit_turn, has_turn = _payload_identifier(payload, "turn_id")
    if has_turn:
        turn_hash = explicit_turn
    elif thread_hash == page.get("active_thread_hash"):
        # Native response_item records omit IDs and inherit the preceding
        # turn_context.  Do not carry a turn across an explicit thread change.
        turn_hash = page.get("active_turn_hash")
    else:
        turn_hash = None
    return thread_hash, turn_hash


def _lifecycle_context(
    payload: dict[str, Any], page: dict[str, Any]
) -> tuple[str | None, str | None, bool, bool]:
    """Resolve lifecycle IDs while preserving explicit-invalid boundaries.

    The older request/call parser treats ``null`` and an empty identifier as a
    missing field for backwards compatibility.  Native lifecycle records need
    a stricter boundary: a present-but-invalid ID must never silently inherit
    the preceding context and become a different turn.
    """

    active_thread = page.get("active_thread_hash")
    active_turn = page.get("active_turn_hash")

    thread_present = "thread_id" in payload
    thread_raw = payload.get("thread_id")
    thread_invalid = thread_present and not (isinstance(thread_raw, str) and thread_raw)
    thread_hash = stable_hash(thread_raw) if not thread_invalid and thread_present else None
    if not thread_present:
        thread_hash = active_thread

    turn_present = "turn_id" in payload
    turn_raw = payload.get("turn_id")
    turn_invalid = turn_present and not (isinstance(turn_raw, str) and turn_raw)
    turn_hash = stable_hash(turn_raw) if not turn_invalid and turn_present else None
    if not turn_present:
        # An explicit thread can inherit a turn only when it is the currently
        # active thread.  An invalid explicit thread never reaches this path.
        if thread_hash is not None and thread_hash == active_thread:
            turn_hash = active_turn
        else:
            turn_hash = None
    return thread_hash, turn_hash, thread_invalid, turn_invalid


def _new_lifecycle_event(
    state: dict[str, Any],
    page: dict[str, Any],
    payload: dict[str, Any],
    kind: str,
    stamp: float | None,
    in_scope: bool,
    sequence: int,
) -> dict[str, Any]:
    """Create a bounded lifecycle event without retaining native payloads."""

    thread_hash, turn_hash, thread_invalid, turn_invalid = _lifecycle_context(payload, page)
    duration_present = "duration_ms" in payload
    duration = _number_ms(payload.get("duration_ms")) if duration_present else None
    ttf_present = "time_to_first_token_ms" in payload
    time_to_first_token_ms = (
        _number_ms(payload.get("time_to_first_token_ms")) if ttf_present else None
    )
    window_present = "window_id" in payload
    window_raw = payload.get("window_id")
    window_invalid = window_present and not (isinstance(window_raw, str) and window_raw)
    window_hash = stable_hash(window_raw) if window_present and not window_invalid else None
    model = _model_label(payload.get("model")) if "model" in payload else None
    event_hash = stable_hash(
        [kind, thread_hash, turn_hash, stamp, duration, time_to_first_token_ms, window_hash]
    )
    return {
        "kind": kind,
        "stamp": stamp,
        "in_scope": in_scope,
        "before_window": (
            state["since"] is not None and stamp is not None and stamp < state["since"]
        ),
        "sequence": sequence,
        "source_hash": page["source_hash"],
        "event_hash": event_hash,
        "thread_hash": thread_hash,
        "turn_hash": turn_hash,
        "thread_invalid": thread_invalid,
        "turn_invalid": turn_invalid,
        "context_bound": thread_hash is not None,
        "model": model,
        "duration_ms": duration,
        "duration_invalid": duration_present and duration is None,
        "time_to_first_token_ms": time_to_first_token_ms,
        "time_to_first_token_invalid": ttf_present and time_to_first_token_ms is None,
        "window_hash": window_hash,
        "window_invalid": window_invalid,
    }


def _model_label(value: Any) -> str:
    """Keep the fixed model vocabulary readable and hash custom names."""

    if not isinstance(value, str) or not value:
        return "unknown"
    if value in KNOWN_MODELS:
        return value
    return f"hash:{stable_hash(value)}"


def _usage(value: Any) -> dict[str, int] | None:
    """Validate one request-level usage object.

    ``cache_write_input_tokens`` and ``reasoning_output_tokens`` were added by
    the v2 transcript format.  Missing optional fields are zero so v1 reports
    retain their old totals and keys.
    """

    if not isinstance(value, dict):
        return None
    required_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    optional_keys = ("cache_write_input_tokens", "reasoning_output_tokens")
    if any(key not in value for key in required_keys):
        return None
    keys = required_keys + optional_keys
    values: dict[str, int] = {}
    for key in keys:
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


def _in_scope(stamp: float | None, since: float | None, until: float | None) -> bool:
    if since is None and until is None:
        return True
    if stamp is None:
        return False
    if since is not None and stamp < since:
        return False
    if until is not None and stamp > until:
        return False
    return True


def _safe_json_hash(value: Any) -> str:
    """Hash arguments without retaining or serialising them in the report."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, UnicodeError, RecursionError):
            pass
    try:
        return stable_hash(value)
    except (TypeError, ValueError, RecursionError):
        return stable_hash(repr(type(value)))


def _tool_hashes(namespace: Any, name: Any) -> tuple[str, str, str]:
    namespace_hash = _identifier_hash(namespace) or "unknown"
    name_hash = _identifier_hash(name) or "unknown"
    # The namespace is deliberately part of the key.  A name alone is not a
    # sufficient identity for tools exposed by different namespaces.
    tool_hash = stable_hash([namespace_hash, name_hash])
    return tool_hash, namespace_hash, name_hash


def _number_ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _wait_timeout(arguments: Any) -> tuple[float | None, bool]:
    """Extract a numeric ``timeout_ms`` while treating malformed args safely."""

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, UnicodeError, RecursionError):
            return None, False
    if not isinstance(arguments, dict) or "timeout_ms" not in arguments:
        return None, False
    value = _number_ms(arguments.get("timeout_ms"))
    return value, value is not None


def _output_hash(output: Any) -> tuple[str | None, int]:
    if output is None:
        return None, 0
    if isinstance(output, str):
        text = output
    else:
        try:
            text = json.dumps(
                output, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError, RecursionError):
            text = repr(type(output))
    return stable_hash(text), len(text.encode("utf-8", errors="replace"))


def _parse_wait_result(output: Any) -> str:
    """Classify only an explicit JSON ``timed_out`` boolean.

    A false value means an event return, not necessarily that every target
    agent completed.  Missing or malformed result evidence remains unknown.
    """

    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (ValueError, UnicodeError, RecursionError):
            return "unknown"
    if not isinstance(output, dict) or type(output.get("timed_out")) is not bool:
        return "unknown"
    return "timeout" if output["timed_out"] else "event_return"


def _is_wait_candidate(namespace: Any, name: Any) -> bool:
    """Recognize only the collaboration wait boundary we can interpret."""

    return name == "wait_agent" and namespace in (None, "collaboration")


def _percentile(values: list[float], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower])
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _thread_ref(thread_hash: str | None, page_index: int) -> str:
    return f"id:{thread_hash}" if thread_hash else f"page:{page_index}"


def _public_thread_hash(ref: str) -> str:
    return ref[3:] if ref.startswith("id:") else "unknown"


def _role_for(parent_hash: str | None, known: bool = True) -> str:
    if not known:
        return "unknown"
    return "subagent" if parent_hash else "parent"


def _new_page(source_hash: str, snapshot_bytes: int | None) -> dict[str, Any]:
    return {
        "source_hash": source_hash,
        "snapshot_bytes": snapshot_bytes,
        "diagnostics": Counter(),
        "metadata": [],
        "contexts": [],
        "events": [],
        "metadata_ids": set(),
        "default_ref": None,
        "page_index": None,
        "generation": 0,
        "active_thread_hash": None,
        "active_turn_hash": None,
    }


def _new_state(since: float | None, until: float | None) -> dict[str, Any]:
    return {
        "since": since,
        "until": until,
        "pages": [],
        "calls": [],
        "outputs": [],
        "timestamps": [],
        "counters": Counter(),
        "records_seen": 0,
        "compactions": 0,
    }


def _diag(state: dict[str, Any], page: dict[str, Any], key: str, amount: int = 1) -> None:
    page["diagnostics"][key] += amount
    state["counters"][key] += amount


def _snapshot_diag(state: dict[str, Any], page: dict[str, Any]) -> None:
    """Report one snapshot change per page even when several checks observe it."""

    if not page["diagnostics"]["snapshot_changed"]:
        _diag(state, page, "snapshot_changed")


def _parse_line(state: dict[str, Any], page: dict[str, Any], record: Any, sequence: int) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
        _diag(state, page, "invalid_records")
        return
    payload = record["payload"]
    stamp = _timestamp(record)
    in_scope = _in_scope(stamp, state["since"], state["until"])
    if stamp is not None and in_scope:
        state["timestamps"].append((stamp, sequence))
    record_type = record.get("type")
    payload_type = payload.get("type")
    kind = payload_type or record_type

    # Metadata and turn contexts are always scanned, even when their event
    # timestamp is outside a requested time range.
    if record_type == "session_meta":
        # A malformed metadata record is still a boundary.  Never let a later
        # item inherit the previous thread after an explicit boundary that we
        # could not identify.
        page["active_thread_hash"] = None
        page["active_turn_hash"] = None
        thread_hash = _identifier_hash(payload.get("id"))
        if thread_hash is None:
            _diag(state, page, "missing_thread_metadata")
        else:
            parent_value = payload.get("parent_thread_id")
            source = payload.get("source")
            if isinstance(source, dict):
                subagent = source.get("subagent")
                spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
                if isinstance(spawn, dict) and parent_value is None:
                    parent_value = spawn.get("parent_thread_id")
            parent_hash = _identifier_hash(parent_value)
            page["metadata_ids"].add(thread_hash)
            # Native pages can contain more than one sequential session_meta
            # (for example after a fork).  Subsequent response_item records
            # inherit this active session until the next metadata boundary.
            page["active_thread_hash"] = thread_hash
            page["active_turn_hash"] = None
            started_at = _timestamp_value(payload.get("timestamp"))
            page["metadata"].append(
                {
                    "thread_hash": thread_hash,
                    "parent_hash": parent_hash,
                    "stamp": started_at if started_at is not None else stamp,
                }
            )
        return
    if record_type == "turn_context" or (
        record_type == "event_msg" and payload_type == "turn_context"
    ):
        explicit_thread, has_thread = _payload_identifier(payload, "thread_id")
        thread_hash = explicit_thread if has_thread else page.get("active_thread_hash")
        turn_hash = _identifier_hash(payload.get("turn_id"))
        if turn_hash is None:
            _diag(state, page, "missing_model_context")
        model = _model_label(payload.get("model"))
        if model == "unknown":
            _diag(state, page, "missing_model_context")
        # Every turn_context starts a new active turn, including malformed
        # contexts.  Otherwise a missing turn_id could inherit an old model.
        page["active_turn_hash"] = turn_hash
        page["active_thread_hash"] = thread_hash
        page["contexts"].append(
            {
                "thread_hash": thread_hash,
                "turn_hash": turn_hash,
                "context_bound": thread_hash is not None,
                "model": model,
                "stamp": stamp,
            }
        )
        return

    if record_type == "compacted":
        page["events"].append(
            _new_lifecycle_event(state, page, payload, "compacted", stamp, in_scope, sequence)
        )
        if in_scope:
            state["compactions"] += 1
            page["generation"] = page.get("generation", 0) + 1
        return

    if record_type == "token_usage_record":
        usage = _usage(payload.get("usage"))
        response_hash = _identifier_hash(payload.get("response_id"))
        if usage is None or response_hash is None:
            if in_scope:
                _diag(state, page, "invalid_usage_records")
            return
        thread_hash, turn_hash = _event_context(payload, page)
        page["events"].append(
            {
                "kind": "request",
                "stamp": stamp,
                "in_scope": in_scope,
                "sequence": sequence,
                "response_hash": response_hash,
                "usage": usage,
                "thread_hash": thread_hash,
                "turn_hash": turn_hash,
                "context_bound": thread_hash is not None,
            }
        )
        return

    if record_type == "event_msg" and payload_type == "token_count":
        observed = _usage_from_line(record)
        if observed is None:
            if in_scope:
                _diag(state, page, "invalid_cumulative_records")
        else:
            thread_hash, _turn_hash = _event_context(payload, page)
            page["events"].append(
                {
                    "kind": "cumulative",
                    "stamp": stamp,
                    "in_scope": in_scope,
                    "sequence": sequence,
                    "total": observed.total,
                    "thread_hash": thread_hash,
                    "context_bound": thread_hash is not None,
                }
            )
        return

    if record_type == "event_msg" and kind in ("task_started", "task_complete", "turn_aborted"):
        page["events"].append(
            _new_lifecycle_event(state, page, payload, kind, stamp, in_scope, sequence)
        )

    if kind in ("task_started", "task_complete", "turn_aborted"):
        if in_scope:
            state["counters"][kind] += 1
        return

    if record_type == "response_item" and kind in ("function_call", "custom_tool_call"):
        call_hash = _identifier_hash(payload.get("call_id"))
        if call_hash is None:
            if in_scope:
                _diag(state, page, "unidentified_calls")
            return
        tool_hash, namespace_hash, name_hash = _tool_hashes(
            payload.get("namespace"), payload.get("name")
        )
        arguments = payload.get("arguments", payload.get("input"))
        timeout_ms, timeout_valid = _wait_timeout(arguments)
        thread_hash, turn_hash = _event_context(payload, page)
        page["events"].append(
            {
                "kind": "call",
                "stamp": stamp,
                "in_scope": in_scope,
                "sequence": sequence,
                "call_hash": call_hash,
                "thread_hash": thread_hash,
                "turn_hash": turn_hash,
                "context_bound": thread_hash is not None,
                "tool_hash": tool_hash,
                "namespace_hash": namespace_hash,
                "name_hash": name_hash,
                "arguments_hash": _safe_json_hash(arguments),
                "generation": page.get("generation", 0),
                "wait_candidate": _is_wait_candidate(
                    payload.get("namespace"), payload.get("name")
                ),
                "timeout_ms": timeout_ms,
                "timeout_valid": timeout_valid,
            }
        )
        return

    if record_type == "response_item" and kind in (
        "function_call_output",
        "custom_tool_call_output",
    ):
        call_hash = _identifier_hash(payload.get("call_id"))
        if call_hash is None:
            if in_scope:
                _diag(state, page, "unidentified_outputs")
            return
        output_hash, output_bytes = _output_hash(payload.get("output"))
        thread_hash, _turn_hash = _event_context(payload, page)
        page["events"].append(
            {
                "kind": "output",
                "stamp": stamp,
                "in_scope": in_scope,
                "sequence": sequence,
                "call_hash": call_hash,
                "thread_hash": thread_hash,
                "context_bound": thread_hash is not None,
                "output_hash": output_hash,
                "output_bytes": output_bytes,
                # Wait classification is computed while the raw output is in
                # scope and only the bounded enum is retained.
                "wait_class": _parse_wait_result(payload.get("output")),
            }
        )
        return

    if record_type == "event_msg" and payload_type == "item_completed":
        item = payload.get("item")
        item_id = item.get("id") if isinstance(item, dict) else None
        item_hash = _identifier_hash(item_id)
        if item_hash is None:
            if in_scope:
                _diag(state, page, "invalid_item_timing")
            return
        started = _number_ms(payload.get("started_at_ms"))
        completed = _number_ms(payload.get("completed_at_ms"))
        if started is None or completed is None or completed < started:
            if in_scope:
                _diag(state, page, "invalid_item_timing")
            return
        thread_hash, _turn_hash = _event_context(payload, page)
        page["events"].append(
            {
                "kind": "timing",
                "stamp": stamp,
                "in_scope": in_scope,
                "sequence": sequence,
                "item_hash": item_hash,
                "thread_hash": thread_hash,
                "context_bound": thread_hash is not None,
                "start_ms": started,
                "end_ms": completed,
            }
        )


def _parse_file(
    state: dict[str, Any],
    page: dict[str, Any],
    path: Path,
    snapshot_bytes: int,
    handle: Any,
    opened_stat: os.stat_result,
    *,
    raise_errors: bool = False,
) -> None:
    sequence = 0
    remaining = snapshot_bytes
    try:
        while remaining:
            if state["records_seen"] >= MAX_AUDIT_RECORDS:
                _diag(state, page, "record_limit_skips")
                _diag(state, page, "resource_limited")
                break
            # Reading at most 8 MiB + 1 lets us discard pathological lines
            # without ever retaining a larger record.
            line = handle.readline(min(remaining, MAX_AUDIT_LINE_BYTES + 1))
            if not line:
                _snapshot_diag(state, page)
                break
            remaining -= len(line)
            page["diagnostics"]["records"] += 1
            state["counters"]["records"] += 1
            state["records_seen"] += 1
            if len(line) > MAX_AUDIT_LINE_BYTES:
                _diag(state, page, "oversized_lines")
                _diag(state, page, "resource_limited")
                if not line.endswith(b"\n"):
                    # Consume the remainder of this one line in bounded
                    # chunks, stopping at its newline or snapshot end.
                    while remaining:
                        chunk = handle.readline(min(remaining, MAX_AUDIT_LINE_BYTES + 1))
                        if not chunk:
                            _snapshot_diag(state, page)
                            remaining = 0
                            break
                        remaining -= len(chunk)
                        if chunk.endswith(b"\n"):
                            break
                continue
            has_newline = line.endswith(b"\n")
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError, RecursionError):
                if has_newline:
                    _diag(state, page, "invalid_records")
                else:
                    _diag(state, page, "incomplete_lines")
                continue
            if not has_newline:
                page["diagnostics"]["unterminated_records"] += 1
                state["counters"]["unterminated_records"] += 1
            _parse_line(state, page, record, sequence)
            sequence += 1
    except (OSError, ValueError, UnicodeError):
        _snapshot_diag(state, page)
        if raise_errors:
            raise ValueError("unable to read transcript snapshot") from None
    finally:
        try:
            current_fd_stat = os.fstat(handle.fileno())
        except (OSError, ValueError):
            current_fd_stat = opened_stat
        try:
            handle.close()
        except OSError:
            pass
    if (
        current_fd_stat.st_size != snapshot_bytes
        or current_fd_stat.st_dev != opened_stat.st_dev
        or current_fd_stat.st_ino != opened_stat.st_ino
    ):
        _snapshot_diag(state, page)
    try:
        current_stat = os.stat(path, follow_symlinks=False)
    except OSError:
        current_stat = opened_stat
    if (
        current_stat.st_size != snapshot_bytes
        or current_stat.st_dev != opened_stat.st_dev
        or current_stat.st_ino != opened_stat.st_ino
    ):
        _snapshot_diag(state, page)


def _resolve_page_refs(state: dict[str, Any]) -> None:
    for page in state["pages"]:
        ids = page["metadata_ids"]
        if len(ids) == 1:
            page["default_ref"] = _thread_ref(next(iter(ids)), page["page_index"])


def _canonicalize_pages(state: dict[str, Any]) -> None:
    """Make aggregate output independent of caller path order.

    Pages are independent snapshots.  Their caller-provided order must not
    decide deduplication winners, fallback page identities, or list ordering.
    Sorting by the privacy-safe source hash preserves deterministic output while
    keeping path names out of the report.
    """

    state["pages"].sort(
        key=lambda page: (
            page.get("source_hash", ""),
            page.get("snapshot_bytes") is None,
            page.get("snapshot_bytes") or 0,
        )
    )
    for index, page in enumerate(state["pages"]):
        page["page_index"] = index


def _event_ref(
    page: dict[str, Any], thread_hash: str | None, context_bound: bool | None = None
) -> str:
    if thread_hash:
        return _thread_ref(thread_hash, page["page_index"])
    # ``context_bound`` is recorded while parsing.  A page-level default is
    # valid only when the item was actually after that page's metadata; it
    # must not retroactively bind items before a metadata boundary.
    if context_bound is False:
        return f"page:{page['page_index']}"
    return page["default_ref"] or f"page:{page['page_index']}"


def _resolve_contexts(state: dict[str, Any]) -> dict[tuple[str, str], str]:
    values: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for page in state["pages"]:
        for context in page["contexts"]:
            ref = _event_ref(page, context["thread_hash"], context.get("context_bound"))
            turn_hash = context["turn_hash"]
            if turn_hash is None:
                continue
            values[(ref, turn_hash)].add(context["model"])
    result: dict[tuple[str, str], str] = {}
    for key, models in values.items():
        explicit = {model for model in models if model != "unknown"}
        if len(explicit) > 1:
            state["counters"]["conflicting_model_attribution"] += 1
            result[key] = "unknown"
        elif explicit:
            result[key] = next(iter(explicit))
        else:
            result[key] = "unknown"
    return result


def _thread_metadata(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for page in state["pages"]:
        for item in page["metadata"]:
            ref = _thread_ref(item["thread_hash"], page["page_index"])
            row = metadata.setdefault(
                ref,
                {"parents": set(), "pages": set(), "started_at": None, "known": True},
            )
            row["known"] = True
            row["pages"].add(page["page_index"])
            parent_hash = item["parent_hash"]
            if parent_hash:
                row["parents"].add(parent_hash)
            stamp = item.get("stamp")
            if stamp is not None:
                row["started_at"] = (
                    stamp if row["started_at"] is None else min(row["started_at"], stamp)
                )
    # A page can have explicit event IDs without a session_meta record.  Those
    # IDs are still safe to expose as hashed, unknown-role thread rows.
    for page in state["pages"]:
        for event in page["events"]:
            thread_hash = event.get("thread_hash")
            if thread_hash:
                ref = _thread_ref(thread_hash, page["page_index"])
                row = metadata.setdefault(
                    ref,
                    {"parents": set(), "pages": set(), "started_at": None, "known": False},
                )
                row["pages"].add(page["page_index"])
    return metadata


def _event_sort_key(event: dict[str, Any], page: dict[str, Any]) -> tuple[Any, ...]:
    """Stable chronology/tie-break key that never includes raw transcript data."""

    stamp = event.get("stamp")
    return (
        stamp is None,
        stamp if stamp is not None else 0,
        _event_ref(page, event.get("thread_hash"), event.get("context_bound")),
        page.get("source_hash", ""),
        event.get("sequence", 0),
    )


def _request_sort_key(event: dict[str, Any], page: dict[str, Any]) -> tuple[Any, ...]:
    """Prefer scoped evidence, then deterministic identity/usage ordering."""

    usage = event.get("usage") or {}
    return (
        not event.get("in_scope", False),
        _event_ref(page, event.get("thread_hash"), event.get("context_bound")),
        event.get("turn_hash") or "",
        stable_hash(usage),
        _event_sort_key(event, page),
    )


def _event_value_key(event: dict[str, Any], page: dict[str, Any]) -> tuple[Any, ...]:
    """Canonical key for duplicate call/output/timing records."""

    return (
        not event.get("in_scope", False),
        _event_ref(page, event.get("thread_hash"), event.get("context_bound")),
        event.get("turn_hash") or "",
        event.get("tool_hash") or "",
        event.get("arguments_hash") or "",
        event.get("output_hash") or "",
        event.get("output_bytes", 0),
        event.get("start_ms", 0),
        event.get("end_ms", 0),
        _event_sort_key(event, page),
    )


def _aggregate_requests(
    state: dict[str, Any], contexts: dict[tuple[str, str], str]
) -> tuple[dict[str, int] | None, int | None, dict[str, dict[str, Any]]]:
    grouped: defaultdict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for page in state["pages"]:
        for event in page["events"]:
            if event["kind"] == "request":
                grouped[event["response_hash"]].append((page, event))

    requests: dict[str, dict[str, Any]] = {}
    for response_hash, group in sorted(grouped.items()):
        group.sort(key=lambda pair: _request_sort_key(pair[1], pair[0]))
        scoped = any(event.get("in_scope", False) for _page, event in group)
        canonical_page, canonical_event = group[0]
        item = {
            **canonical_event,
            "ref": _event_ref(
                canonical_page,
                canonical_event.get("thread_hash"),
                canonical_event.get("context_bound"),
            ),
        }
        if scoped and len(group) > 1:
            state["counters"]["duplicate_usage_records"] += len(group) - 1
            if any(event["usage"] != canonical_event["usage"] for _page, event in group[1:]):
                state["counters"]["conflicting_usage_records"] += 1
            attrs = {
                (
                    _event_ref(page, event.get("thread_hash"), event.get("context_bound")),
                    event.get("turn_hash"),
                )
                for page, event in group
            }
            if len(attrs) > 1:
                state["counters"]["conflicting_response_attribution"] += 1
                item["ref"] = "conflict:response"
                item["turn_hash"] = None
        item["in_scope"] = scoped
        requests[response_hash] = item

    totals_keys = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    scoped_requests = [item for item in requests.values() if item["in_scope"]]
    if not scoped_requests:
        return None, None, requests
    totals = {key: sum(item["usage"][key] for item in scoped_requests) for key in totals_keys}
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    largest = max(item["usage"]["total_tokens"] for item in scoped_requests)
    return {"unique_responses": len(scoped_requests), **totals}, largest, requests


def _aggregate_cumulative(
    state: dict[str, Any],
) -> tuple[int | None, dict[str, int], dict[str, int]]:
    """Aggregate cumulative token snapshots without joining page streams.

    A ``token_count`` is a snapshot from the transcript page that contains it.
    The payload does not carry a reliable source/stream identity (and often
    does not carry a thread ID), so observations from two pages must not be
    interleaved by their inferred thread and treated as one monotonic counter.
    Decrease diagnostics are therefore computed within each page's original
    stream.  The latest value is still selected globally by observation time,
    but snapshots are never added together.
    """

    # Keep the old thread view as informational evidence.  It is deliberately
    # not used for decrease detection because one thread can occur in several
    # independently captured pages.
    by_ref: defaultdict[str, list[tuple[float | None, int, int]]] = defaultdict(list)
    source_refs: defaultdict[str, set[str]] = defaultdict(set)
    latest_by_source: dict[str, tuple[float | None, int, int, int]] = {}
    latest_observation: tuple[float | None, int, str, int, int] | None = None

    def sort_key(value: tuple[float | None, int, int]) -> tuple[Any, ...]:
        stamp, sequence, _total = value
        return (stamp is None, stamp or 0, sequence)

    for page in state["pages"]:
        stream: list[tuple[float | None, int, int]] = []
        source_hash = page["source_hash"]
        for event in page["events"]:
            if event["kind"] != "cumulative" or not event["in_scope"]:
                continue
            stamp = event["stamp"]
            sequence = event["sequence"]
            total = event["total"]
            stream.append((stamp, sequence, total))
            ref = _event_ref(page, event.get("thread_hash"), event.get("context_bound"))
            by_ref[ref].append((stamp, sequence, total))
            source_refs[ref].add(source_hash)

        # Only compare values from this source page.  Sorting by timestamp then
        # source-local sequence preserves deterministic chronology while keeping
        # malformed/missing timestamps at the same end as the previous API.
        stream.sort(key=sort_key)
        prior: int | None = None
        for stamp, sequence, total in stream:
            if prior is not None and total < prior:
                state["counters"]["cumulative_decreases"] += 1
            prior = total
            candidate = (stamp, sequence, source_hash, page["page_index"], total)
            if latest_observation is None or (
                (stamp is None, stamp or 0, sequence, source_hash, page["page_index"])
                > (
                    latest_observation[0] is None,
                    latest_observation[0] or 0,
                    latest_observation[1],
                    latest_observation[2],
                    latest_observation[3],
                )
            ):
                latest_observation = candidate

        if stream:
            stamp, sequence, total = stream[-1]
            existing = latest_by_source.get(source_hash)
            candidate = (stamp, sequence, total, page["page_index"])
            if existing is None or (
                (stamp is None, stamp or 0, sequence, page["page_index"])
                > (existing[0] is None, existing[0] or 0, existing[1], existing[3])
            ):
                latest_by_source[source_hash] = candidate

    # A thread appearing in multiple source pages is evidence that the values
    # are independent snapshots, not one continuous counter.
    state["counters"]["cumulative_multiple_sources"] = sum(
        1 for sources in source_refs.values() if len(sources) > 1
    )

    latest_by_ref: dict[str, int] = {}
    for ref, observations in by_ref.items():
        observations.sort(key=sort_key)
        if observations:
            latest_by_ref[ref] = observations[-1][2]

    latest = latest_observation[4] if latest_observation is not None else None
    latest_by_source_totals = {
        source_hash: value[2] for source_hash, value in latest_by_source.items()
    }
    return latest, latest_by_ref, latest_by_source_totals


def _empty_tool_stats() -> Counter:
    return Counter(
        {
            "calls": 0,
            "completed_calls": 0,
            "timed_calls": 0,
            "observed_span_ms": 0,
            "explicit_timed_calls": 0,
            "explicit_span_ms": 0,
            "output_bytes": 0,
            "largest_output_bytes": 0,
            "repeated_calls": 0,
            "repeated_after_compaction": 0,
            "unchanged_result_repeats": 0,
            "changed_result_repeats": 0,
            "unknown_result_repeats": 0,
        }
    )


def _aggregate_calls(
    state: dict[str, Any], contexts: dict[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    call_groups: defaultdict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = (
        defaultdict(list)
    )
    output_groups: defaultdict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = (
        defaultdict(list)
    )
    timing_groups: defaultdict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = (
        defaultdict(list)
    )
    call_id_refs: defaultdict[str, dict[str, bool]] = defaultdict(dict)
    for page in state["pages"]:
        for event in page["events"]:
            if event["kind"] == "call":
                ref = _event_ref(page, event.get("thread_hash"), event.get("context_bound"))
                call_groups[(ref, event["call_hash"])].append((page, event))
                call_id_refs[event["call_hash"]][ref] = call_id_refs[event["call_hash"]].get(
                    ref, False
                ) or event.get("in_scope", False)
            elif event["kind"] == "output":
                ref = _event_ref(page, event.get("thread_hash"), event.get("context_bound"))
                output_groups[(ref, event["call_hash"])].append((page, event))
            elif event["kind"] == "timing":
                ref = _event_ref(page, event.get("thread_hash"), event.get("context_bound"))
                timing_groups[(ref, event["item_hash"])].append((page, event))

    for refs in call_id_refs.values():
        if sum(refs.values()) > 1:
            state["counters"]["call_id_collisions"] += 1

    def canonical_group(
        groups: defaultdict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]],
        duplicate_key: str,
        conflict_key: str,
        compare_fields: tuple[str, ...],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for key, group in sorted(groups.items()):
            group.sort(key=lambda pair: _event_value_key(pair[1], pair[0]))
            scoped = any(event.get("in_scope", False) for _page, event in group)
            page, event = group[0]
            value = {**event, "ref": key[0], "_sort_key": _event_sort_key(event, page)}
            if scoped and len(group) > 1:
                state["counters"][duplicate_key] += len(group) - 1
                if any(
                    any(event.get(field) != group[0][1].get(field) for field in compare_fields)
                    for _page, event in group[1:]
                ):
                    state["counters"][conflict_key] += 1
            value["in_scope"] = scoped
            result[key] = value
        return result

    call_map = canonical_group(
        call_groups,
        "duplicate_call_records",
        "conflicting_call_records",
        ("tool_hash", "arguments_hash", "turn_hash"),
    )
    output_map = canonical_group(
        output_groups,
        "duplicate_output_records",
        "conflicting_output_records",
        ("output_hash", "output_bytes", "stamp"),
    )
    timing_map = canonical_group(
        timing_groups,
        "duplicate_item_timing",
        "conflicting_item_timing",
        ("start_ms", "end_ms"),
    )

    state["calls"] = []
    for key, call in call_map.items():
        call["output"] = output_map.get(key)
        explicit = timing_map.get(key)
        call["explicit"] = explicit if explicit is not None and explicit.get("in_scope") else None
        state["calls"].append(call)
    state["calls"].sort(key=lambda call: call.get("_sort_key", ()))
    state["outputs"] = list(output_map.values())
    for key, output in output_map.items():
        if key not in call_map and output.get("in_scope"):
            state["counters"]["unmatched_outputs"] += 1

    tools: dict[tuple[str, str], Counter] = {}
    tool_meta: dict[tuple[str, str], tuple[str, str]] = {}
    model_rows: dict[tuple[str, str, str], Counter] = {}
    fingerprints: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    waits: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    thread_meta = _thread_metadata(state)

    def role_for(ref: str) -> str:
        row = thread_meta.get(ref)
        if row is None or not row.get("known"):
            return "unknown"
        parents = row.get("parents", set())
        if len(parents) > 1:
            return "unknown"
        return _role_for(next(iter(parents)) if parents else None)

    for call in state["calls"]:
        turn_key = call.get("turn_hash")
        model = contexts.get((call["ref"], turn_key), "unknown") if turn_key else "unknown"
        if model == "unknown" and call["in_scope"]:
            state["counters"]["missing_model_attribution"] += 1
        call["model"] = model
        role = role_for(call["ref"])
        if not call["in_scope"]:
            continue
        model_key = (_public_thread_hash(call["ref"]), model, role)
        row = model_rows.setdefault(model_key, Counter())
        row["calls"] += 1

        tool_key = (call["ref"], call["tool_hash"])
        stats = tools.setdefault(tool_key, _empty_tool_stats())
        tool_meta[tool_key] = (call["namespace_hash"], call["name_hash"])
        stats["calls"] += 1
        fingerprint = stable_hash(
            [call["ref"], call["namespace_hash"], call["name_hash"], call["arguments_hash"]]
        )
        prior_calls = fingerprints[(call["ref"], fingerprint)]
        if prior_calls:
            stats["repeated_calls"] += 1
            previous = prior_calls[-1]
            if call.get("generation", 0) > previous.get("generation", 0):
                stats["repeated_after_compaction"] += 1
            prior_output = next(
                (
                    item["output"]
                    for item in reversed(prior_calls)
                    if item.get("output") is not None and item["output"].get("in_scope")
                ),
                None,
            )
            current_output = call.get("output")
            category = "unknown_result_repeats"
            if (
                prior_output is not None
                and current_output is not None
                and current_output.get("in_scope")
                and prior_output.get("output_hash") is not None
                and current_output.get("output_hash") is not None
            ):
                category = (
                    "unchanged_result_repeats"
                    if prior_output["output_hash"] == current_output["output_hash"]
                    else "changed_result_repeats"
                )
            stats[category] += 1
            state["counters"][category] += 1
        prior_calls.append(call)

        output = call.get("output")
        if output is not None and output.get("in_scope"):
            stats["completed_calls"] += 1
            stats["output_bytes"] += output["output_bytes"]
            stats["largest_output_bytes"] = max(
                stats["largest_output_bytes"], output["output_bytes"]
            )
            start = call.get("stamp")
            end = output.get("stamp")
            if start is not None and end is not None and end >= start:
                stats["timed_calls"] += 1
                stats["observed_span_ms"] += round((end - start) * 1000)
            explicit = call.get("explicit")
            if explicit is not None:
                stats["explicit_timed_calls"] += 1
                stats["explicit_span_ms"] += round(explicit["end_ms"] - explicit["start_ms"])
            elif start is None or end is None or end < start:
                state["counters"]["missing_timing_records"] += 1
            row["completed_calls"] += 1

        if not call.get("wait_candidate"):
            continue
        wait_key = (_public_thread_hash(call["ref"]), model, role, call["tool_hash"])
        wait = waits.setdefault(
            wait_key,
            {
                "thread_hash": wait_key[0],
                "model": model,
                "role": role,
                "tool_hash": call["tool_hash"],
                "namespace_hash": call["namespace_hash"],
                "calls": 0,
                "timed_out": 0,
                "event_returns": 0,
                "unknown": 0,
                "requested_timeout_ms_histogram": Counter(),
                "durations": [],
                "short_timeouts": 0,
            },
        )
        wait["calls"] += 1
        if call["timeout_valid"]:
            value = call["timeout_ms"]
            key_text = str(int(value)) if value.is_integer() else str(value)
            wait["requested_timeout_ms_histogram"][key_text] += 1
        else:
            state["counters"]["invalid_wait_arguments"] += 1
        output = call.get("output")
        classification = "unknown"
        if output is not None and output.get("in_scope"):
            classification = output.get("wait_class", "unknown")
            if classification == "timeout":
                wait["timed_out"] += 1
            elif classification == "event_return":
                wait["event_returns"] += 1
            else:
                wait["unknown"] += 1
                state["counters"]["invalid_wait_results"] += 1
        else:
            wait["unknown"] += 1

        duration: float | None = None
        explicit = call.get("explicit")
        if explicit is not None and output is not None and output.get("in_scope"):
            duration = explicit["end_ms"] - explicit["start_ms"]
        elif (
            output is not None
            and output.get("in_scope")
            and call.get("stamp") is not None
            and output.get("stamp") is not None
            and output["stamp"] >= call["stamp"]
        ):
            duration = (output["stamp"] - call["stamp"]) * 1000
        if duration is not None:
            wait["durations"].append(duration)
        if classification == "timeout" and duration is not None and duration < 60_000:
            wait["short_timeouts"] += 1
            state["counters"]["short_timeouts"] += 1

    requests_by_response = state.get("requests_by_response", {})
    for item in requests_by_response.values():
        if not item["in_scope"]:
            continue
        ref = item["ref"]
        model = (
            contexts.get((ref, item.get("turn_hash")), "unknown")
            if item.get("turn_hash")
            else "unknown"
        )
        if model == "unknown":
            state["counters"]["missing_model_attribution"] += 1
        role = role_for(ref)
        key = (_public_thread_hash(ref), model, role)
        row = model_rows.setdefault(key, Counter())
        row["unique_responses"] += 1
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
        ):
            row[field] += item["usage"][field]

    fields = (
        "calls",
        "completed_calls",
        "timed_calls",
        "observed_span_ms",
        "explicit_timed_calls",
        "explicit_span_ms",
        "output_bytes",
        "largest_output_bytes",
        "repeated_calls",
        "repeated_after_compaction",
        "unchanged_result_repeats",
        "changed_result_repeats",
        "unknown_result_repeats",
    )
    tool_rows = []
    for (ref, tool_hash), stats in sorted(tools.items(), key=lambda item: item[0]):
        namespace_hash, name_hash = tool_meta[(ref, tool_hash)]
        tool_rows.append(
            {
                "thread_hash": _public_thread_hash(ref),
                "tool_hash": tool_hash,
                "namespace_hash": namespace_hash,
                "name_hash": name_hash,
                **{field: stats[field] for field in fields},
            }
        )

    wait_rows = []
    for wait in sorted(
        waits.values(),
        key=lambda item: (
            item["thread_hash"],
            item["model"],
            item["role"],
            item["tool_hash"],
        ),
    ):
        durations = wait.pop("durations")
        histogram = dict(sorted(wait.pop("requested_timeout_ms_histogram").items()))
        wait["requested_timeout_ms_histogram"] = histogram
        wait["actual_duration_ms"] = {
            "count": len(durations),
            "p50": _percentile(durations, 0.50),
            "p90": _percentile(durations, 0.90),
        }
        wait_rows.append(wait)

    model_usage = []
    for (thread_hash, model, role), values in sorted(model_rows.items()):
        row = {"thread_hash": thread_hash, "model": model, "role": role}
        row.update({key: values[key] for key in sorted(values)})
        if "input_tokens" in row:
            row["uncached_input_tokens"] = row["input_tokens"] - row.get("cached_input_tokens", 0)
        model_usage.append(row)
    return tool_rows, model_usage, wait_rows


def _finalize(state: dict[str, Any]) -> dict[str, Any]:
    _canonicalize_pages(state)
    _resolve_page_refs(state)
    contexts = _resolve_contexts(state)
    request_usage, largest_request, requests = _aggregate_requests(state, contexts)
    state["requests_by_response"] = requests
    latest_cumulative, latest_by_ref, latest_by_source = _aggregate_cumulative(state)
    tool_rows, model_usage, wait_rows = _aggregate_calls(state, contexts)

    diagnostics = dict(state["counters"])
    for key in _DIAGNOSTIC_KEYS:
        diagnostics.setdefault(key, 0)
    timestamps = state["timestamps"]
    elapsed = (
        round(
            (max(value[0] for value in timestamps) - min(value[0] for value in timestamps))
            * 1000
        )
        if timestamps
        else None
    )
    metadata = _thread_metadata(state)
    thread_roles: dict[str, str] = {}
    for ref, row in metadata.items():
        parents = row.get("parents", set())
        parent_hash = next(iter(parents)) if len(parents) == 1 else None
        thread_roles[ref] = _role_for(
            parent_hash, known=row.get("known", False) and len(parents) <= 1
        )
    lifecycle_events: list[dict[str, Any]] = []
    for page in state["pages"]:
        for event in page["events"]:
            if event.get("kind") not in (
                "task_started",
                "task_complete",
                "turn_aborted",
                "compacted",
            ):
                continue
            item = dict(event)
            item["ref"] = _event_ref(
                page,
                event.get("thread_hash"),
                event.get("context_bound"),
            )
            lifecycle_events.append(item)
    lifecycle = aggregate_lifecycle(
        lifecycle_events,
        contexts=contexts,
        thread_roles=thread_roles,
    )
    threads_by_public: dict[tuple[str, str], dict[str, Any]] = {}
    for ref, row in metadata.items():
        thread_hash = _public_thread_hash(ref)
        parents = row.get("parents", set())
        parent_hash = next(iter(parents)) if len(parents) == 1 else None
        role = _role_for(parent_hash, known=row.get("known", False) and len(parents) <= 1)
        key = (thread_hash, role)
        out = threads_by_public.setdefault(
            key,
            {
                "thread_hash": thread_hash,
                "parent_hash": parent_hash,
                "role": role,
                "pages": 0,
                "started_at": None,
            },
        )
        out["pages"] += len(row.get("pages", set()))
        started = row.get("started_at")
        if started is not None:
            out["started_at"] = (
                started if out["started_at"] is None else min(out["started_at"], started)
            )
    threads = sorted(threads_by_public.values(), key=lambda row: (row["thread_hash"], row["role"]))
    files = [
        {
            "source_hash": page["source_hash"],
            "snapshot_bytes": page["snapshot_bytes"],
            "diagnostics": dict(sorted(page["diagnostics"].items())),
        }
        for page in state["pages"]
    ]
    return {
        "schema_version": 2,
        "pages": len(files),
        "files": files,
        "observed_elapsed_ms": elapsed,
        "compactions": state["compactions"],
        "diagnostics": diagnostics,
        "request_usage": request_usage,
        "largest_request_tokens": largest_request,
        "latest_cumulative_tokens": latest_cumulative,
        "latest_cumulative_tokens_by_thread": [
            {"thread_hash": _public_thread_hash(ref), "total_tokens": total}
            for ref, total in sorted(latest_by_ref.items())
        ],
        "latest_cumulative_tokens_by_source": [
            {"source_hash": source_hash, "total_tokens": total}
            for source_hash, total in sorted(latest_by_source.items())
        ],
        "request_minus_latest_cumulative_tokens": (
            request_usage["total_tokens"] - latest_cumulative
            if request_usage is not None and latest_cumulative is not None
            else None
        ),
        "tools": tool_rows,
        "threads": threads,
        "model_usage": model_usage,
        "waits": wait_rows,
        "lifecycle": lifecycle,
        "limitations": [
            "Request usage is deduplicated by response ID across pages.",
            "Thread identity uses session_meta.id or explicit thread_id; "
            "session_id is never a thread key.",
            "Cumulative snapshots are compared within each source page and are "
            "never added to request usage.",
            "A thread observed in multiple source pages does not imply one "
            "continuous cumulative counter.",
            "Missing model context is unknown; models are not inherited across threads or turns.",
            "Call/output spans can overlap and include waiting; they are not CPU time.",
            "Explicit item timing is preferred for actual-duration summaries.",
            "Repeated calls are diagnostics only and do not prove waste or change governance.",
            "This report is not billing data and does not change enforcement.",
        ],
    }


def _prepare_page(
    state: dict[str, Any],
    raw_path: Path,
    *,
    raise_errors: bool,
    captured_total: int,
) -> tuple[dict[str, Any], int]:
    try:
        resolved = raw_path.resolve()
    except (OSError, RuntimeError):
        resolved = raw_path
    source_hash = stable_hash(str(resolved))
    try:
        initial_stat = os.lstat(raw_path)
    except (OSError, ValueError):
        if raise_errors:
            raise ValueError("audit requires a readable regular transcript") from None
        page = _new_page(source_hash, None)
        page["page_index"] = len(state["pages"])
        _diag(state, page, "unreadable_files")
        state["pages"].append(page)
        return page, captured_total
    page = _new_page(source_hash, None)
    page["page_index"] = len(state["pages"])
    if not stat_module.S_ISREG(initial_stat.st_mode):
        if raise_errors:
            raise ValueError("audit requires a readable regular transcript")
        _diag(state, page, "not_regular_files")
        state["pages"].append(page)
        return page, captured_total
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(raw_path, flags)
        opened_stat = os.fstat(fd)
        if (
            not stat_module.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_dev != initial_stat.st_dev
            or opened_stat.st_ino != initial_stat.st_ino
        ):
            os.close(fd)
            _snapshot_diag(state, page)
            if raise_errors:
                raise ValueError("unable to read transcript snapshot") from None
            state["pages"].append(page)
            return page, captured_total
        handle = os.fdopen(fd, "rb")
    except (OSError, ValueError):
        try:
            os.close(fd)
        except (OSError, UnboundLocalError):
            pass
        if raise_errors:
            raise ValueError("audit requires a readable regular transcript") from None
        _diag(state, page, "unreadable_files")
        state["pages"].append(page)
        return page, captured_total
    page["snapshot_bytes"] = opened_stat.st_size
    if opened_stat.st_size > MAX_TRANSCRIPT_BYTES:
        if raise_errors:
            handle.close()
            raise ValueError("audit requires a regular transcript no larger than 256 MiB")
        _diag(state, page, "oversized_files")
        _diag(state, page, "resource_limited")
        handle.close()
    elif captured_total + opened_stat.st_size > MAX_AUDIT_BYTES:
        _diag(state, page, "snapshot_cap")
        _diag(state, page, "resource_limited")
        handle.close()
    else:
        _parse_file(
            state,
            page,
            raw_path,
            opened_stat.st_size,
            handle,
            opened_stat,
            raise_errors=raise_errors,
        )
        captured_total += opened_stat.st_size
    state["pages"].append(page)
    return page, captured_total


def audit_transcripts(
    paths: Iterable[Path], *, since: float | None = None, until: float | None = None
) -> dict[str, Any]:
    """Audit multiple transcript pages with cross-page deduplication.

    Metadata and turn contexts are collected independently of the time range;
    only event statistics are filtered by ``since``/``until``.  Files that are
    unreadable, oversized, changing, or over the aggregate snapshot cap are
    represented by bounded diagnostics rather than leaking paths or content.
    """

    state = _new_state(since, until)
    captured_total = 0
    for raw in paths:
        try:
            path = raw if isinstance(raw, Path) else Path(raw)
        except (TypeError, ValueError):
            page = _new_page(stable_hash(repr(type(raw))), None)
            page["page_index"] = len(state["pages"])
            _diag(state, page, "unreadable_files")
            state["pages"].append(page)
            continue
        _, captured_total = _prepare_page(
            state, path, raise_errors=False, captured_total=captured_total
        )
    return _finalize(state)


def audit_transcript(path: Path) -> dict[str, Any]:
    """Analyze one bounded snapshot, retaining the v1 report fields."""

    state = _new_state(None, None)
    _prepare_page(state, Path(path), raise_errors=True, captured_total=0)
    result = _finalize(state)
    page = state["pages"][0]
    # The single-file API historically returned a report directly rather than
    # a page list.  Keep all old keys and expose v2 additions alongside them.
    result["source_hash"] = page["source_hash"]
    result["snapshot_bytes"] = page["snapshot_bytes"]
    result["files"] = None
    result["pages"] = 1
    return result
