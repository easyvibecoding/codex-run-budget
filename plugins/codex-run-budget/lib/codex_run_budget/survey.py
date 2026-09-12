"""Bounded discovery for read-only recent-task telemetry; never opens the ledger."""

from __future__ import annotations

import heapq
import json
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import audit_transcripts
from .report_i18n import ReportText
from .transcript import MAX_TRANSCRIPT_BYTES
from .util import stable_hash

MAX_SURVEY_BYTES = 4 * 1024 * 1024 * 1024
MAX_DISCOVERY_ENTRIES = 100_000
MAX_SURVEY_FILES = 1000


def _observation_text(locale: str) -> ReportText:
    return ReportText(locale, domain="observations")


def _human(value: Any, text: ReportText) -> str:
    if value is None:
        return "unknown" if text.locale == "en" else text("unknown")
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return text.number(value)
    return str(value)


def _matches_task(path: Path, hashes: set[str]) -> bool:
    match = re.search(r"-([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl$", path.name)
    if match:
        return stable_hash(match[1].lower()) in hashes
    # Alternate filenames may require a bounded metadata header, never the body.
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            row = json.loads(source.readline(128 * 1024))
        identity = row.get("payload", {}).get("id")
        return (
            row.get("type") == "session_meta"
            and isinstance(identity, str)
            and stable_hash(identity) in hashes
        )
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return False


def sessions_dir() -> Path:
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    return root / "sessions"


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def survey_transcripts(
    directory: Path | None = None,
    *,
    days: float = 7,
    limit: int = 200,
    now: float | None = None,
    since: float | None = None,
    include_requests: bool = False,
    thread_hashes: set[str] | None = None,
) -> dict[str, Any]:
    """Select recent regular JSONL pages, then analyze one bounded time window.

    Modification time is only a cheap discovery filter. Audit uses record time,
    and parses older metadata for attribution without charging older requests.
    Every skip and partial cohort is reported; missing coverage is never zero.
    """
    if not math.isfinite(days) or not 0 < days <= 365:
        raise ValueError("days must be positive and no greater than 365")
    if type(limit) is not int or not 1 <= limit <= MAX_SURVEY_FILES:
        raise ValueError("limit must be between 1 and 1000")
    if thread_hashes is not None and (
        not thread_hashes
        or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in thread_hashes)
    ):
        raise ValueError("invalid exact Task filter")
    until = time.time() if now is None else now
    if not math.isfinite(until):
        raise ValueError("invalid survey timestamp")
    since = until - days * 86400 if since is None else since
    if not math.isfinite(since) or not 0 < until - since <= 365 * 86400:
        raise ValueError("invalid survey interval")
    root = (directory if directory is not None else sessions_dir()).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("survey requires an existing transcript directory")
    candidates: list[tuple[float, str, int, Path]] = []
    counts: Counter = Counter()

    stopped = False
    pending = [root]
    while pending and not stopped:
        current = pending.pop()
        try:
            if current.is_symlink():
                counts["non_regular_files"] += 1
                continue
            with os.scandir(current) as entries:
                for item in entries:
                    counts["discovered_entries"] += 1
                    if counts["discovered_entries"] > MAX_DISCOVERY_ENTRIES:
                        counts["discovery_limit_reached"] = 1
                        stopped = True
                        break
                    try:
                        if item.is_symlink():
                            counts["non_regular_files"] += 1
                            continue
                        if item.is_dir(follow_symlinks=False):
                            pending.append(Path(item.path))
                            continue
                        if not item.name.endswith(".jsonl"):
                            continue
                        if not item.is_file(follow_symlinks=False):
                            counts["non_regular_files"] += 1
                            continue
                        stat = item.stat(follow_symlinks=False)
                    except OSError:
                        counts["unreadable_files"] += 1
                        continue
                    if stat.st_mtime < since:
                        counts["older_files"] += 1
                        continue
                    if stat.st_mtime > until:
                        counts["future_mtime_files"] += 1
                    if thread_hashes is not None and not _matches_task(
                        Path(item.path), thread_hashes
                    ):
                        counts["outside_task_scope"] += 1
                        continue
                    counts["matching_files"] += 1
                    if stat.st_size > MAX_TRANSCRIPT_BYTES:
                        counts["oversized_files"] += 1
                        continue
                    path = Path(item.path)
                    entry = (stat.st_mtime, str(path), stat.st_size, path)
                    if len(candidates) < limit:
                        heapq.heappush(candidates, entry)
                    else:
                        heapq.heappushpop(candidates, entry)
                        counts["file_limit_skips"] += 1
        except OSError:
            counts["unreadable_directories"] += 1
    selected = []
    total_bytes = 0
    for _modified, _name, size, path in sorted(candidates, reverse=True):
        if total_bytes + size > MAX_SURVEY_BYTES:
            counts["byte_limit_skips"] += 1
            continue
        selected.append(path)
        total_bytes += size
    limited = any(
        counts[key]
        for key in (
            "unreadable_directories",
            "unreadable_files",
            "oversized_files",
            "discovery_limit_reached",
            "file_limit_skips",
            "byte_limit_skips",
        )
    )
    audit = audit_transcripts(selected, since=since, until=until, include_requests=include_requests)
    evidence_issues = _evidence_issues(audit)
    evidence_available = _has_evidence(audit)
    return {
        "schema_version": 1,
        "coverage": {
            "selection_limited": limited,
            "evidence_limited": bool(evidence_issues) or not evidence_available,
            "evidence_available": evidence_available,
            "evidence_issues": evidence_issues,
            "observed_only": True,
        },
        "selection": {
            "directory_hash": stable_hash(str(root.resolve())),
            "since": _iso(since),
            "until": _iso(until),
            "selected_files": len(selected),
            "selected_snapshot_bytes": total_bytes,
            "file_limit": limit,
            "byte_limit": MAX_SURVEY_BYTES,
            "coverage_limited": limited,
            "diagnostics": dict(counts),
        },
        "audit": audit,
        "limitations": [
            "Recent local transcript pages only; this is not the account usage meter.",
            "Discovery uses file modification time; analysis uses record timestamps.",
            "Active files are read as bounded snapshots and may have unfinished work.",
            "File or byte limits and skipped records make the observed cohort partial.",
            "No budget, wait setting, hook trust, or task state is changed.",
        ],
    }


