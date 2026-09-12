"""Native account quota observations, separate from the enforcement ledger.

Only allowlisted numeric usage and hashed identities cross the storage seam.
Quota percentages, local tokens, and backend-estimated credits remain distinct.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .audit import KNOWN_MODELS
from .meter_plan import normalize_subscription, plan_type
from .meter_policy import credit_scenarios, pricing_context
from .report_i18n import ReportText
from .survey import survey_transcripts
from .util import stable_hash

MAX_SNAPSHOTS = 10_000
MAX_SNAPSHOT_BYTES = 1024 * 1024
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. /:+-]{0,127}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_REACHED_TYPES = (
    "rate_limit_reached",
    "workspace_owner_credits_depleted",
    "workspace_member_credits_depleted",
    "workspace_owner_usage_limit_reached",
    "workspace_member_usage_limit_reached",
)
_TOKEN_FIELDS = {
    "inputTokens": "input_tokens",
    "cachedInputTokens": "cached_input_tokens",
    "netNewInputTokens": "net_new_input_tokens",
    "outputTokens": "output_tokens",
    "totalTokens": "total_tokens",
}


# Issue values are part of the structured report contract.  A translated
# explanation is only an adjacent human hint; the original code remains in
# every rendered summary so consumers can still match it deterministically.
_ISSUE_KEYS = {
    "account_identity_unavailable": "issue_account_identity_unavailable",
    "account_changed": "issue_account_changed",
    "subscription_conflicted": "issue_subscription_conflicted",
    "billing_route_changed": "issue_billing_route_changed",
    "subscription_changed": "issue_subscription_changed",
    "overlapping_or_unordered_captures": "issue_overlapping_or_unordered_captures",
    "window_latest_unavailable": "issue_window_latest_unavailable",
    "window_baseline_unavailable": "issue_window_baseline_unavailable",
    "plan_unavailable": "issue_plan_unavailable",
    "plan_changed": "issue_plan_changed",
    "quota_alias_changed": "issue_quota_alias_changed",
    "window_identity_unavailable": "issue_window_identity_unavailable",
    "reset_or_window_changed": "issue_reset_or_window_changed",
    "reset_boundary_crossed": "issue_reset_boundary_crossed",
    "percentage_unavailable": "issue_percentage_unavailable",
    "quota_decreased_or_corrected": "issue_quota_decreased_or_corrected",
}


def _observation_text(locale: str) -> ReportText:
    return ReportText(locale, domain="observations")


def _human(value: Any, text: ReportText) -> str:
    """Format a display value without changing structured/status values."""
    if value is None:
        # Keep the historical lowercase English rendering byte-compatible;
        # translated catalogs can use their locale's ordinary unknown label.
        return "unknown" if text.locale == "en" else text("unknown")
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return text.number(value)
    return str(value)


def _issue(code: Any, text: ReportText) -> str:
    """Keep an issue code and append a fixed translated explanation when known."""
    if not isinstance(code, str):
        return _human(code, text)
    key = _ISSUE_KEYS.get(code)
    if not key or text.locale == "en":
        return code
    try:
        return f"{code} ({text(key)})"
    except KeyError:
        # A newly introduced code is still useful and must not disappear just
        # because its catalog has not been extended yet.
        return code


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if (
            not math.isfinite(value)
            or not 0 <= value <= 2**63 - 1
            or (integer and int(value) != value)
        ):
            return None
    except (OverflowError, ValueError):
        return None
    return int(value) if integer else value


def _label(value: Any) -> str | None:
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else None


def _quota_label(value: Any) -> str | None:
    if not _label(value):
        return None
    public_labels = {"codex", "codex_bengalfox", "spark", "legacy", "Codex", "Codex-Spark"}
    return value if value in public_labels else "hash:" + stable_hash(value)


def _model(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value if value in KNOWN_MODELS else "hash:" + stable_hash(value)


def _bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _decimal(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        number = Decimal(value)
        return value if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def _window(raw: Any, slot: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used = _number(raw.get("usedPercent"))
    duration = _number(raw.get("windowDurationMins"), integer=True)
    reset = _number(raw.get("resetsAt"), integer=True)
    return {
        "slot": slot,
        "used_percent": used,
        "remaining_percent": max(0, min(100, 100 - used)) if used is not None else None,
        "duration_minutes": duration if duration else None,
        "resets_at": reset if reset else None,
    }


def _official_usage(item: dict[str, Any]) -> dict[str, Any]:
    tid = item.get("thread_id")
    response = item.get("response")
    raw = response.get("threadUsage") if isinstance(response, dict) else None
    result: dict[str, Any] = {
        "thread_hash": stable_hash(tid) if isinstance(tid, str) and tid else None,
        "status": "error" if item.get("error") else "unavailable",
        "estimated_credits_micros": None,
        "groups": [],
    }
    if not isinstance(raw, dict):
        return result
    # Never associate a different backend thread's billing with the requested one.
    if raw.get("threadId") != tid:
        result["status"] = "identity_conflict"
        return result
    result["status"] = "backend_estimate"
    result["estimated_credits_micros"] = _number(
        raw.get("estimatedUsageCreditsMicros"), integer=True
    )
    groups = raw.get("groups")
    if not isinstance(groups, list) or len(groups) > 512:
        result["status"] = "invalid_groups"
        return result
    for group in groups:
        if not isinstance(group, dict):
            result["status"] = "partial_backend_estimate"
            continue
        tokens = {
            dest: _number(group.get(src), integer=True) for src, dest in _TOKEN_FIELDS.items()
        }
        credits = _number(group.get("estimatedUsageCreditsMicros"), integer=True)
        total = tokens["total_tokens"]
        input_tokens, output_tokens = tokens["input_tokens"], tokens["output_tokens"]
        conflicted = (
            total is not None
            and input_tokens is not None
            and output_tokens is not None
            and total != input_tokens + output_tokens
        ) or (
            input_tokens is not None
            and tokens["cached_input_tokens"] is not None
            and tokens["net_new_input_tokens"] is not None
            and tokens["cached_input_tokens"] + tokens["net_new_input_tokens"] != input_tokens
        ) or any(
            input_tokens is not None and tokens[field] is not None and tokens[field] > input_tokens
            for field in ("cached_input_tokens", "net_new_input_tokens")
        )
        result["groups"].append(
            {
                "model": _model(group.get("model")),
                "reasoning_effort": group.get("reasoningEffort")
                if group.get("reasoningEffort")
                in (
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                    "ultra",
                )
                else None,
                "speed": group.get("speed")
                if group.get("speed")
                in ("normal", "standard", "default", "fast", "priority", "flex")
                else None,
                "fast_mode": True
                if group.get("speed") == "fast"
                else False
                if group.get("speed") in ("normal", "standard")
                else None,
                "configuration_source": "backend_usage_group",
                **tokens,
                "token_status": "conflicted" if conflicted else "reported",
                "estimated_credits_micros": credits,
                # micros / tokens equals credits / million tokens. Not quota percent.
                "estimated_credits_per_million_tokens": credits / total
                if credits is not None and total and not conflicted
                else None,
                "quota_percentage_points": None,
            }
        )
    return result


def normalize_snapshot(sources: dict[str, Any]) -> dict[str, Any]:
    """Discard account IDs, reset-credit IDs, banners, errors and arbitrary text."""
    started = _number(sources.get("started_at"))
    finished = _number(sources.get("finished_at"))
    if started is None or finished is None or finished < started:
        raise ValueError("invalid capture timestamps")
    raw = sources.get("rate_limits")
    raw = raw if isinstance(raw, dict) else {}
    account = raw.get("accountId")
    by_id = raw.get("rateLimitsByLimitId")
    diagnostics = []
    if isinstance(by_id, dict):
        buckets = list(by_id.items())[:128]
        if len(by_id) > 128:
            diagnostics.append("bucket_limit_reached")
    else:
        legacy = raw.get("rateLimits")
        buckets = [(legacy.get("limitId") or "legacy", legacy)] if isinstance(legacy, dict) else []
    limits = []
    for key, bucket in buckets:
        if not isinstance(bucket, dict) or not _label(key):
            diagnostics.append("invalid_bucket")
            continue
        bucket_id = bucket.get("limitId")
        if bucket_id is not None and bucket_id != key:
            diagnostics.append("bucket_identity_conflict")
            continue
        credits = bucket.get("credits")
        credits = credits if isinstance(credits, dict) else {}
        individual = bucket.get("individualLimit")
        individual = individual if isinstance(individual, dict) else {}
        limits.append(
            {
                "limit_id": _quota_label(key),
                "label": _quota_label(bucket.get("limitName")),
                "normal_model": _model(bucket.get("normalModelSlug")),
                "plan_type": plan_type(bucket.get("planType")),
                "windows": [
                    window
                    for slot in ("primary", "secondary")
                    if (window := _window(bucket.get(slot), slot)) is not None
                ],
                "credits": {
                    "has_credits": _bool(credits.get("hasCredits")),
                    "unlimited": _bool(credits.get("unlimited")),
                    "balance": _decimal(credits.get("balance")),
                },
                "individual_limit": {
                    "limit": _decimal(individual.get("limit")),
                    "used": _decimal(individual.get("used")),
                    "remaining_percent": _number(individual.get("remainingPercent")),
                    "resets_at": _number(individual.get("resetsAt"), integer=True),
                }
                if individual
                else None,
                "spend_control_reached": _bool(bucket.get("spendControlReached")),
                "rate_limit_reached_type": bucket.get("rateLimitReachedType")
                if bucket.get("rateLimitReachedType") in _REACHED_TYPES else None,
            }
        )
    usage = sources.get("account_usage")
    usage = usage if isinstance(usage, dict) else {}
    summary = usage.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    daily = usage.get("dailyUsageBuckets")
    daily_rows = None
    if isinstance(daily, list):
        daily_rows = []
        if len(daily) > 400:
            diagnostics.append("daily_bucket_limit_reached")
        for row in daily[-400:]:
            if not isinstance(row, dict):
                continue
            date = row.get("startDate")
            tokens = _number(row.get("tokens"), integer=True)
            if isinstance(date, str) and _DATE.fullmatch(date) and tokens is not None:
                daily_rows.append({"date": date, "tokens": tokens})
    errors = sources.get("errors")
    errors = errors if isinstance(errors, list) else []
    for error in errors[:32]:
        if isinstance(error, dict):
            source = error.get("source")
            code = error.get("code")
            if source in (
                "initialize",
                "rate_limits",
                "account_usage",
                "account",
                "thread_usage",
                "transport",
            ) and code in (
                "timeout",
                "process_exit",
                "eof",
                "unsupported_rpc",
                "rpc_error",
                "malformed_output",
                "oversized_output",
                "missing_response",
                "transport_error",
                "spawn_error",
                "not_attempted",
            ):
                diagnostics.append(f"{source}:{code}")
    thread_rows = sources.get("thread_usage")
    thread_rows = thread_rows if isinstance(thread_rows, list) else []
    if len(thread_rows) > 8:
        diagnostics.append("thread_limit_reached")
    return {
        "schema_version": 2,
        "capture_started_at": started,
        "captured_at": finished,
        "account_hash": stable_hash(account) if isinstance(account, str) and account else None,
        "source_status": "available" if (
            _bool(raw.get("ordinaryUsageAllowed")) is not None
            or any(
                any(w["used_percent"] is not None for w in b["windows"])
                or any(value is not None for value in b["credits"].values())
                or b["rate_limit_reached_type"] is not None
                or b["spend_control_reached"] is not None
                or (b["individual_limit"] is not None
                    and any(value is not None for value in b["individual_limit"].values()))
                for b in limits
            )
        ) else "unavailable",
        "ordinary_usage_allowed": _bool(raw.get("ordinaryUsageAllowed")),
        "limits": limits,
        "subscription": normalize_subscription(sources.get("account_response"), limits),
        "account_usage": {
            "lifetime_tokens": _number(summary.get("lifetimeTokens"), integer=True),
            "daily_tokens": daily_rows,
        },
        "official_thread_usage": [
            _official_usage(row) for row in thread_rows[:8] if isinstance(row, dict)
        ],
        "diagnostics": sorted(set(diagnostics)),
    }


def _db_path(directory: Path) -> Path:
    root = Path(os.path.abspath(directory.expanduser()))
    aliases = {"/var": "/private/var", "/tmp": "/private/tmp", "/etc": "/private/etc"}
    for path in (*reversed(root.parents), root):
        if path.is_symlink() and aliases.get(str(path)) != str(path.resolve()):
            raise ValueError("meter storage must not follow user symlinks")
    target = root / "meter.sqlite3"
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(target) + suffix)
        if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
            raise ValueError("invalid meter storage file")
    return target


def record_snapshot(directory: Path, sources: dict[str, Any]) -> dict[str, Any]:
    """Append one normalized snapshot. Never opens or mutates the budget ledger."""
    snapshot = normalize_snapshot(sources)
    payload = json.dumps(snapshot, separators=(",", ":"), allow_nan=False)
    if len(payload.encode()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot is too large")
    path = _db_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            if connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("unrecognized meter database")
            connection.execute(
                "CREATE TABLE snapshots (id INTEGER PRIMARY KEY, captured_at REAL NOT NULL, "
                "payload TEXT NOT NULL)"
            )
            connection.execute("PRAGMA user_version=1")
        elif version != 1:
            raise ValueError("unsupported meter database version")
        if connection.execute("SELECT count(*) FROM snapshots").fetchone()[0] >= MAX_SNAPSHOTS:
            raise ValueError("meter storage is full; preserve or archive its history")
        cursor = connection.execute(
            "INSERT INTO snapshots(captured_at,payload) VALUES (?,?)",
            (snapshot["captured_at"], payload),
        )
        connection.commit()
        return {"id": cursor.lastrowid, **snapshot}
    finally:
        connection.close()


def load_snapshots(directory: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Read newest observations without creating a directory or database."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid history limit")
    path = _db_path(directory)
    if not path.exists():
        return []
    connection = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True, timeout=5)
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unsupported meter database version")
        rows = connection.execute(
            "SELECT id, substr(payload,1,?) FROM snapshots ORDER BY id DESC LIMIT ?",
            (MAX_SNAPSHOT_BYTES + 1, limit),
        )
        result = []
        for number, payload in rows:
            if len(payload.encode()) > MAX_SNAPSHOT_BYTES:
                raise ValueError("stored snapshot is too large")
            value = json.loads(payload)
            if not isinstance(value, dict) or value.get("schema_version") not in (1, 2):
                raise ValueError("invalid stored snapshot")
            result.append({**value, "id": number})
        return result
    finally:
        connection.close()


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Percentage-point deltas only within one identified account/reset window."""
    reasons = []
    account = before.get("account_hash")
    if not account or not after.get("account_hash"):
        reasons.append("account_identity_unavailable")
    elif account != after["account_hash"]:
        reasons.append("account_changed")
    old_subscription = before.get("subscription") or {}
    new_subscription = after.get("subscription") or {}
    if any(s.get("status") == "conflicted" for s in (old_subscription, new_subscription)):
        reasons.append("subscription_conflicted")
    if old_subscription.get("auth_type") and new_subscription.get("auth_type"):
        if old_subscription["auth_type"] != new_subscription["auth_type"]:
            reasons.append("billing_route_changed")
    if old_subscription.get("plan_type") and new_subscription.get("plan_type"):
        if old_subscription["plan_type"] != new_subscription["plan_type"]:
            reasons.append("subscription_changed")
    start, end = before["captured_at"], after["captured_at"]
    if end <= start or after["capture_started_at"] < start:
        reasons.append("overlapping_or_unordered_captures")
    old = {row["limit_id"]: row for row in before["limits"]}
    rows = []
    current_keys = {(b["limit_id"], w["slot"]) for b in after["limits"] for w in b["windows"]}
    for bucket in before["limits"]:
        for window in bucket["windows"]:
            if (bucket["limit_id"], window["slot"]) not in current_keys:
                rows.append(
                    {
                        "limit_id": bucket["limit_id"],
                        "slot": window["slot"],
                        "duration_minutes": window["duration_minutes"],
                        "used_percentage_points": None,
                        "status": "not_comparable",
                        "issues": ["window_latest_unavailable"],
                    }
                )
    for bucket in after["limits"]:
        prior = old.get(bucket["limit_id"])
        for window in bucket["windows"]:
            issues = list(reasons)
            previous = (
                next((w for w in prior["windows"] if w["slot"] == window["slot"]), None)
                if prior
                else None
            )
            if previous is None:
                issues.append("window_baseline_unavailable")
            elif prior["plan_type"] is None or bucket["plan_type"] is None:
                issues.append("plan_unavailable")
            elif prior["plan_type"] != bucket["plan_type"]:
                issues.append("plan_changed")
            elif prior["normal_model"] != bucket["normal_model"]:
                issues.append("quota_alias_changed")
            else:
                for field in ("duration_minutes", "resets_at"):
                    if previous[field] is None or window[field] is None:
                        issues.append("window_identity_unavailable")
                    elif previous[field] != window[field]:
                        issues.append("reset_or_window_changed")
                if window["resets_at"] is not None and end >= window["resets_at"]:
                    issues.append("reset_boundary_crossed")
                if previous["used_percent"] is None or window["used_percent"] is None:
                    issues.append("percentage_unavailable")
            delta = None
            if not issues:
                delta = window["used_percent"] - previous["used_percent"]
                if delta < 0:
                    issues.append("quota_decreased_or_corrected")
                    delta = None
            rows.append(
                {
                    "limit_id": bucket["limit_id"],
                    "slot": window["slot"],
                    "duration_minutes": window["duration_minutes"],
                    "used_percentage_points": delta,
                    "status": "not_comparable"
                    if issues
                    else ("below_display_resolution" if delta == 0 else "observed_increase"),
                    "issues": sorted(set(issues)),
                }
            )
    return {
        "baseline_id": before.get("id"),
        "latest_id": after.get("id"),
        "since": start,
        "until": end,
        "elapsed_seconds": max(0, end - start),
        "windows": rows,
        "model_quota_attribution": "unavailable",
        "subscription_observations": {
            "before": old_subscription or None,
            "after": new_subscription or None,
            "historical_task_plan_inferred": False,
        },
        "limitations": [
            "Account quota includes concurrent tasks, other devices and potentially delayed usage.",
            "A zero displayed change is below meter resolution, not free token usage.",
            "Local token shares do not allocate account quota "
            "or establish a token-to-percent tariff.",
            "Backend credits are estimates and are not included-quota percentage points.",
        ],
    }


