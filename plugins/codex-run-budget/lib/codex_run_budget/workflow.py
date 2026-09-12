"""Bounded workflow observations, explicit cursors, and no agent control effects."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .report import write_report
from .report_render import _md_table
from .task_catalog import TaskCatalog, _uuid
from .transcript import _usage_from_line
from .util import stable_hash

TAIL_BYTES = 256 * 1024
HEADER_BYTES = 128 * 1024
MAX_TASKS = 32
MAX_SNAPSHOTS = 500
KINDS = {"task_started", "task_complete", "turn_aborted"}
LABELS = {
    "task_started": "觀測到回合起始",
    "task_complete": "觀測到回合結束",
    "turn_aborted": "觀測到回合中斷",
    "source_unavailable": "資料來源無法讀取",
    "lineage_incomplete": "代理歸屬證據不完整",
    "abort_observed_check_native": "曾觀測到中斷，需確認原生狀態",
    "old_evidence_not_proof_of_stall": "紀錄較舊，不能直接判定卡住",
    "usage_delta_unavailable": "此 Task 的 Token 前後差額不可比較",
}


def _safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink source or destination")


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        result = parsed.timestamp() if parsed.tzinfo else None
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def _anchor(stream, size):
    stream.seek(max(0, size - 4096))
    return stable_hash(stream.read(min(size, 4096)).hex())


def _read(path, identifier, previous=None):
    """Read only exact native paths, validated identity, header and bounded tail.

    Cumulative counters are comparable only across an unchanged boundary anchor and a
    fully covered append. No path, prompt, tool content or raw identifier escapes.
    """
    unknown = {"source_status": "unavailable", "usage": None, "lifecycle": None}
    try:
        path = Path(path)
        _safe_path(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return unknown
            header = stream.readline(HEADER_BYTES)
            record = json.loads(header)
            if (
                record.get("type") != "session_meta"
                or _uuid(record.get("payload", {}).get("id")) != identifier
            ):
                return {**unknown, "source_status": "identity_mismatch"}
            source = stable_hash(f"{path.absolute()}:{info.st_dev}:{info.st_ino}")
            size = info.st_size
            prior = previous or {}
            same_source = (
                source == prior.get("source_hash")
                and type(prior.get("size")) is int
                and prior["size"] <= size
            )
            continuity = same_source and _anchor(stream, prior["size"]) == prior.get("anchor")
            overhead = len(header) + (min(prior.get("size", 0), 4096) if same_source else 0)
            if continuity and size == prior["size"] and info.st_mtime_ns == prior.get("mtime_ns"):
                return {**prior, "scan_bytes": overhead, "append_status": "unchanged"}
            offset = max(len(header), size - TAIL_BYTES)
            partial_first = False
            if offset > len(header):
                stream.seek(offset - 1)
                partial_first = stream.read(1) != b"\n"
                overhead += 1
            stream.seek(offset)
            raw = stream.read(size - offset)
            current = os.fstat(stream.fileno())
            if len(raw) != size - offset or current.st_size < size:
                return unknown
            anchor = _anchor(stream, size)
        result = {
            **unknown,
            "source_status": "observed",
            "source_hash": source,
            "size": size,
            "mtime_ns": info.st_mtime_ns,
            "anchor": anchor,
            "scan_bytes": overhead + len(raw) + min(size, 4096),
            "tail_limited": offset > len(header),
            "append_status": "covered"
            if continuity
            and (offset + (raw.find(b"\n") + 1 if partial_first else 0) <= prior["size"])
            and not (partial_first and b"\n" not in raw)
            else "unproven",
            "last_record_at": None,
            "invalid_records": 0,
            "counter_discontinuity": False,
            "tail_tool_calls": 0,
            "tail_wait_calls": 0,
        }
        lines = raw.splitlines(keepends=True)
        if partial_first:
            lines = lines[1:]  # A potentially partial first record is not evidence.
        previous_counter = None
        for line in lines:
            if not line.endswith(b"\n"):
                continue  # Never advance semantic evidence with a partial trailing line.
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                result["invalid_records"] += 1
                continue
            if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                continue
            payload = record["payload"]
            timestamp = _stamp(record.get("timestamp"))
            if timestamp is not None:
                result["last_record_at"] = timestamp
            if record.get("type") == "event_msg":
                if payload.get("type") in KINDS:
                    turn = payload.get("turn_id")
                    result["lifecycle"] = {
                        "kind": payload["type"],
                        "turn_hash": stable_hash(turn) if isinstance(turn, str) and turn else None,
                        "at": timestamp,
                    }
                if payload.get("type") == "token_count":
                    usage = _usage_from_line(record)
                    current_counter = asdict(usage) if usage else None
                    if (
                        previous_counter
                        and current_counter
                        and any(current_counter[k] < previous_counter[k] for k in current_counter)
                    ):
                        result["counter_discontinuity"] = True
                    result["usage"] = current_counter
                    previous_counter = current_counter
            if record.get("type") == "response_item" and payload.get("type") in (
                "function_call",
                "custom_tool_call",
            ):
                result["tail_tool_calls"] += 1
                # Wrapped code-mode calls are not parsed or inferred.
                name = payload.get("name")
                if isinstance(name, str) and name.rsplit(".", 1)[-1] in (
                    "wait_threads",
                    "wait_agent",
                    "sleep",
                ):
                    result["tail_wait_calls"] += 1
        return result
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return unknown


def _delta(first, last):
    if last.get("append_status") not in ("covered", "unchanged"):
        return None
    if last.get("counter_discontinuity") or last.get("invalid_records"):
        return None
    a, b = first.get("usage"), last.get("usage")
    if not a or not b:
        return None
    delta = {key: b[key] - a[key] for key in a}
    if (
        any(v < 0 for v in delta.values())
        or delta["total"] != delta["input"] + delta["output"]
        or delta["cached_input"] > delta["input"]
        or delta["reasoning_output"] > delta["output"]
    ):
        return None
    return delta


def _fingerprint(row):
    # Exclude observation time, read costs and append-comparison metadata.
    fields = (
        "source_status",
        "source_hash",
        "size",
        "mtime_ns",
        "anchor",
        "usage",
        "lifecycle",
        "invalid_records",
        "counter_discontinuity",
    )
    return stable_hash(json.dumps({k: row.get(k) for k in fields}, sort_keys=True))


class WorkflowObserver:
    """One interface for local capture + cursor comparison; never a scheduler."""

    def __init__(self, root, home=None):
        self.root = Path(root) / "workflow-observations"
        self.home = home

    def _connect(self):
        _safe_path(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root / "observations.sqlite3"
        _safe_path(path)
        if not path.exists():
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        _safe_path(path)
        if not path.is_file():
            raise ValueError("invalid observation store")
        connection = sqlite3.connect(path, timeout=0.5)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS snapshots (cursor TEXT PRIMARY KEY, "
            "scope TEXT NOT NULL, captured REAL NOT NULL, payload TEXT NOT NULL)"
        )
        return connection

    def select(self, selectors, include_agents=False, limit=8):
        if not 1 <= len(selectors) <= 8 or type(limit) is not int or not 1 <= limit <= MAX_TASKS:
            raise ValueError("select 1..8 roots and 1..32 Tasks")
        with TaskCatalog(self.home) as catalog:
            roots = [catalog.get(value) for value in selectors]
            if len({row["id"] for row in roots}) != len(roots) or len(roots) > limit:
                raise ValueError("duplicate roots or insufficient Task limit")
            selected = {row["id"]: row for row in roots}
            if include_agents:
                for root in roots:
                    # Keep every explicit root even when descendants hit the cap.
                    family = catalog.family(root, limit)
                    for row in family:
                        if row["id"] not in selected and len(selected) >= limit:
                            catalog.limited = True
                        else:
                            selected[row["id"]] = row
            metadata = [catalog.describe(row) for row in selected.values()]
            paths = {
                identifier: catalog.connection.execute(
                    "SELECT rollout_path FROM threads WHERE id=?", (identifier,)
                ).fetchone()[0]
                for identifier in selected
            }
            scope = stable_hash(
                json.dumps(
                    {
                        "roots": sorted(r["thread_hash"] for r in roots),
                        "include_agents": include_agents,
                        "limit": limit,
                    }
                )
            )
            return scope, metadata, paths, catalog.limited

    def capture(self, selectors, *, include_agents=False, limit=8, after=None, now=None):
        captured = time.time() if now is None else now
        if type(captured) not in (int, float) or not math.isfinite(captured):
            raise ValueError("invalid observation time")
        if after is not None and not re.fullmatch(r"[0-9a-f]{64}", after):
            raise ValueError("invalid cursor")
        scope, metadata, paths, limited = self.select(selectors, include_agents, limit)
        connection = self._connect()
        try:
            baseline = None
            if after:
                found = connection.execute(
                    "SELECT scope,payload FROM snapshots WHERE cursor=?", (after,)
                ).fetchone()
                if not found or found[0] != scope:
                    raise ValueError("cursor expired or belongs to a different scope")
                baseline = json.loads(found[1])
                if baseline["captured_at"] > captured:
                    raise ValueError("observation clock went backwards")
            prior = {r["thread_hash"]: r for r in baseline["tasks"]} if baseline else {}
            tasks, changes, signals, tokens, comparable = [], [], [], 0, 0
            for identity, path in paths.items():
                key = stable_hash(identity)
                old = prior.get(key)
                telemetry = _read(path, identity, (old or {}).get("observation"))
                row = {
                    **next(m for m in metadata if m["thread_hash"] == key),
                    "observation": telemetry,
                }
                tasks.append(row)
                changed = not old or _fingerprint(telemetry) != _fingerprint(old["observation"])
                if old and any(
                    row.get(k) != old.get(k)
                    for k in ("display_name", "parent_hash", "root_hash", "lineage_status")
                ):
                    changed = True
                delta = _delta(old["observation"], telemetry) if old else None
                if delta is not None:
                    comparable += 1
                    tokens += delta["total"]
                lifecycle = telemetry.get("lifecycle") or {}
                if telemetry["source_status"] != "observed":
                    signals.append({"task": key, "kind": "source_unavailable"})
                if row["lineage_status"] != "observed":
                    signals.append({"task": key, "kind": "lineage_incomplete"})
                if lifecycle.get("kind") == "turn_aborted":
                    signals.append({"task": key, "kind": "abort_observed_check_native"})
                stamp = telemetry.get("last_record_at")
                if (
                    stamp is not None
                    and stamp <= captured - 900
                    and lifecycle.get("kind") != "task_complete"
                ):
                    signals.append({"task": key, "kind": "old_evidence_not_proof_of_stall"})
                if old and delta is None:
                    signals.append({"task": key, "kind": "usage_delta_unavailable"})
                if changed:
                    changes.append(
                        {
                            "thread_hash": key,
                            "display_name": row["display_name"],
                            "last_lifecycle": lifecycle.get("kind"),
                            "token_delta": delta,
                        }
                    )
            removed = sorted(set(prior) - {r["thread_hash"] for r in tasks})
            old_signals = baseline.get("signals", []) if baseline else []
            new_signals = [s for s in signals if s not in old_signals]
            cleared_signals = [s for s in old_signals if s not in signals]
            result = {
                "schema_version": 1,
                "scope": scope,
                "captured_at": captured,
                "baseline_at": baseline["captured_at"] if baseline else None,
                "tasks": tasks,
                "selection_limited": limited,
                "changes": changes,
                "removed_from_selection": removed,
                "signals": signals,
                "new_signals": new_signals,
                "cleared_signals": cleared_signals,
                "changed": bool(
                    changes
                    or removed
                    or new_signals
                    or cleared_signals
                    or (baseline and baseline["selection_limited"] != limited)
                ),
                "consecutive_unchanged": 0
                if changes or removed
                else (baseline.get("consecutive_unchanged", 0) + 1 if baseline else 0),
                "observed_token_delta": tokens if comparable else None,
                "comparable_tasks": comparable,
                "selected_tasks": len(tasks),
                "scan_bytes": sum(r["observation"].get("scan_bytes", 0) for r in tasks),
                "model_requests": 0,
                "live_status": "not_queried",
                "workflow_acceptance": "not_evaluated",
            }
            cursor = stable_hash(json.dumps(result, sort_keys=True) + str(time.time_ns()))
            result["cursor"] = cursor
            connection.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?)",
                (cursor, scope, captured, json.dumps(result, ensure_ascii=False)),
            )
            connection.execute(
                "DELETE FROM snapshots WHERE cursor IN (SELECT cursor FROM snapshots "
                "ORDER BY captured DESC,cursor DESC LIMIT -1 OFFSET ?)",
                (MAX_SNAPSHOTS,),
            )
            connection.commit()
            return result
        finally:
            connection.close()


def render(result):
    rows = []
    for task in result["tasks"]:
        observed = task["observation"]
        rows.append(
            [
                task["display_name"],
                task["parent_name"] or "—",
                task["root_name"] or "未知",
                LABELS.get((observed.get("lifecycle") or {}).get("kind"), "未觀測"),
                observed["source_status"],
            ]
        )
    names = {r["thread_hash"]: r["display_name"] for r in result["tasks"]}
    return "\n".join(
        [
            "# Workflow 觀察",
            "",
            f"選定 {len(rows)} 個 Task；範圍受限：{result['selection_limited']}。",
            "",
            _md_table(
                ["Task / 代理", "直屬主代理", "所屬主 Task", "最後生命週期證據", "資料來源"], rows
            ),
            "",
            f"可比較 {result['comparable_tasks']} 個 Task 的前後 Token 差額："
            f"{result['observed_token_delta']}。",
            f"本次讀取 {result['scan_bytes']} bytes；模型呼叫 0。",
            "",
            _md_table(
                ["Task", "需確認訊號"],
                [
                    [names.get(s["task"], "選定任務"), LABELS.get(s["kind"], s["kind"])]
                    for s in result["signals"]
                ],
            ),
            "",
            "這是本機紀錄觀察，不是原生即時狀態。"
            "task_complete 只證明回合結束，不是 workflow 驗收。",
            "無新紀錄不等於卡死；Token 差額不是額度或帳單，部分 Task 不可比較時不能當作全量。",
            "每頁最多讀 256 KiB 尾端；tool/wait 計數只有尾端直接呼叫，未解開 code-mode 包裝。",
            "效率改善需比較相同工作範圍與驗收品質；本工具不宣稱已省下時間或 Token。",
            "",
        ]
    )


def run(args):
    if args.action is None:
        print(
            "workflow observe --thread 選擇代碼 [--include-agents] [--after CURSOR]\n"
            "workflow targets：只列原生 wait_threads 的精確目標，不讀對話。\n"
            "預設最多 8 個 Task；觀察只回差異，不開背景排程或操控代理。"
        )
        return
    selectors = args.thread or [os.environ.get("CODEX_THREAD_ID")]
    if not all(selectors):
        raise ValueError("select a Task first")
    observer = WorkflowObserver(args.data_dir, args.codex_home)
    if args.action == "targets":
        _, metadata, paths, limited = observer.select(selectors, args.include_agents, args.limit)
        if len(paths) > 8:
            raise ValueError("native wait supports at most 8 targets per call")
        current = os.environ.get("CODEX_THREAD_ID")
        targets = [
            {"threadId": identifier, "hostId": "local"}
            for identifier in paths
            if identifier != current
        ]
        print(
            json.dumps(
                {
                    "targets": targets,
                    "timeoutMs": 0,
                    "limited": limited,
                    "calling_task_excluded": current in paths,
                    "names": [r["display_name"] for r in metadata],
                },
                ensure_ascii=False,
            )
        )
        return
    result = observer.capture(
        selectors, include_agents=args.include_agents, limit=args.limit, after=args.after
    )
    if result["changed"]:
        path = observer.root / f"{result['cursor']}.md"
        write_report(path, render(result))
        result["report_path"] = str(path.absolute())
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(
            f"{'觀察到變化' if result['changed'] else '無新變化'}；"
            f"{result['selected_tasks']} 個 Task；"
            f"{len(result['new_signals'])} 個新訊號；讀取 {result['scan_bytes']} bytes。"
        )
        for row in result["changes"][:8]:
            print(f"- {row['display_name']}：{LABELS.get(row['last_lifecycle'], '生命週期未觀測')}")
        names = {r["thread_hash"]: r["display_name"] for r in result["tasks"]}
        for signal in result["new_signals"][:5]:
            print(f"- {names[signal['task']]}：{LABELS[signal['kind']]}")
        if result["cleared_signals"]:
            print(f"已解除 {len(result['cleared_signals'])} 個先前訊號。")
        if result["selection_limited"]:
            print("選取已達上限，不是完整代理樹。")
        print(
            f"可比較 Token 差額：{result['observed_token_delta']}"
            f"（{result['comparable_tasks']} 個 Task）。"
        )
        print("原生即時狀態／workflow 驗收尚未查證；不據此自動介入。")
        print(f"cursor: {result['cursor']}")
        if result.get("report_path"):
            print(f"[觀察報告](<{result['report_path']}>)")