def _evidence_issues(audit: dict[str, Any]) -> dict[str, int]:
    words = (
        "invalid",
        "conflict",
        "skip",
        "limit",
        "missing",
        "unmatched",
        "unknown",
        "incomplete",
        "snapshot_changed",
        "unreadable",
        "unidentified",
        "oversized",
        "ambiguous",
        "not_regular",
        "snapshot_cap",
        "unattributed",
    )
    diagnostics = dict(audit.get("diagnostics", {}))
    for key, value in audit.get("lifecycle", {}).get("diagnostics", {}).items():
        name = key if key.startswith("lifecycle_") else "lifecycle_" + key
        diagnostics[name] = max(diagnostics.get(name, 0), value)
    return {
        key: value
        for key, value in diagnostics.items()
        if value and any(word in key for word in words)
    }


def _has_evidence(audit: dict[str, Any]) -> bool:
    lifecycle = audit.get("lifecycle", {}).get("summary", {})
    return bool(
        audit.get("request_usage")
        or audit.get("tools")
        or lifecycle.get("turns")
        or lifecycle.get("compactions")
        or lifecycle.get("unattributed_compactions")
    )


def _lifecycle_lines(
    lifecycle: dict[str, Any], *, details: bool, text: ReportText
) -> list[str]:
    summary = lifecycle.get("summary", {})
    if not summary.get("turns"):
        lines = [text("lifecycle_no_records")]
        if summary.get("compactions") or summary.get("unattributed_compactions"):
            lines.append(
                text(
                    "lifecycle_compactions",
                    compactions=_human(summary.get("compactions", 0), text),
                    unattributed=_human(summary.get("unattributed_compactions", 0), text),
                )
            )
        return lines
    lines = [
        text(
            "lifecycle_summary",
            observed=f"observed {_human(summary.get('turns', 0), text)}",
            completed=f"completed {_human(summary.get('completed', 0), text)}",
            aborted=f"aborted {_human(summary.get('aborted', 0), text)}",
            no_terminal=(
                f"no terminal observed {_human(summary.get('no_terminal_observed', 0), text)}"
            ),
            conflicted=f"conflicted {_human(summary.get('conflicted', 0), text)}",
        ),
        text(
            "lifecycle_later",
            aborted=(
                f"after aborted {_human(summary.get('aborted_with_later_turn', 0), text)}"
            ),
            no_terminal=(
                f"after no terminal {_human(summary.get('no_terminal_with_later_turn', 0), text)}"
            ),
            compactions=_human(summary.get("compactions", 0), text),
            unattributed=_human(summary.get("unattributed_compactions", 0), text),
        ),
        text("lifecycle_missing"),
    ]
    if not details:
        return lines
    rows = lifecycle.get("turns", [])
    priority = {"conflicted": 0, "no_terminal_observed": 1, "aborted": 2, "completed": 3}
    ranked = sorted(
        rows,
        key=lambda row: (
            priority.get(row.get("state"), 4),
            -row.get("compactions", 0),
            -(row.get("started_at") or row.get("ended_at") or 0),
            row["thread_hash"],
            row["turn_hash"],
        ),
    )[:20]
    lines.extend(
        [
            text(
                "lifecycle_rows",
                shown=_human(len(ranked), text),
                total=_human(len(rows), text),
            ),
            text("lifecycle_columns"),
        ]
    )
    for row in ranked:
        duration = row.get("duration_ms")
        duration_text = (
            text(
                "lifecycle_duration",
                value=text.number(duration / 1000, 1),
                source=row.get("duration_source") or "unknown",
            )
            if duration is not None
            else ("unknown" if text.locale == "en" else text("unknown"))
        )
        start = (
            "before window"
            if row.get("started_before_window")
            else "observed"
            if row.get("start_observed")
            else "missing"
        )
        later = "observed" if row.get("later_turn_observed") else "not observed"
        lines.append(
            f"{row['thread_hash'][:12]}/{row['turn_hash'][:12]} | {row['state']} | "
            f"{duration_text} | {row.get('compactions', 0)} | {start} | {later}"
        )
    lines.append(text("lifecycle_duration_note"))
    return lines