def _format(value: Any) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return (
        "unknown"
        if value is None
        else f"{value:,}"
        if isinstance(value, (float, int))
        else str(value)
    )


def _utc(stamp: Any) -> str:
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "unknown"


def snapshot_summary(snapshot: dict[str, Any], *, locale: str = "en") -> str:
    """Render one native quota snapshot for humans.

    The snapshot itself is deliberately language-neutral JSON.  ``locale`` is
    consumed only here, at the human-output seam; no preference lookup occurs.
    """
    text = _observation_text(locale)
    unknown = "unknown" if text.locale == "en" else text("unknown")
    lines = [text("snapshot_title", time=_utc(snapshot["captured_at"]))]
    if snapshot.get("id") is not None:
        lines.append(text("snapshot_saved", id=_human(snapshot["id"], text)))
    subscription = snapshot.get("subscription") or {}
    lines.append(
        text(
            "snapshot_subscription",
            plan=subscription.get("plan_type") or unknown,
            auth=subscription.get("auth_type") or unknown,
            evidence=subscription.get("status") or "not_recorded",
            unknown=unknown,
        )
    )
    allowed = snapshot.get("ordinary_usage_allowed")
    permission = "allowed" if allowed is True else "not_allowed" if allowed is False else unknown
    lines.append(text("snapshot_permission", permission=permission))
    for bucket in snapshot["limits"]:
        for window in bucket["windows"]:
            lines.append(
                text(
                    "snapshot_window",
                    limit=bucket["limit_id"],
                    duration=_human(window["duration_minutes"], text),
                    plan=bucket.get("plan_type") or unknown,
                    used=_human(window["used_percent"], text),
                    remaining=_human(window["remaining_percent"], text),
                    reset=_utc(window["resets_at"]),
                )
            )
        credits = bucket.get("credits") or {}
        lines.append(
            text(
                "snapshot_controls",
                limit=bucket["limit_id"],
                reached=bucket.get("rate_limit_reached_type") or unknown,
                spend=_human(bucket.get("spend_control_reached"), text),
                has=_human(credits.get("has_credits"), text),
                unlimited=_human(credits.get("unlimited"), text),
                balance=_human(credits.get("balance"), text),
            )
        )
        individual = bucket.get("individual_limit")
        if individual:
            lines.append(
                text(
                    "snapshot_individual",
                    used=_human(individual.get("used"), text),
                    limit=_human(individual.get("limit"), text),
                    remaining=_human(individual.get("remaining_percent"), text),
                    reset=_utc(individual.get("resets_at")),
                )
            )
    if not snapshot["limits"]:
        lines.append(text("snapshot_unavailable"))
    lifetime = snapshot["account_usage"]["lifetime_tokens"]
    lines.append(text("snapshot_lifetime", tokens=_human(lifetime, text)))
    groups_shown = 0
    for thread in snapshot["official_thread_usage"]:
        identity = (thread["thread_hash"] or "unknown")[:12]
        lines.append(text("snapshot_thread", identity=identity, status=thread["status"]))
        for group in thread["groups"]:
            if groups_shown >= 20:
                break
            groups_shown += 1
            lines.append(
                text(
                    "snapshot_group",
                    model=group["model"] or unknown,
                    effort=group["reasoning_effort"] or unknown,
                    speed=group["speed"] or unknown,
                    tokens=_human(group["total_tokens"], text),
                    credits=_human(group["estimated_credits_per_million_tokens"], text),
                )
            )
    lines.append(text("snapshot_credits_note", unknown=unknown))
    lines.append(text("snapshot_permission_note"))
    if snapshot["diagnostics"]:
        lines.append(text("snapshot_diagnostics", values=", ".join(snapshot["diagnostics"])))
    return "\n".join(lines)


