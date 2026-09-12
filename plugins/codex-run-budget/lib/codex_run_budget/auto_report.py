"""Default-on, user-switchable receipts. Reporting never controls the agent loop."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import sqlite3
import stat
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from .report_i18n import ReportText, resolve_locale
from .task_catalog import task_description
from .transcript import _usage_from_line, request_usage
from .util import stable_hash

SCAN_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10_000
EVENTS = {"UserPromptSubmit", "Stop", "Interrupt", "SessionEnd", "SubagentStop"}


def _pending(key: str, locale="zh-Hant") -> str:
    text = ReportText(locale)
    return (
        f"# {text('title')}\n\n{ text('pending')}\n\n{text('pending_note')}\n\n"
        f"<!-- run-budget-pending:{key} -->\n"
    )


def _footer(directory: Path, key: str, payload: dict[str, Any], locale="zh-Hant") -> dict[str, Any]:
    """Publish a real pending target before asking for one normal-answer link."""
    target = directory / f"{key}.md"
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(_pending(key, locale))
    digest = getattr(__loader__, "runtime_digest", None)
    runner = (
        directory.parent / "runtimes" / (digest + ".pyz")
        if digest else Path(__file__).resolve().parents[2] / "scripts/hook.py"
    )
    command = shlex.join([
        "python3", "-I", str(runner), "--preview", payload["session_id"], payload["turn_id"],
        "--data-dir", str(directory.parent.absolute()),
    ])
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            "Before final, run once: " + command
            + " --output-dir <absolute task-owned writable dir>. "
            "Append its visualize reference unchanged on a final-answer line. "
            "Do not read/analyze the card or load skills for it; no retries. "
            "Skip if disabled or the answer format conflicts."
        ),
    }}


def _directory(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("report root is a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / "auto-reports"
    if target.is_symlink():
        raise ValueError("report directory is a symlink")
    target.mkdir(exist_ok=True, mode=0o700)
    return target


def settings(root: Path) -> dict[str, Any]:
    path = root / "auto-report.json"
    if not path.exists() and not path.is_symlink():
        return {"enabled": True, "threshold_seconds": 0}
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("nonregular auto-report settings")
        raw = stream.read(2049)
    value = json.loads(raw) if len(raw) <= 2048 else None
    if (
        not isinstance(value, dict)
        or type(value.get("enabled")) is not bool
        or type(value.get("threshold_seconds")) not in (int, float)
        or not 0 <= value["threshold_seconds"] <= 86400
    ):
        raise ValueError("invalid auto-report settings")
    return {"enabled": value["enabled"], "threshold_seconds": value["threshold_seconds"]}


def configure(root: Path, *, enabled: bool, threshold_seconds: float = 0) -> dict[str, Any]:
    if (
        type(enabled) is not bool
        or type(threshold_seconds) not in (int, float)
        or not 0 <= threshold_seconds <= 86400
    ):
        raise ValueError("invalid report configuration")
    _directory(root)
    target = root / "auto-report.json"
    if target.is_symlink():
        raise ValueError("settings target is a symlink")
    descriptor, temporary = tempfile.mkstemp(prefix="auto-report-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"enabled": enabled, "threshold_seconds": threshold_seconds}, output)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return settings(root)


def _connect(root: Path) -> sqlite3.Connection:
    directory = _directory(root)
    path = directory / "timing.sqlite3"
    if path.is_symlink():
        raise ValueError("timing store is a symlink")
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass  # Another Task may initialize the shared store simultaneously.
        else:
            os.close(descriptor)
    if path.is_symlink() or not path.is_file():
        raise ValueError("timing store is not a regular file")
    connection = sqlite3.connect(path, timeout=0.4, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS turns ("
            "key TEXT PRIMARY KEY, session_hash TEXT NOT NULL, turn_hash TEXT NOT NULL, "
            "started REAL NOT NULL, monotonic REAL NOT NULL, baseline TEXT NOT NULL, "
            "state TEXT NOT NULL, elapsed REAL, report TEXT)"
        )
    except Exception:
        connection.close()
        raise
    return connection


def _model(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-z0-9][-a-z0-9.]{0,79}", value)
        else None
    )


def _request_thread_counter(payload: dict, task: str, turn: str) -> dict | None:
    """Use the native cumulative counter, never add request and event totals.

    A request record can precede the post-tool token_count event. Its own
    usage is not a thread total; require explicit, consistent native scopes.
    """
    if (payload.get("thread_id") != task or payload.get("turn_id") != turn
            or payload.get("session_id", task) != task
            or payload.get("root_turn_id", turn) != turn):
        return None
    response = payload.get("response_id")
    if not isinstance(response, str) or not 0 < len(response) <= 512:
        return None
    values = [request_usage(payload.get(key)) for key in
              ("usage", "turn_token_usage", "thread_token_usage")]
    if any(value is None or any(n > 2**63 - 1 for n in value.values()) for value in values):
        return None
    if any(any(left[key] > right[key] for key in left)
           for left, right in zip(values, values[1:])):
        return None
    return {key: values[-1][key + "_tokens"] for key in
            ("total", "input", "cached_input", "output", "reasoning_output")}


def _first_turn_proof(records, turn: str) -> tuple[bool, bool]:
    """Prove a full, original first-turn prefix; absence alone is never zero."""
    if not records or records[0].get("type") != "session_meta":
        return False, False
    metadata = records[0]["payload"]
    if any(value for key, value in metadata.items()
           if key.startswith("fork") or key == "parent_thread_id"):
        return False, False
    began = model_seen = usage_seen = False
    previous = None
    for record in records[1:]:
        kind, payload = record["type"], record["payload"]
        event = payload.get("type")
        if kind not in ("event_msg", "response_item", "turn_context", "world_state",
                        "token_usage_record"):
            return False, False
        if kind == "session_meta" or payload.get("turn_id") not in (None, turn):
            return False, False
        if payload.get("thread_id") not in (None, metadata.get("id")):
            return False, False
        if kind == "event_msg" and event == "task_started":
            if began or payload.get("turn_id") != turn:
                return False, False
            began = True
        elif not began:
            # Copied conversation, a prior turn, or an incomplete prefix.
            return False, False
        if kind == "response_item":
            model_seen |= event != "message" or payload.get("role") not in (
                "user", "developer", "system"
            )
        values = None
        if kind == "event_msg":
            model_seen |= event in ("agent_message", "agent_reasoning")
            if event == "token_count":
                usage_seen = True
                usage = _usage_from_line(record)
                if usage is None:
                    return False, False
                values = asdict(usage)
        if kind == "token_usage_record":
            model_seen = True
            values = _request_thread_counter(payload, metadata.get("id"), turn)
            # Older clients may only have per-request usage. They establish
            # model activity, but cannot supply a cumulative counter.
            if "thread_token_usage" in payload and values is None:
                return False, False
        if values is not None:
            usage_seen = True
            if previous and any(values[key] < previous[key] for key in values):
                return False, False
            previous = values
    return began, began and not model_seen and not usage_seen


def snapshot(path_value: Any, turn_id: str) -> dict[str, Any]:
    """Only header identity and a bounded tail are read; no text is persisted."""
    result: dict[str, Any] = {"status": "unavailable", "usage": None, "contexts": []}
    if not isinstance(path_value, str) or not path_value:
        return result
    path = Path(path_value)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return result
            header = stream.readline(128 * 1024)
            metadata = json.loads(header)
            if metadata.get("type") != "session_meta":
                return result
            payload = metadata.get("payload") or {}
            identity = payload.get("id")
            if not isinstance(identity, str) or not 0 < len(identity) <= 256:
                return result
            source = payload.get("source")
            if isinstance(source, dict) and source.get("subagent") is not None:
                return {**result, "status": "subagent"}
            offset = max(0, info.st_size - SCAN_BYTES)
            stream.seek(offset)
            raw = stream.read(info.st_size - offset)
            current = os.fstat(stream.fileno())
            if len(raw) != info.st_size - offset or current.st_size < info.st_size:
                return result
        result.update(
            status="observed",
            task_hash=stable_hash(identity),
            source_hash=stable_hash(str(path.absolute())),
            device=info.st_dev,
            inode=info.st_ino,
            size=info.st_size,
            scan_bytes=len(header) + len(raw),
            tail_limited=bool(offset),
        )
        lines = raw.split(b"\n")
        # Incomplete first/last records never establish a counter value.
        if offset:
            lines = lines[1:]
        if lines[-1]:
            try:
                json.loads(lines[-1])
            except (ValueError, RecursionError):
                lines.pop()
                result["invalid_records"] = True
        contexts = []
        usage_seen = False
        records = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                result["invalid_records"] = True
                continue
            if not isinstance(record, dict):
                result["invalid_records"] = True
                continue
            payload = record.get("payload")
            if not isinstance(record.get("type"), str) or not isinstance(payload, dict):
                result["invalid_records"] = True
                continue
            if not offset:
                records.append(record)
            if record.get("type") == "event_msg" and payload.get("type") == "token_count":
                if not usage_seen:
                    usage_seen = True
                    usage = _usage_from_line(record)
                    result["usage"] = asdict(usage) if usage is not None else None
            if (not usage_seen and record.get("type") == "token_usage_record"
                    and payload.get("turn_id") == turn_id
                    and "thread_token_usage" in payload):
                usage_seen = True
                result["usage"] = _request_thread_counter(payload, identity, turn_id)
            if (
                record.get("type") == "turn_context"
                and payload.get("turn_id") == turn_id
                and len(contexts) < 16
            ):
                effort = payload.get("effort", payload.get("reasoning_effort"))
                tier = payload.get("service_tier")
                contexts.append(
                    {
                        "model": _model(payload.get("model")),
                        "reasoning_effort": effort
                        if effort
                        in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
                        else None,
                        "fast_mode": True
                        if tier == "fast"
                        else False
                        if tier == "standard"
                        else None,
                    }
                )
        result["contexts"] = contexts
        result["requested_turn_hash"] = stable_hash(turn_id)
        first, fresh = (False, False)
        if not offset and not result.get("invalid_records"):
            first, fresh = _first_turn_proof(list(reversed(records)), turn_id)
        result.update(first_turn_only=first, fresh_turn_start=fresh)
        return result
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return {"status": "unavailable", "usage": None, "contexts": []}


def _delta(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, int] | None, str]:
    if before.get("status") != "observed" or after.get("status") != "observed":
        return None, "snapshot_unavailable"
    if any(before.get(k) != after.get(k) for k in ("task_hash", "source_hash", "device", "inode")):
        return None, "source_changed"
    if after["size"] < before["size"]:
        return None, "source_truncated"
    first, last = before.get("usage"), after.get("usage")
    verified_first = (
        first is None and before.get("fresh_turn_start") is True
        and after.get("first_turn_only") is True
        and before.get("requested_turn_hash") == after.get("requested_turn_hash")
    )
    if verified_first and last is not None:
        first = {key: 0 for key in last}
    if not first or not last:
        return None, "counter_unavailable"
    delta = {k: last[k] - first[k] for k in first}
    if (
        any(v < 0 for v in delta.values())
        or delta["total"] != delta["input"] + delta["output"]
        or delta["cached_input"] > delta["input"]
        or delta["reasoning_output"] > delta["output"]
    ):
        return None, "counter_reset_or_inconsistent"
    return delta, "verified_first_turn_counter" if verified_first else "boundary_counter_difference"


def observed_total(parent: dict | None, children: dict) -> tuple[dict | None, bool]:
    """Known subtotal only; missing or partial sources never become complete zeroes."""
    child = children.get("usage") if children.get("status") != "none" else None
    available = [value for value in (parent, child) if value is not None]
    total = (
        {key: sum(value[key] for value in available) for key in available[0]} if available else None
    )
    if parent is None and total is not None and total["total"] == 0:
        total = None
    complete = (
        parent is not None and children.get("status") in ("observed", "none")
        and not children.get("pending_agents") and not children.get("missing_agents")
        and not children.get("selection_limited")
    )
    return total, complete


def child_coverage(children: dict, locale="zh-Hant") -> str:
    text = ReportText(locale)
    if children.get("status") == "none":
        return text("no_children")
    if children.get("status") == "unavailable":
        return text("child_unavailable")
    return (
        text("child_counts", seen=text.number(children.get('agents_with_usage', 0)),
             total=text.number(children.get('agents_seen', 0)))
        + " · " + text("partial" if children.get("status") != "observed" else "observed")
    )


def _documents(receipt: dict[str, Any]) -> tuple[str, str]:
    text = ReportText(receipt.get("locale", "zh-Hant"))
    children = receipt.get("subagents") or {"status": "unavailable"}
    usage, complete = observed_total(receipt["usage"], children)

    def number(key: str) -> str:
        return text.number(usage[key] if usage is not None else None)

    rows = [
        (text("elapsed_wait"), text.duration(receipt['elapsed_seconds'], minutes=False)),
        (text("total" if complete else "subtotal"), number("total")),
        (text("parent_delta"),
         text.number(receipt['usage']['total'] if receipt["usage"] else None)),
        (text("children"), text("na") if children.get("status") == "none" else
         text.number(children['usage']['total'] if children.get("usage") else None)),
        (text("coverage"), child_coverage(children, text.locale)),
        (text("input"), number("input")),
        (text("cached"), number("cached_input")),
        (text("output"), number("output")),
        (text("reasoning"), number("reasoning_output")),
        (text("start_model"), receipt["start_model"] or text("unknown")),
        (text("stop_model"), receipt["stop_model"] or text("unknown")),
    ]
    notes = [text("note_" + key) for key in (
        "stop", "usage", "counter", "subsets", "scope", "children", "render"
    )]
    contexts = receipt["stop_contexts"]
    context_lines = []
    for context in contexts:
        fast = (
            text("on")
            if context["fast_mode"] is True
            else text("off")
            if context["fast_mode"] is False
            else text("unknown")
        )
        context_lines.append(
            text("context", model=context['model'] or text("unknown_model"),
                 effort=context['reasoning_effort'] or text("unknown"), fast=fast)
        )
    if not context_lines:
        context_lines = [text("context_missing")]
    title = text("title")
    task = receipt.get("task") or {}
    label = task.get("display_name") or f"{text('unnamed')} · {receipt['task_hash'][:12]}"
    identity = label + " · " + text("turn", value=receipt['turn_hash'][:12])
    markdown_identity = escape(identity, quote=False)
    for character, replacement in (
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("*", "&#42;"),
        ("_", "&#95;"),
        ("`", "&#96;"),
    ):
        markdown_identity = markdown_identity.replace(character, replacement)
    period = f"{receipt['started_at']} → {receipt['stopped_at']}"
    markdown = "\n".join(
        [
            f"# {title}",
            "",
            markdown_identity,
            "",
            period,
            "",
            f"| {text('column_item')} | {text('column_observation')} |",
            "| --- | --- |",
            *(f"| {k} | {v} |" for k, v in rows),
            "",
            "## " + text("settings_heading"),
            "",
            *context_lines,
            "",
            text("status", value=receipt['usage_status']),
            "",
            "## " + text("limits"),
            "",
            *(f"- {line}" for line in notes),
            "",
        ]
    )
    body = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
    html = (
        f'<!doctype html><html lang="{text.locale}"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>{title}</title><style>:root{{color-scheme:light dark}}"
        "body{font:15px/1.7 system-ui;max-width:850px;margin:auto;padding:28px;"
        "color:light-dark(#19332f,#e1ebe7);background:light-dark(#fcfcfa,#141918)}"
        "h1{font-size:30px}h2{font-size:18px;margin-top:30px}p{overflow-wrap:anywhere}"
        "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 0;"
        "border-bottom:1px solid light-dark(#d3ded8,#394640)}td{text-align:right;"
        "font-variant-numeric:tabular-nums}li{margin:8px 0}</style><main>"
        f"<h1>{title}</h1><p>{escape(identity)}</p><p>{escape(period)}</p><table>{body}</table>"
        f"<h2>{escape(text('settings_heading'))}</h2>"
        + "".join(f"<p>{escape(line)}</p>" for line in context_lines)
        + f"<p>{escape(text('status', value=receipt['usage_status']))}</p>"
        + f"<h2>{escape(text('limits'))}</h2><ul>"
        + "".join(f"<li>{escape(line)}</li>" for line in notes)
        + "</ul></main></html>"
    )
    return markdown, html


def _publish(root: Path, key: str, receipt: dict[str, Any]) -> str:
    directory = _directory(root)
    markdown, html = _documents(receipt)
    # Completed receipts remain no-clobber. Only our exact pending Markdown may
    # be atomically replaced, after both other artifacts have been written.
    for extension, content in (
        ("html", html),
        ("json", json.dumps(receipt, ensure_ascii=True, indent=2)),
    ):
        target = directory / f"{key}.{extension}"
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
    target = directory / f"{key}.md"
    if target.exists() or target.is_symlink():
        expected = _pending(key, receipt.get("pending_locale", "zh-Hant")).encode()
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            if (
                not stat.S_ISREG(os.fstat(source.fileno()).st_mode)
                or source.read(len(expected) + 1) != expected
            ):
                raise ValueError("report is not our pending target")
        descriptor, temporary = tempfile.mkstemp(prefix="receipt-", dir=directory)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(markdown)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    else:
        # Compatibility with starts recorded by older pinned runtimes.
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(markdown)
    return str(target.absolute())


def handle(
    payload: dict[str, Any],
    root: Path,
    *,
    wall: float | None = None,
    monotonic: float | None = None,
    home: Path | None = None,
) -> dict[str, Any] | None:
    """One start-time footer instruction; Stop never requests continuation."""
    event = payload.get("hook_event_name")
    if event not in EVENTS:
        return None
    try:
        if not settings(root)["enabled"]:
            return None
        if event == "SubagentStop":
            from .child_usage import capture
            capture(payload, root, home=home, now=wall)
            return None
        if payload.get("agent_id"):
            return None
        session, turn = payload.get("session_id"), payload.get("turn_id")
        if not isinstance(session, str) or not session or len(session) > 256:
            return None
        if event != "SessionEnd" and (not isinstance(turn, str) or not turn or len(turn) > 256):
            return None
        now = time.time() if wall is None else wall
        ticks = time.monotonic() if monotonic is None else monotonic
        key = stable_hash([session, turn])
        observed = None
        if event == "UserPromptSubmit":
            # Keep bounded transcript I/O outside the cross-Task write lock.
            observed = snapshot(payload.get("transcript_path"), turn)
            if observed["status"] == "subagent":
                return None
            if observed.get("task_hash") != stable_hash(session):
                observed["fresh_turn_start"] = False
            observed["hook_model"] = _model(payload.get("model"))
            observed["report_locale"] = resolve_locale(home=home)["locale"]
        connection = _connect(root)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if event == "SessionEnd":
                connection.execute(
                    "UPDATE turns SET state='session_ended' "
                    "WHERE session_hash=? AND state IN ('started','short')",
                    (stable_hash(session),),
                )
                connection.commit()
                return None
            row = connection.execute("SELECT * FROM turns WHERE key=?", (key,)).fetchone()
            if event == "UserPromptSubmit":
                footer = None
                if row is None:
                    if connection.execute("SELECT count(*) FROM turns").fetchone()[0] >= MAX_ROWS:
                        raise ValueError("auto-report timing index is full")
                    connection.execute(
                        "INSERT INTO turns VALUES (?,?,?,?,?,?,'started',NULL,NULL)",
                        (
                            key,
                            stable_hash(session),
                            stable_hash(turn),
                            now,
                            ticks,
                            json.dumps(observed, separators=(",", ":")),
                        ),
                    )
                    footer = _footer(_directory(root), key, payload, observed["report_locale"])
                connection.commit()
                return footer
            if row is None or row["state"] not in ("started", "short"):
                return None
            if event == "Interrupt":
                connection.execute("UPDATE turns SET state='interrupted' WHERE key=?", (key,))
                connection.commit()
                return None
            elapsed = ticks - row["monotonic"]
            if (
                not math.isfinite(elapsed)
                or elapsed < 0
                or abs((now - row["started"]) - elapsed) > 10
            ):
                state = "clock_discontinuity"
            elif (
                settings(root)["threshold_seconds"] > 0
                and elapsed <= settings(root)["threshold_seconds"]
            ):
                state = "short"
            else:
                state = "generating"
            connection.execute(
                "UPDATE turns SET state=?,elapsed=? WHERE key=?", (state, elapsed, key)
            )
            # Claim before file generation: a crash or timeout cannot start a retry loop.
            connection.commit()
            if state != "generating":
                return None
            started = json.loads(row["baseline"])
            stopped = snapshot(payload.get("transcript_path"), turn)
            usage, status = _delta(started, stopped)
            locale = resolve_locale(home=home)
            text = ReportText(locale["locale"])
            from .child_usage import collect
            children = collect(root, session, row["started"], now, home=home,
                               unnamed_label=text("unnamed"))
            receipt = {
                "schema_version": 2,
                "scope": "user_turn_stop_boundary",
                "task_hash": started.get("task_hash") or "unknown",
                "task": task_description(session, home=home, unnamed_label=text("unnamed"))
                if started.get("task_hash") == stable_hash(session)
                else None,
                "turn_hash": row["turn_hash"],
                "elapsed_seconds": round(elapsed, 3),
                "started_at": datetime.fromtimestamp(row["started"], timezone.utc).isoformat(),
                "stopped_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "usage": usage,
                "usage_status": status,
                "start_model": started.get("hook_model"),
                "stop_model": _model(payload.get("model")),
                "stop_contexts": stopped["contexts"],
                "snapshot_scan_bytes": started.get("scan_bytes", 0) + stopped.get("scan_bytes", 0),
                "stop_tail_limited": stopped.get("tail_limited"),
                "stop_hook_active": payload.get("stop_hook_active") is True,
                "model_requests_for_report": 0,
                "native_quota_refreshed": False,
                "subagents_included": children.get("agents_with_usage", 0) > 0,
                "subagents": children,
                "final_usage_may_not_yet_be_persisted": True,
                **locale,
                "pending_locale": started.get("report_locale", "zh-Hant"),
            }
            try:
                report = _publish(root, key, receipt)
            except Exception:
                connection.execute("UPDATE turns SET state='failed' WHERE key=?", (key,))
                raise
            connection.execute(
                "UPDATE turns SET state='reported',report=? WHERE key=?", (key + ".md", key)
            )
            return {
                "systemMessage": text.duration(elapsed) + " · "
                + f"[{text('report_link')}](<{report}>) ({text('stop_note')})"
            }
        finally:
            connection.close()
    except Exception:
        # A failed receipt must never HALT, bypass a HALT, or continue the model.
        try:
            message = ReportText(resolve_locale(home=home)["locale"])("failed")
        except Exception:
            message = (
                "Automatic usage report unavailable; budget rules and Task state are unchanged."
            )
        return {"systemMessage": message}


def recent(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    path = root / "auto-reports/timing.sqlite3"
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError("timing store is a symlink")
    from urllib.parse import quote

    connection = sqlite3.connect("file:" + quote(str(path.absolute())) + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT key,turn_hash,started,state,elapsed,report FROM turns "
                "ORDER BY started DESC LIMIT ?",
                (limit,),
            )
        ]
    finally:
        connection.close()
