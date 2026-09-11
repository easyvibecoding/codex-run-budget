"""Pure, privacy-preserving aggregation for native turn lifecycle events.

The transcript reader deliberately does the unsafe work of decoding JSON and
normalising identifiers.  This module only consumes the small, sanitised event
records produced by :mod:`codex_run_budget.audit`; it never sees prompts,
messages, tool arguments, or raw lifecycle reasons.  The result is an
*observed* lifecycle view.  A turn with no terminal event is not classified as
running or stuck because a bounded transcript may simply end before the
terminal record was captured.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

LIFECYCLE_SCHEMA_VERSION = 1
_KINDS = frozenset(("task_started", "task_complete", "turn_aborted", "compacted"))
_TERMINAL_KINDS = frozenset(("task_complete", "turn_aborted"))


def _finite_number(value: Any) -> float | None:
    """Return a finite numeric value without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _event_order(event: Mapping[str, Any]) -> tuple[Any, ...]:
    """Stable order that contains no transcript text or filesystem paths."""

    stamp = event.get("stamp")
    return (
        stamp is None,
        stamp if stamp is not None else 0,
        str(event.get("source_hash") or ""),
        int(event.get("sequence") or 0),
        str(event.get("event_hash") or ""),
    )


def _identity_key(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return event.get("thread_hash"), event.get("turn_hash")


def _value_key(event: Mapping[str, Any]) -> tuple[Any, ...]:
    """Semantic key used to distinguish replay from contradictory evidence."""

    return (
        event.get("kind"),
        event.get("duration_ms"),
        event.get("time_to_first_token_ms"),
    )


def _canonical(events: list[dict[str, Any]]) -> tuple[dict[str, Any], int, bool]:
    """Choose deterministic evidence and report duplicate/conflict status.

    The earliest timeline record wins, including a pre-window start replayed
    inside the window; source and sequence are only
    deterministic tie breakers.  Top-level replay stamps are intentionally not
    treated as semantic terminal conflicts: native pages can stamp one replay
    at a different time while retaining the same lifecycle payload.
    """

    ordered = sorted(
        events,
        key=lambda item: (
            _event_order(item),
            _value_key(item),
        ),
    )
    winner = dict(ordered[0])
    scoped = [item for item in ordered if item.get("in_scope")]
    compare = scoped or ordered
    values = {_value_key(item) for item in compare}
    return winner, max(0, len(compare) - 1), len(values) > 1


def _empty_diagnostics() -> Counter:
    return Counter(
        {
            "invalid_events": 0,
            "missing_thread_id": 0,
            "missing_turn_id": 0,
            "invalid_thread_id": 0,
            "invalid_turn_id": 0,
            "duplicate_events": 0,
            "conflicting_events": 0,
            "conflicting_terminal_states": 0,
            "conflicting_terminal_values": 0,
            "invalid_duration": 0,
            "invalid_time_to_first_token": 0,
            "duplicate_compactions": 0,
            "conflicting_compaction_context": 0,
            "missing_compaction_window_id": 0,
            "invalid_compaction_window_id": 0,
            "unattributed_lifecycle_events": 0,
            "unattributed_compactions": 0,
            "missing_terminal": 0,
            "ambiguous_later_turn": 0,
        }
    )


def _normalise_event(item: Mapping[str, Any], diagnostics: Counter) -> dict[str, Any] | None:
    """Copy only the bounded fields understood by the aggregator.

    This defensive copy matters for direct callers of the public pure
    function.  Unknown keys are discarded so a caller cannot accidentally
    make raw message/reason fields part of the report.
    """

    if not isinstance(item, Mapping):
        diagnostics["invalid_events"] += 1
        return None
    kind = item.get("kind")
    if kind not in _KINDS:
        diagnostics["invalid_events"] += 1
        return None
    thread_hash = item.get("thread_hash")
    turn_hash = item.get("turn_hash")
    if thread_hash is not None and not isinstance(thread_hash, str):
        diagnostics["invalid_thread_id"] += 1
        thread_hash = None
    if turn_hash is not None and not isinstance(turn_hash, str):
        diagnostics["invalid_turn_id"] += 1
        turn_hash = None
    if not thread_hash:
        if item.get("thread_invalid"):
            diagnostics["invalid_thread_id"] += 1
        else:
            diagnostics["missing_thread_id"] += 1
    if not turn_hash:
        if item.get("turn_invalid"):
            diagnostics["invalid_turn_id"] += 1
        else:
            diagnostics["missing_turn_id"] += 1

    stamp = _finite_number(item.get("stamp"))
    duration = item.get("duration_ms")
    if item.get("duration_invalid"):
        diagnostics["invalid_duration"] += 1
    if duration is not None:
        duration = _finite_number(duration)
        if duration is None or duration < 0:
            diagnostics["invalid_duration"] += 1
            duration = None
    ttfb = item.get("time_to_first_token_ms")
    if item.get("time_to_first_token_invalid"):
        diagnostics["invalid_time_to_first_token"] += 1
    if ttfb is not None:
        ttfb = _finite_number(ttfb)
        if ttfb is None or ttfb < 0:
            diagnostics["invalid_time_to_first_token"] += 1
            ttfb = None
    window_hash = item.get("window_hash")
    if window_hash is not None and not isinstance(window_hash, str):
        diagnostics["invalid_compaction_window_id"] += 1
        window_hash = None
    event = {
        "kind": kind,
        "thread_hash": thread_hash or None,
        "turn_hash": turn_hash or None,
        "stamp": stamp,
        "in_scope": bool(item.get("in_scope", True)),
        "before_window": bool(item.get("before_window")),
        "source_hash": item.get("source_hash") if isinstance(item.get("source_hash"), str) else "",
        "sequence": item.get("sequence") if type(item.get("sequence")) is int else 0,
        "event_hash": item.get("event_hash") if isinstance(item.get("event_hash"), str) else "",
        "model": item.get("model") if isinstance(item.get("model"), str) else None,
        "duration_ms": duration,
        "time_to_first_token_ms": ttfb,
        "window_hash": window_hash,
        "thread_invalid": bool(item.get("thread_invalid")),
        "turn_invalid": bool(item.get("turn_invalid")),
        "window_invalid": bool(item.get("window_invalid")),
        "ref": item.get("ref") if isinstance(item.get("ref"), str) else None,
    }
    return event


def _scope_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return event records that can influence a bounded report.

    Out-of-window start events remain available to mark
    ``started_before_window``.  Other old events do not establish a terminal
    state, and future events are never allowed to affect the report.
    """

    return [item for item in events if item.get("in_scope")]


def _duration_from_events(
    start: Mapping[str, Any] | None,
    terminal: Mapping[str, Any] | None,
) -> tuple[float | None, str | None]:
    if terminal is not None and terminal.get("duration_ms") is not None:
        return terminal["duration_ms"], "explicit"
    if start is None or terminal is None:
        return None, None
    start_stamp, end_stamp = start.get("stamp"), terminal.get("stamp")
    if start_stamp is None or end_stamp is None or end_stamp < start_stamp:
        return None, None
    return round((end_stamp - start_stamp) * 1000), "event_span"


def _model_for(
    ref: str,
    turn_hash: str,
    row_events: Iterable[Mapping[str, Any]],
    contexts: Mapping[tuple[str, str], str],
    diagnostics: Counter,
) -> str:
    context_model = contexts.get((ref, turn_hash))
    if isinstance(context_model, str) and context_model and context_model != "unknown":
        event_models = {
            item.get("model")
            for item in row_events
            if item.get("in_scope")
            and isinstance(item.get("model"), str)
            and item.get("model") not in (None, "unknown")
        }
        if event_models and (event_models - {context_model}):
            diagnostics["conflicting_model"] += 1
            return "unknown"
        return context_model
    event_models = {
        item.get("model")
        for item in row_events
        if item.get("in_scope")
        and isinstance(item.get("model"), str)
        and item.get("model") not in (None, "unknown")
    }
    if len(event_models) == 1:
        return next(iter(event_models))
    if len(event_models) > 1:
        diagnostics["conflicting_model"] += 1
    return "unknown"


def _compaction_groups(
    events: list[dict[str, Any]], diagnostics: Counter
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    """Deduplicate compacted events, returning evidence and per-turn counts."""

    scoped = [item for item in events if item["kind"] == "compacted" and item["in_scope"]]
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in scoped:
        if item.get("window_invalid"):
            diagnostics["invalid_compaction_window_id"] += 1
        window_hash = item.get("window_hash")
        if window_hash:
            key = ("window", window_hash)
        elif item.get("stamp") is not None:
            # Without a window id, same-context records at the same timeline
            # point are the only safe bounded replay key.  Distinct timestamps
            # remain separate observations.
            key = (
                "stamp",
                item.get("ref"),
                item.get("thread_hash"),
                item.get("turn_hash"),
                item.get("stamp"),
            )
            diagnostics["missing_compaction_window_id"] += 1
        else:
            key = (
                "event",
                item.get("ref"),
                item.get("thread_hash"),
                item.get("turn_hash"),
                item.get("source_hash"),
                item.get("sequence"),
            )
            diagnostics["missing_compaction_window_id"] += 1
        groups[key].append(item)

    unique: list[dict[str, Any]] = []
    by_turn: Counter[tuple[str, str]] = Counter()
    for _key, group in sorted(groups.items(), key=lambda pair: repr(pair[0])):
        winner = sorted(group, key=lambda item: _event_order(item))[0]
        unique.append(winner)
        if len(group) > 1:
            diagnostics["duplicate_compactions"] += len(group) - 1
        identities = {_identity_key(item) for item in group}
        if len(identities) > 1:
            diagnostics["conflicting_compaction_context"] += 1
            diagnostics["unattributed_compactions"] += 1
            continue
        thread_hash, turn_hash = _identity_key(winner)
        if thread_hash and turn_hash:
            by_turn[(thread_hash, turn_hash)] += 1
        else:
            diagnostics["unattributed_compactions"] += 1
    return unique, dict(by_turn)


def aggregate_lifecycle(
    events: Iterable[Mapping[str, Any]],
    *,
    contexts: Mapping[tuple[str, str], str] | None = None,
    thread_roles: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Aggregate sanitised native lifecycle events into a bounded report.

    ``events`` must contain only privacy-safe fields (hashed identifiers,
    fixed model labels, timestamps, and validated numeric durations).  The
    function is intentionally tolerant of malformed direct input: invalid
    records are diagnosed and omitted instead of being turned into a guessed
    identity.  ``in_scope`` is computed by the transcript parser; callers that
    do not use a time window can simply set it to ``True``.
    """

    diagnostics = _empty_diagnostics()
    contexts = contexts or {}
    thread_roles = thread_roles or {}
    normalised = []
    for item in events:
        # Future records and old terminal/compaction records must not alter a
        # bounded report, including its invalid-ID diagnostics.  A start
        # before the lower bound is the sole exception: it can provide
        # context for an in-window terminal or compaction.
        if isinstance(item, Mapping):
            kind = item.get("kind")
            if not item.get("in_scope", True) and not (
                kind == "task_started" and item.get("before_window")
            ):
                continue
        event = _normalise_event(item, diagnostics)
        if event is not None:
            normalised.append(event)

    # Unknown or explicitly invalid identities never become a fabricated
    # ``hash(None)`` turn.  Keep their diagnostics, but do not let them alter
    # state or later-turn relationships.
    valid = []
    for event in normalised:
        if not event["thread_hash"] or not event["turn_hash"]:
            if event["kind"] == "compacted":
                # Compactions are still counted in the aggregate, even when
                # no turn can safely own them.
                continue
            diagnostics["unattributed_lifecycle_events"] += 1
            continue
        valid.append(event)

    compactions, compactions_by_turn = _compaction_groups(normalised, diagnostics)
    # Keep all in-window and pre-window lifecycle evidence in each group.  A
    # group is materialised only when at least one lifecycle event is in the
    # requested window; old starts then remain useful context without making an
    # old-only turn appear in the bounded report.
    all_groups: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in valid:
        if event["kind"] != "compacted":
            all_groups[(event["thread_hash"], event["turn_hash"])].append(event)
    for key, count in compactions_by_turn.items():
        if count:
            all_groups.setdefault(key, [])

    rows: list[dict[str, Any]] = []
    turn_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    compaction_events_by_turn: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for event in compactions:
        event_key = _identity_key(event)
        if event_key[0] and event_key[1]:
            compaction_events_by_turn[event_key].append(event)

    for key, all_group in sorted(all_groups.items()):
        thread_hash, turn_hash = key
        scoped_group = [item for item in all_group if item["in_scope"]]
        if not scoped_group and not compactions_by_turn.get(key):
            continue
        starts = [item for item in all_group if item["kind"] == "task_started"]
        terminals = [
            item for item in all_group if item["kind"] in _TERMINAL_KINDS and item["in_scope"]
        ]
        # Group event kind first, then canonicalise each kind.  A start's
        # timestamp difference is normal replay evidence, not a conflict.
        start, duplicate_starts, _start_conflict = (
            _canonical(starts) if starts else (None, 0, False)
        )
        if duplicate_starts:
            diagnostics["duplicate_events"] += duplicate_starts
        terminal_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in terminals:
            terminal_by_kind[event["kind"]].append(event)
        canonical_terminals: list[dict[str, Any]] = []
        terminal_values_conflicted = False
        for kind, same_kind in sorted(terminal_by_kind.items()):
            canonical, duplicate_count, conflict = _canonical(same_kind)
            canonical_terminals.append(canonical)
            diagnostics["duplicate_events"] += duplicate_count
            if conflict:
                diagnostics["conflicting_terminal_values"] += 1
                diagnostics["conflicting_events"] += 1
                terminal_values_conflicted = True
        terminal: dict[str, Any] | None = None
        state = "no_terminal_observed"
        if len(canonical_terminals) > 1 or terminal_values_conflicted:
            if len(canonical_terminals) > 1:
                diagnostics["conflicting_terminal_states"] += 1
                diagnostics["conflicting_events"] += 1
            state = "conflicted"
        elif canonical_terminals:
            terminal = canonical_terminals[0]
            state = "completed" if terminal["kind"] == "task_complete" else "aborted"
        if state == "no_terminal_observed":
            diagnostics["missing_terminal"] += 1

        # A valid start before the lower bound is still observed evidence and
        # may explain an in-window terminal.  Its timestamp remains visible as
        # context; ``started_before_window`` distinguishes it from an
        # in-window start.  Only a truly missing start is start-missing.
        before_window = any(item.get("before_window") for item in starts)
        start_observed = bool(starts)
        chosen_start = start if start_observed else None
        started_at = chosen_start.get("stamp") if chosen_start else None
        ended_at = terminal.get("stamp") if terminal is not None else None
        duration_ms, duration_source = _duration_from_events(chosen_start, terminal)
        row_events = [
            *all_group,
            *compaction_events_by_turn.get(key, []),
            *canonical_terminals,
        ]
        ref = str((row_events or starts or canonical_terminals)[0].get("ref") or "")
        model = _model_for(
            # The parser's canonical ref is carried on every event; use the
            # first one for context attribution.
            ref,
            turn_hash,
            row_events,
            contexts,
            diagnostics,
        )
        role = thread_roles.get(ref, "unknown")
        row = {
            "thread_hash": thread_hash,
            "turn_hash": turn_hash,
            "model": model,
            "role": role,
            "state": state,
            "start_observed": start_observed,
            "started_at": started_at,
            "ended_at": ended_at,
            "started_before_window": before_window,
            "duration_ms": duration_ms,
            "duration_source": duration_source,
            "time_to_first_token_ms": (
                terminal.get("time_to_first_token_ms") if terminal is not None else None
            ),
            "compactions": compactions_by_turn.get(key, 0),
            "later_turn_observed": False,
            "next_turn_hash": None,
            "gap_to_next_turn_ms": None,
        }
        rows.append(row)
        turn_evidence[key] = {
            "start": chosen_start,
            "terminal": terminal,
            "events": row_events,
        }

    # A canonical start is needed to identify later turns.  Starts that have
    # no other in-window event still count as future turns, but they do not
    # create a row unless they themselves are in scope (the grouping above
    # already does so).
    starts_by_thread: defaultdict[str, dict[float, set[tuple[str, str]]]] = defaultdict(dict)
    for key, evidence in turn_evidence.items():
        start = evidence["start"]
        if start is not None and start.get("in_scope") and start.get("stamp") is not None:
            starts_by_thread[key[0]].setdefault(start["stamp"], set()).add(key)
    # Build the timestamp arrays once.  Constructing/slicing a full start list
    # inside the row loop would turn even a bisect lookup back into O(n²).
    start_indexes = {
        thread: (sorted(starts), starts) for thread, starts in starts_by_thread.items()
    }

    row_by_key = {(row["thread_hash"], row["turn_hash"]): row for row in rows}
    for key, row in row_by_key.items():
        evidence = turn_evidence[key]
        chosen_start = evidence["start"]
        terminal = evidence["terminal"]
        group = evidence["events"]
        anchor = terminal or chosen_start
        if anchor is None:
            scoped_group = [item for item in group if item.get("in_scope")]
            anchor = min(scoped_group, key=_event_order) if scoped_group else None
        if anchor is None or anchor.get("stamp") is None:
            continue
        anchor_stamp = anchor["stamp"]
        stamps, starts = start_indexes.get(key[0], ([], {}))
        start_index = bisect_right(stamps, anchor_stamp)
        if start_index == len(stamps):
            continue
        next_stamp = stamps[start_index]
        candidates = starts[next_stamp]
        candidate_count = len(candidates) - (key in candidates)
        # A canonical turn has only one start, so at most one timestamp group
        # can consist solely of the current turn.
        if not candidate_count:
            start_index += 1
            if start_index == len(stamps):
                continue
            next_stamp = stamps[start_index]
            candidates = starts[next_stamp]
            candidate_count = len(candidates)
        next_key = (
            next(value for value in candidates if value != key) if candidate_count == 1 else None
        )
        if next_key is None:
            diagnostics["ambiguous_later_turn"] += 1
        row["later_turn_observed"] = True
        row["next_turn_hash"] = next_key[1] if next_key is not None else None
        if row.get("ended_at") is not None:
            gap = (next_stamp - row["ended_at"]) * 1000
            if math.isfinite(gap) and gap >= 0:
                row["gap_to_next_turn_ms"] = round(gap)

    summary = {
        "turns": len(rows),
        "completed": sum(row["state"] == "completed" for row in rows),
        "aborted": sum(row["state"] == "aborted" for row in rows),
        "no_terminal_observed": sum(row["state"] == "no_terminal_observed" for row in rows),
        "conflicted": sum(row["state"] == "conflicted" for row in rows),
        "started_before_window": sum(row["started_before_window"] for row in rows),
        "start_missing": sum(not row["start_observed"] for row in rows),
        "aborted_with_later_turn": sum(
            row["state"] == "aborted" and row["later_turn_observed"] for row in rows
        ),
        "no_terminal_with_later_turn": sum(
            row["state"] == "no_terminal_observed" and row["later_turn_observed"] for row in rows
        ),
        "compactions": len(compactions),
        "unattributed_compactions": diagnostics["unattributed_compactions"],
    }
    diagnostics.setdefault("conflicting_model", 0)
    diagnostics.setdefault("conflicting_compaction_context", 0)
    diagnostics.setdefault("missing_terminal", 0)
    limitations = [
        "Lifecycle state is observed evidence in bounded transcript snapshots, "
        "not a running/stuck classifier.",
        "A missing terminal record does not prove that work is still running or stuck.",
        "A later turn start does not prove same-work recovery or causal relation.",
        "Only top-level record timestamps establish bounded chronology; payload "
        "messages and reasons are discarded.",
        "Durations are explicit native values when present, otherwise observed "
        "event spans; they are wall-clock spans, not CPU time.",
        "Compactions without a stable window identity are conservatively "
        "deduplicated only at the same observed timestamp.",
        "This report is privacy-preserving diagnostics and is not billing or enforcement data.",
    ]
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "summary": summary,
        "turns": sorted(rows, key=lambda row: (row["thread_hash"], row["turn_hash"])),
        "diagnostics": dict(sorted(diagnostics.items())),
        "limitations": limitations,
    }


__all__ = ["LIFECYCLE_SCHEMA_VERSION", "aggregate_lifecycle"]