def meter_report(
    directory: Path,
    *,
    sessions: Path | None = None,
    limit: int = 200,
    baseline_id: int | None = None,
    thread_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compose quota and offline tokens without deriving model quota allocations.

    Request completion timestamps select the local interval, not billing time.
    With only a baseline there is no interval; do not charge a preceding day to it.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid file limit")
    if baseline_id is not None and (type(baseline_id) is not int or baseline_id < 1):
        raise ValueError("invalid baseline id")
    snapshots = load_snapshots(directory, limit=1000 if baseline_id is not None else 2)
    latest = snapshots[0] if snapshots else None
    baseline = (
        next((row for row in snapshots[1:] if row["id"] == baseline_id), None)
        if baseline_id is not None
        else snapshots[1]
        if len(snapshots) > 1
        else None
    )
    if baseline_id is not None and baseline is None:
        raise ValueError("baseline not available in retained selection")
    selected_threads = _selected_threads(thread_ids)
    report: dict[str, Any] = {
        "schema_version": 2,
        "status": "baseline_needed" if latest is None else "second_snapshot_needed",
        "latest": latest,
        "interval": None,
        "local_usage": None,
        "model_quota_attribution": "unavailable",
        "pricing_context": pricing_context(),
        "selected_thread_hashes": sorted(selected_threads),
    }
    if baseline is None:
        return report
    interval = compare_snapshots(baseline, latest)
    report.update(status="observed", interval=interval)
    duration = interval["until"] - interval["since"]
    if not 0 < duration <= 365 * 86400:
        report["local_usage"] = {"status": "invalid_interval", "models": []}
        return report
    try:
        # audit's lower edge is inclusive. Move one representable instant ahead
        # so a completion at the baseline cannot be charged into two intervals.
        since = math.nextafter(interval["since"], math.inf)
        survey = survey_transcripts(sessions, since=since, limit=limit, now=interval["until"])
    except (OSError, ValueError):
        report["local_usage"] = {"status": "unavailable", "models": []}
        return report
    report["local_usage"] = _local_usage(survey, selected_threads)
    return report


def _selected_threads(thread_ids: list[str] | None) -> set[str]:
    if thread_ids is None:
        return set()
    if not isinstance(thread_ids, (list, tuple)) or len(thread_ids) > 64:
        raise ValueError("invalid task selection")
    hashes = set()
    for value in thread_ids:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value.lower():
            raise ValueError("invalid task UUID")
        hashes.add(stable_hash(value.lower()))
    return hashes


def _local_usage(survey: dict[str, Any], selected_threads: set[str]) -> dict[str, Any]:
    audit = survey["audit"]
    rows = [
        row
        for row in audit.get("request_context_usage", audit.get("model_usage", []))
        if not selected_threads or row.get("thread_hash") in selected_threads
    ]
    usage = audit.get("request_usage")
    if selected_threads:
        selected = [row for row in rows if row.get("unique_responses")]
        usage = (
            {
                field: sum(row.get(field, 0) for row in selected)
                for field in (
                    "unique_responses",
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "uncached_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                    "total_tokens",
                )
            }
            if selected
            else None
        )
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.get("unique_responses"):
            continue
        model = row.get("model") or "unknown"
        target = totals.setdefault(
            model,
            {
                "model": model,
                "unique_responses": 0,
                **{
                    field: 0
                    for field in (
                        "input_tokens",
                        "cached_input_tokens",
                        "cache_write_input_tokens",
                        "uncached_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                        "total_tokens",
                    )
                },
                "quota_percentage_points": None,
                "credits_per_million_tokens": None,
            },
        )
        for field in (
            "unique_responses",
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
        ):
            target[field] += row.get(field, 0)
    total = usage.get("total_tokens", 0) if usage else 0
    for row in totals.values():
        row["observed_token_share_percent"] = 100 * row["total_tokens"] / total if total else None
        row["cached_input_share_percent"] = (
            100 * row["cached_input_tokens"] / row["input_tokens"] if row["input_tokens"] else None
        )
    contexts = [
        row
        for row in audit.get("request_context_usage", [])
        if not selected_threads or row.get("thread_hash") in selected_threads
    ]
    observed_threads = {
        row["thread_hash"]
        for row in rows
        if row.get("unique_responses") and row.get("thread_hash") not in (None, "unknown")
    }
    return {
        "status": "observed_partial" if usage else "unknown",
        "selection": survey["selection"],
        "coverage": survey["coverage"],
        "diagnostics": audit.get("diagnostics", {}),
        "request_usage": usage,
        "models": sorted(totals.values(), key=lambda row: (-row["total_tokens"], row["model"])),
        "tasks": sorted(
            (row for row in rows if row.get("unique_responses")),
            key=lambda row: (-row.get("total_tokens", 0), row["thread_hash"], row["model"]),
        ),
        "task_count": len(observed_threads),
        "request_context_usage": contexts,
        "metadata_coverage": {
            field: {
                "known_requests": sum(
                    row.get("unique_responses", 0)
                    for row in contexts
                    if row.get(field) is not None and row.get(field) != "unknown"
                ),
                "total_requests": sum(row.get("unique_responses", 0) for row in contexts),
            }
            for field in ("model", "reasoning_effort", "service_tier", "fast_mode", "plan_type")
        },
        "selected_thread_hashes": sorted(selected_threads),
        "missing_selected_thread_hashes": sorted(selected_threads - observed_threads),
        "limitations": [
            "Local request completion-time observations, not an account-wide billing ledger.",
            "Input includes cached input; output includes reasoning output. "
            "Do not add subsets twice.",
            "Unknown/conflicting model identity and partial transcript coverage remain unresolved.",
            "Token share percent is not quota percent. Per-model quota is unavailable.",
            "Task selection filters local tokens only; account quota remains account-wide.",
            "Historical Fast/effort/plan require contemporaneous evidence, not current defaults.",
        ],
    }


def meter_tasks(
    *,
    sessions: Path | None = None,
    days: float = 7,
    limit: int = 200,
    thread_ids: list[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Read cross-task historical observations without network or meter DB writes."""
    selected = _selected_threads(thread_ids)
    until = time.time() if now is None else now
    survey = survey_transcripts(sessions, days=days, limit=limit, now=until)
    return {
        "schema_version": 2,
        "status": "local_observation",
        "since": until - days * 86400,
        "until": until,
        "local_usage": _local_usage(survey, selected),
        "pricing_context": pricing_context(),
        "model_quota_attribution": "unavailable",
    }


def tasks_summary(report: dict[str, Any], *, locale: str = "en") -> str:
    text = _observation_text(locale)
    local = report.get("local_usage") or {}
    interval = report.get("interval") or report
    lines = [
        text(
            "tasks_heading",
            count=_human(local.get("task_count", 0), text),
        ),
        text("tasks_window", since=_utc(interval.get("since")), until=_utc(interval.get("until"))),
        text("tasks_columns"),
    ]
    for row in sorted(
        local.get("request_context_usage", []), key=lambda row: -row.get("total_tokens", 0)
    )[:20]:
        values = (
            (row.get("thread_hash") or "unknown")[:12],
            (row.get("turn_hash") or "unknown")[:12],
            row.get("model"),
            row.get("reasoning_effort"),
            row.get("service_tier"),
            row.get("fast_mode"),
            row.get("plan_type"),
            row.get("unique_responses"),
            row.get("total_tokens"),
        )
        lines.append(" | ".join(_human(value, text) for value in values))
    if not local.get("request_context_usage"):
        lines.append(text("tasks_none"))
    if local.get("missing_selected_thread_hashes"):
        lines.append(text("tasks_missing"))
    lines.extend(local.get("limitations", []))
    lines.append(text("tasks_plan_note"))
    lines.append(text("tasks_fast_reference"))
    lines.append(text("tasks_fast_note"))
    return "\n".join(lines)


def meter_estimate(
    *,
    sessions: Path | None = None,
    days: float = 7,
    limit: int = 200,
    thread_ids: list[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Use the offline Task seam; never query native billing or mutate storage."""
    report = meter_tasks(
        sessions=sessions, days=days, limit=limit, thread_ids=thread_ids, now=now
    )
    report["status"] = "counterfactual_credit_scenarios"
    report["credit_scenarios"] = credit_scenarios(
        report["local_usage"]["request_context_usage"]
    )
    return report


def estimate_summary(report: dict[str, Any], *, locale: str = "en") -> str:
    text = _observation_text(locale)
    scenarios = report["credit_scenarios"]
    reference = scenarios["reference"]
    coverage = scenarios["coverage"]
    lines = [
        text("estimate_title"),
        text(
            "estimate_rate",
            verified=reference["verified_on"],
            freshness=reference["freshness"]["status"],
        ),
        text(
            "estimate_coverage",
            priced=_human(coverage["priced_requests"], text),
            excluded=_human(coverage["excluded_requests"], text),
        ),
        text(
            "estimate_scenarios",
            standard=_human(scenarios["standard_scenario_credits"], text),
            fast=_human(scenarios["fast_scenario_credits"], text),
        ),
        text("estimate_columns"),
    ]
    for row in sorted(scenarios["rows"], key=lambda row: -row["requests"])[:20]:
        lines.append(
            text(
                "estimate_row",
                task=(row.get("thread_hash") or "unknown")[:12],
                model=row.get("model") or "unknown",
                effort=row.get("reasoning_effort") or "unknown",
                fast=_human(row.get("observed_fast_mode"), text),
                requests=_human(row["requests"], text),
                standard=_human(row["standard_scenario_credits"], text),
                fast_credits=_human(row["fast_scenario_credits"], text),
                status=row["status"],
            )
        )
    lines.extend(scenarios["limitations"])
    lines.append(text("estimate_rate_source", source=reference["token_rate_source"]))
    return "\n".join(lines)


def report_summary(report: dict[str, Any], *, locale: str = "en") -> str:
    text = _observation_text(locale)
    latest = report["latest"]
    lines = [snapshot_summary(latest, locale=locale)] if latest else [text("report_no_latest")]
    interval = report["interval"]
    if interval is None:
        lines.append(text("report_baseline"))
        return "\n".join(lines)
    lines.append(
        text("report_interval", since=_utc(interval["since"]), until=_utc(interval["until"]))
    )
    for row in interval["windows"]:
        issues = ", ".join(_issue(code, text) for code in row["issues"])
        lines.append(
            text(
                "report_window",
                limit=row["limit_id"],
                duration=_human(row["duration_minutes"], text),
                delta=_human(row["used_percentage_points"], text),
                status=row["status"],
                issues=(" (" + issues + ")") if issues else "",
            )
        )
    local = report["local_usage"] or {}
    lines.append(text("report_local_heading"))
    lines.append(text("report_local_columns"))
    for row in local.get("models", [])[:20]:
        lines.append(
            " | ".join(
                _human(row[field], text)
                for field in (
                    "model",
                    "unique_responses",
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "total_tokens",
                )
            )
            + " | " + ("unknown" if text.locale == "en" else text("unknown"))
        )
    if not local.get("models"):
        lines.append(text("report_no_models"))
    lines.extend(interval["limitations"])
    lines.append(tasks_summary(report, locale=locale))
    return "\n".join(lines)
