"""Bounded discovery for read-only recent-task telemetry; never opens the ledger."""

from __future__ import annotations

import heapq
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import audit_transcripts
from .transcript import MAX_TRANSCRIPT_BYTES
from .util import stable_hash

MAX_SURVEY_BYTES = 4 * 1024 * 1024 * 1024
MAX_DISCOVERY_ENTRIES = 100_000
MAX_SURVEY_FILES = 1000


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
    until = time.time() if now is None else now
    if not math.isfinite(until):
        raise ValueError("invalid survey timestamp")
    since = until - days * 86400
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
    audit = audit_transcripts(selected, since=since, until=until)
    evidence_issues = _evidence_issues(audit)
    evidence_available = bool(audit.get("request_usage") or audit.get("tools"))
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
    )
    return {
        key: value
        for key, value in audit.get("diagnostics", {}).items()
        if value and any(word in key for word in words)
    }


def survey_summary(report: dict[str, Any]) -> str:
    """Compact default output; full per-thread evidence remains available as JSON."""
    selection, audit = report["selection"], report["audit"]
    threads = audit.get("threads", [])
    roles = Counter(row.get("role") or "unknown" for row in threads)
    usage = audit.get("request_usage")
    waits = audit.get("waits", [])
    tools = audit.get("tools", [])
    lines = [
        "Run Budget recent-task survey (read-only)",
        f"Window: {selection['since']} to {selection['until']}",
        f"Selected pages: {selection['selected_files']}; observed threads: {len(threads)} "
        f"(parent {roles['parent']}, subagent {roles['subagent']}, unknown {roles['unknown']})",
        "Discovery coverage: "
        + (
            "limited; inspect selection diagnostics"
            if selection["coverage_limited"]
            else "within discovery limits (not a completeness guarantee)"
        ),
        "Evidence coverage: "
        + (
            "partial or uncertain; inspect diagnostics"
            if _evidence_issues(audit)
            else (
                "observed records only"
                if usage or tools
                else "unknown; no matching usage or tool records"
            )
        ),
        (
            f"Observed requests: {usage['unique_responses']:,}; "
            f"request tokens: {usage['total_tokens']:,} (not billing usage)"
            if usage
            else "Observed request usage: unknown (no valid request records)"
        ),
    ]
    if usage:
        lines.append(
            f"Input: {usage['input_tokens']:,}; cached input: {usage['cached_input_tokens']:,}; "
            f"output: {usage['output_tokens']:,}"
        )
    lines.append(
        "wait_agent: "
        + ", ".join(
            f"{label} {sum(row.get(key, 0) for row in waits):,}"
            for key, label in (
                ("calls", "calls"),
                ("timed_out", "timeouts"),
                ("event_returns", "event returns"),
                ("unknown", "unknown outcomes"),
                ("short_timeouts", "timeouts under 60s"),
            )
        )
        if waits
        else "wait_agent: no matching call records; outcome coverage unknown"
    )
    lines.append(
        "Repeated-result candidates: "
        + ", ".join(
            f"{label} {sum(row.get(key, 0) for row in tools):,}"
            for key, label in (
                ("unchanged_result_repeats", "unchanged"),
                ("changed_result_repeats", "changed"),
                ("unknown_result_repeats", "unknown"),
            )
        )
        if tools
        else "Repeated-result candidates: no matching tool records"
    )
    diagnostics = _evidence_issues(audit)
    if diagnostics:
        lines.append(
            "Data diagnostics: " + ", ".join(f"{k}={v}" for k, v in sorted(diagnostics.items()))
        )
    lines.extend(
        [
            "Event returns do not prove agent completion; repeated results do not prove waste.",
            "Use --json for per-thread/model evidence and all coverage diagnostics.",
        ]
    )
    return "\n".join(lines)