def survey_summary(
    report: dict[str, Any], *, lifecycle_details: bool = False, locale: str = "en"
) -> str:
    """Compact default output; full per-thread evidence remains available as JSON."""
    text = _observation_text(locale)
    selection, audit = report["selection"], report["audit"]
    threads = audit.get("threads", [])
    roles = Counter(row.get("role") or "unknown" for row in threads)
    usage = audit.get("request_usage")
    waits = audit.get("waits", [])
    tools = audit.get("tools", [])
    lines = [
        text("survey_title"),
        text("survey_window", since=selection["since"], until=selection["until"]),
        text(
            "survey_selected",
            selected=_human(selection["selected_files"], text),
            threads=_human(len(threads), text),
            parent=_human(roles["parent"], text),
            subagent=_human(roles["subagent"], text),
            unknown=_human(roles["unknown"], text),
        ),
        text(
            "survey_discovery",
            value=text(
                "survey_discovery_limited"
                if selection["coverage_limited"]
                else "survey_discovery_ok"
            ),
        ),
        text(
            "survey_evidence",
            value=text(
                "survey_evidence_partial"
                if _evidence_issues(audit)
                else (
                    "survey_evidence_observed"
                    if _has_evidence(audit)
                    else "survey_evidence_unknown"
                )
            ),
        ),
        (
            text(
                "survey_requests",
                requests=_human(usage["unique_responses"], text),
                tokens=_human(usage["total_tokens"], text),
            )
            if usage
            else text("survey_requests_unknown")
        ),
    ]
    if usage:
        lines.append(
            text(
                "survey_input",
                input=_human(usage["input_tokens"], text),
                cached=_human(usage["cached_input_tokens"], text),
                output=_human(usage["output_tokens"], text),
            )
        )
    lines.append(
        text(
            "survey_waits",
            calls=_human(sum(row.get("calls", 0) for row in waits), text),
            timeouts=_human(sum(row.get("timed_out", 0) for row in waits), text),
            event_returns=_human(sum(row.get("event_returns", 0) for row in waits), text),
            unknown=_human(sum(row.get("unknown", 0) for row in waits), text),
            short_timeouts=_human(sum(row.get("short_timeouts", 0) for row in waits), text),
        )
        if waits
        else text("survey_waits_none")
    )
    lines.append(
        text(
            "survey_repeats",
            unchanged=_human(
                sum(row.get("unchanged_result_repeats", 0) for row in tools), text
            ),
            changed=_human(sum(row.get("changed_result_repeats", 0) for row in tools), text),
            unknown=_human(sum(row.get("unknown_result_repeats", 0) for row in tools), text),
        )
        if tools
        else text("survey_repeats_none")
    )
    lines.extend(
        _lifecycle_lines(
            audit.get("lifecycle", {}), details=lifecycle_details, text=text
        )
    )
    diagnostics = _evidence_issues(audit)
    if diagnostics:
        lines.append(
            text(
                "survey_diagnostics",
                values=", ".join(
                    f"{k}={_human(v, text)}" for k, v in sorted(diagnostics.items())
                ),
            )
        )
    lines.extend(
        [
            text("survey_event_note"),
            text("survey_usage_note"),
        ]
    )
    return "\n".join(lines)
