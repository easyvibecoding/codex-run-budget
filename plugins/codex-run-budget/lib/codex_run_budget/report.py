"""Read-only, single-snapshot Task reports. No quota allocation or ledger writes."""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .meter import _selected_threads, compare_snapshots, load_snapshots
from .meter_policy import credit_scenarios, pricing_context
from .survey import survey_transcripts

TOKEN_FIELDS = (
    "unique_responses",
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
DEFAULT_WINDOWS = ("5h", "24h", "7d", "30d")
MAX_REPORT_BYTES = 16 * 1024 * 1024


def _iso(stamp: float, zone: ZoneInfo | timezone = timezone.utc) -> str:
    return datetime.fromtimestamp(stamp, zone).isoformat()


def _stamp(value: str | None, fallback: float) -> float:
    if value is None:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps require an explicit UTC offset")
    return parsed.timestamp()


def resolve_windows(
    names: list[str] | tuple[str, ...] | None = None,
    *,
    timezone_name: str = "UTC",
    since: str | None = None,
    until: str | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Independent [start, end) windows, all ending at one captured instant.

    Calendar boundaries use local wall time (Monday weeks); rolling windows
    use elapsed seconds, so DST days are not incorrectly treated as 24 hours.
    """
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("unknown IANA time zone") from exc
    captured = time.time() if now is None else now
    end = _stamp(until, captured)
    if not math.isfinite(end) or not math.isfinite(captured) or end > captured:
        raise ValueError("report end must not be in the future")
    chosen = list(names if names is not None else (() if since else DEFAULT_WINDOWS))
    if not chosen and not since or len(chosen) > 12:
        raise ValueError("choose between 1 and 12 windows")
    if len(set(chosen)) != len(chosen):
        raise ValueError("duplicate windows")
    local = datetime.fromtimestamp(end, zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for name in chosen:
        if name in ("today", "week", "month"):
            start_date = midnight
            if name == "week":
                start_date -= timedelta(days=local.weekday())
            elif name == "month":
                start_date = midnight.replace(day=1)
            start = start_date.timestamp()
            kind = "calendar_to_date"
        else:
            match = re.fullmatch(r"([1-9][0-9]{0,4})(h|d)", name)
            if not match:
                raise ValueError("window must be Nh, Nd, today, week or month")
            start = end - int(match[1]) * (3600 if match[2] == "h" else 86400)
            kind = "rolling"
        rows.append({"name": name, "kind": kind, "start": start, "end": end})
    if since:
        rows.append({"name": "custom", "kind": "custom", "start": _stamp(since, end), "end": end})
    if len(rows) > 12:
        raise ValueError("too many windows")
    for row in rows:
        span = row["end"] - row["start"]
        # Empty calendar-to-date is valid exactly at a calendar boundary.
        if not math.isfinite(span) or span < 0 or span > 365 * 86400:
            raise ValueError("window must be within 365 elapsed days")
        if span == 0 and row["kind"] != "calendar_to_date":
            raise ValueError("custom window must have positive length")
        row.update(since=_iso(row["start"], zone), until=_iso(end, zone))
    return rows


def _usage(rows: list[dict[str, Any]]) -> dict[str, int] | None:
    return {field: sum(row[field] for row in rows) for field in TOKEN_FIELDS} if rows else None


def _group(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    context_detail: bool = False,
) -> list[dict[str, Any]]:
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        if context_detail:
            key += (tuple(sorted(row["context_status"].items())),)
        groups[key].append(row)
    result = []
    for key, members in groups.items():
        result.append(
            {
                **dict(zip(fields, key)),
                **(_usage(members) or {}),
                "first_observed_at": min(row["observed_at"] for row in members),
                "last_observed_at": max(row["observed_at"] for row in members),
            }
        )
        if context_detail:
            result[-1]["context_status"] = members[0]["context_status"]
            result[-1]["context_sources"] = {
                dimension: sorted(
                    {source for row in members for source in row["context_sources"][dimension]}
                )
                for dimension in members[0]["context_sources"]
            }
    return sorted(
        result, key=lambda row: (-row["total_tokens"], str(tuple(row.get(f) for f in fields)))
    )


def _native_interval(snapshots: list[dict[str, Any]], window: dict[str, Any]) -> dict[str, Any]:
    inside = [s for s in snapshots if window["start"] <= s["captured_at"] < window["end"]]
    result: dict[str, Any] = {
        "snapshot_count": len(inside),
        "scope": "account_shared_not_selected_tasks",
        "status": "insufficient_snapshots",
        "comparison": None,
        "observed_since": None,
        "observed_until": None,
    }
    if len(inside) >= 2:
        before, after = inside[0], inside[-1]
        comparison = compare_snapshots(before, after)
        # Endpoint equality alone does not prove a continuous account/reset
        # window: a plan/account could have changed and then changed back.
        discontinuity = any(
            row["status"] == "not_comparable"
            for left, right in zip(inside, inside[1:])
            for row in compare_snapshots(left, right)["windows"]
        )
        if discontinuity:
            for row in comparison["windows"]:
                row["used_percentage_points"] = None
                row["status"] = "not_comparable"
                row["issues"] = sorted(set(row["issues"] + ["intermediate_snapshot_discontinuity"]))
        result.update(
            status="observed_subinterval_only",
            observed_since=_iso(before["captured_at"]),
            observed_until=_iso(after["captured_at"]),
            comparison=comparison,
        )
    return result


def build_report(
    *,
    sessions: Path | None = None,
    directory: Path | None = None,
    windows: list[str] | None = None,
    timezone_name: str = "UTC",
    since: str | None = None,
    until: str | None = None,
    thread_ids: list[str] | None = None,
    limit: int = 200,
    detail_limit: int = 200,
    now: float | None = None,
) -> dict[str, Any]:
    """Capture once, deduplicate once, then filter exact request timestamps.

    Task filters are exact identities, not tree expansion. Public output uses
    hashes; it contains neither prompt-derived names nor transcript paths.
    """
    captured = time.time() if now is None else now
    if type(detail_limit) is not int or not 1 <= detail_limit <= 2000:
        raise ValueError("detail limit must be between 1 and 2000")
    selected = _selected_threads(thread_ids)
    ranges = resolve_windows(
        windows,
        timezone_name=timezone_name,
        since=since,
        until=until,
        now=captured,
    )
    earliest = min(row["start"] for row in ranges)
    end = ranges[0]["end"]
    # Survey requires a positive interval, including at an empty calendar start.
    survey = survey_transcripts(
        sessions,
        since=min(earliest, end - 0.000001),
        now=end,
        limit=limit,
        include_requests=True,
    )
    audit = survey["audit"]
    observations = [
        row
        for row in audit["request_observations"]
        if not selected or row["thread_hash"] in selected
    ]
    excluded = sum(row["unique_responses"] for row in observations if row["observed_at"] is None)
    observations = [row for row in observations if row["observed_at"] is not None]
    # Loading local meter history is read-only and does not create the store.
    saved = load_snapshots(directory, limit=1000) if directory is not None else []
    snapshots = sorted(
        (
            s
            for s in saved
            if isinstance(s.get("captured_at"), (int, float))
            and math.isfinite(s["captured_at"])
            and s["captured_at"] <= end
        ),
        key=lambda s: (s["captured_at"], s.get("id", 0)),
    )
    latest = snapshots[-1] if snapshots else None
    period_rows = []
    for period in ranges:
        rows = [
            row for row in observations if period["start"] <= row["observed_at"] < period["end"]
        ]
        context_fields = (
            "thread_hash",
            "model",
            "role",
            "reasoning_effort",
            "service_tier",
            "fast_mode",
            "plan_type",
        )
        contexts = _group(rows, context_fields, context_detail=True)
        turns = _group(rows, ("thread_hash", "turn_hash"))
        turns.sort(
            key=lambda row: (-row["last_observed_at"], row["thread_hash"], row["turn_hash"] or "")
        )
        by_turn: defaultdict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_turn[row["thread_hash"], row["turn_hash"]].append(row)
        for turn in turns[:detail_limit]:
            turn["contexts"] = _group(
                by_turn[turn["thread_hash"], turn["turn_hash"]],
                context_fields,
                context_detail=True,
            )
        scenario = credit_scenarios(
            contexts, as_of=datetime.fromtimestamp(captured, timezone.utc).date()
        )
        # Keep the single dated reference at report level, not copied per window.
        scenario.pop("reference")
        scenario.pop("rows")
        period_rows.append(
            {
                **period,
                "usage": _usage(rows),
                "status": "observed_only" if rows else "no_observations",
                "tasks": _group(rows, ("thread_hash", "role")),
                "contexts": contexts[:detail_limit],
                "context_detail_count": len(contexts),
                "context_details_truncated": len(contexts) > detail_limit,
                "turns": turns[:detail_limit],
                "turn_detail_count": len(turns),
                "turn_details_truncated": len(turns) > detail_limit,
                "metadata_coverage": {
                    field: dict(
                        sorted(
                            {
                                status: sum(
                                    r["unique_responses"]
                                    for r in rows
                                    if r["context_status"][field] == status
                                )
                                for status in {r["context_status"][field] for r in rows}
                            }.items()
                        )
                    )
                    for field in (
                        "model",
                        "reasoning_effort",
                        "service_tier",
                        "fast_mode",
                        "plan_type",
                    )
                },
                "credit_scenarios": scenario,
                "native_quota": _native_interval(snapshots, period),
            }
        )
    observed_hashes = {row["thread_hash"] for row in observations}
    return {
        "schema_version": 1,
        "generated_at": _iso(captured),
        "timezone": timezone_name,
        "scope": {
            "kind": "selected_tasks" if selected else "all_observed_tasks",
            "thread_hashes": sorted(selected),
            "selected_tasks_without_observations": sorted(selected - observed_hashes),
            "includes_descendants_automatically": False,
        },
        "coverage": {
            **survey["coverage"],
            "ambiguous_time_requests_excluded": excluded,
            "selection": survey["selection"],
            "detail_limit": detail_limit,
            "native_history_limit_reached": len(saved) == 1000,
        },
        "pricing_reference": pricing_context(
            as_of=datetime.fromtimestamp(captured, timezone.utc).date()
        ),
        "native_latest": (
            {
                "captured_at": latest["captured_at"],
                "age_at_report_end_seconds": end - latest["captured_at"],
                "source_status": latest["source_status"],
                "subscription": latest.get("subscription"),
                "limits": latest["limits"],
                "ordinary_usage_allowed": latest.get("ordinary_usage_allowed"),
            }
            if latest
            else None
        ),
        "windows": period_rows,
        "limitations": [
            "Local observed requests only, not account-wide or billing-complete usage.",
            "Windows use [since, until); overlapping windows must not be added.",
            "Requests belong to their recorded usage timestamp, not a prorated execution duration.",
            "Missing or conflicting request times are excluded with visible coverage diagnostics.",
            "Task and turn IDs are hashed. No prompts, titles or transcript content are exported.",
            "Input includes cached input; output includes reasoning. Do not double-count subsets.",
            "Unknown Fast, effort and plans are not backfilled from current settings.",
            "Native quota is saved account data; observed subintervals are not entire windows.",
            "Standard/Fast credits are counterfactuals, not actual charges or quota percentages.",
            "No ledger, hook, task state, account setting, network or quota reset is changed.",
        ],
    }


def write_report(path: Path, rendered: str) -> None:
    """Create a private output, refusing overwrite, symlink targets and broad writes."""
    raw = rendered.encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds 16 MiB; narrow scope or lower detail limit")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("report output must not traverse symlinks")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)


def render_report(report: dict[str, Any], format_name: str = "markdown") -> str:
    from .report_render import render_html, render_markdown

    if format_name == "json":
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if format_name == "html":
        return render_html(report)
    if format_name == "markdown":
        return render_markdown(report)
    raise ValueError("unknown report format")
