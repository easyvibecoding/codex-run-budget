"""One bounded pre-final snapshot for Codex's inline visualization surface.

This tool never starts or completes a turn, calls a model, reads other Tasks,
or rewrites a previously presented snapshot. The model emits only its reference.
"""

from __future__ import annotations

import json
import math
import os
import pkgutil
import sqlite3
import time
from datetime import datetime
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote

from .auto_report import _delta, settings, snapshot
from .task_catalog import TaskCatalog, _uuid
from .util import stable_hash


def render_card(receipt: dict) -> str:
    usage = receipt["usage"]

    def number(key):
        return f"{usage[key]:,}" if usage is not None else "未觀測"

    contexts = receipt["contexts"]

    def observed(field, labels=None):
        values = []
        for context in contexts:
            value = context.get(field)
            label = labels.get(value, "未知") if labels else str(value or "未知")
            if label not in values:
                values.append(label)
        return " / ".join(values) or "未知"

    seconds = receipt["elapsed_seconds"]
    elapsed = "未知" if seconds is None else f"{seconds / 60:.1f} 分鐘"
    template = pkgutil.get_data("codex_run_budget", "assets/turn-card.html")
    if template is None:
        raise ValueError("card template unavailable")
    values = {
        "key": receipt["key"], "task": receipt["task_name"],
        "captured": receipt["captured_at"], "total": number("total"), "elapsed": elapsed,
        "usage_label": "開始至快照的累計差額" if usage is not None else "缺少可靠的前後計數器",
        "model": observed("model"), "effort": observed("reasoning_effort"),
        "fast": observed("fast_mode", {True: "開啟", False: "關閉"}),
        "input": number("input"), "cached": number("cached_input"),
        "output": number("output"), "reasoning": number("reasoning_output"),
    }
    return Template(template.decode()).substitute({k: escape(str(v)) for k, v in values.items()})


def preview(root: Path, session: str, turn: str, *, output_dir: Path, home=None) -> dict:
    """Return only a reference/status, never a report body or raw native paths."""
    policy = settings(root)
    if not policy["enabled"]:
        return {"status": "disabled"}
    if not _uuid(session) or not isinstance(turn, str) or not 0 < len(turn) <= 256:
        raise ValueError("invalid preview identity")
    key = stable_hash([session, turn])
    path = root / "auto-reports/timing.sqlite3"
    if root.is_symlink() or path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        return {"status": "missing_start"}
    connection = sqlite3.connect(
        "file:" + quote(str(path.absolute())) + "?mode=ro", uri=True, timeout=0.4
    )
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM turns WHERE key=?", (key,)).fetchone()
    finally:
        connection.close()
    if row is None or row["state"] not in ("started", "short"):
        return {"status": "no_active_start"}
    if row["session_hash"] != stable_hash(session) or row["turn_hash"] != stable_hash(turn):
        raise ValueError("timing identity mismatch")
    seconds = time.monotonic() - row["monotonic"]
    if (
        not math.isfinite(seconds) or seconds < 0
        or abs(time.time() - row["started"] - seconds) > 10
    ):
        seconds = None
    if policy["threshold_seconds"] and (seconds is None or seconds <= policy["threshold_seconds"]):
        return {"status": "below_threshold"}
    with TaskCatalog(home) as catalog:
        task = catalog.get(session)
        if task["role"] != "parent":
            return {"status": "subagent"}
        native = catalog.connection.execute(
            "SELECT rollout_path FROM threads WHERE id=?", (session,)
        ).fetchone()
        current = snapshot(native[0] if native else None, turn)
    if current.get("task_hash") != stable_hash(session):
        return {"status": "source_unavailable"}
    usage, status = _delta(json.loads(row["baseline"]), current)
    receipt = {
        "key": key, "task_name": task["display_name"], "usage": usage, "usage_status": status,
        "contexts": current["contexts"], "elapsed_seconds": seconds,
        "captured_at": datetime.now().astimezone().strftime("%H:%M:%S %Z"),
    }
    if not output_dir.is_absolute() or any(
        p.is_symlink() for p in (output_dir, *output_dir.parents)
    ):
        raise ValueError("output must be an absolute nonsymlink task-owned directory")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = output_dir / ("codex-turn-" + key[:16] + "-" + str(time.time_ns()) + ".html")
    content = render_card(receipt)
    if len(content.encode()) > 1_000_000:
        raise ValueError("card too large")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)
    reference = (
        "\ue200visualize\ue202" + json.dumps({"path": str(target)}, ensure_ascii=False) + "\ue201"
    )
    return {"status": "preview", "reference": reference}
