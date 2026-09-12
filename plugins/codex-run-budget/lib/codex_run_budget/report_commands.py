"""Scope-first report commands. Large artifacts never enter stdout by default."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .report import build_report, render_report, write_report
from .report_render import _md_table
from .task_catalog import TaskCatalog, _uuid
from .util import data_path

MENU = """Codex 用量分析：先選範圍，不讀取全量歷史。
- report tasks：最近 10 個任務名稱與選擇代碼，僅中繼資料。
- report task：目前 Task 最近 24h；可用 --thread 選擇代碼指定。
- report agents：目前 Task 的代理關係，不讀 Token 紀錄。
- report tree：明確分析目前 Task 與子代理，最近 24h。
- report window --windows 5h：目前 Task 的單一窗口。
跨任務必須明確加 --all-tasks；預設最多 20 頁、20 組明細。
分析預設存檔、只回短摘要；--full 才將完整報告印到 stdout。
Codex slash 入口：/skills → usage-task / usage-agents / usage-window。
"""


def _attach_names(report, home, known):
    try:
        with TaskCatalog(home) as catalog:
            for key, row in report["task_catalog"].items():
                try:
                    metadata = known.get(key) or catalog.describe(catalog.get(key))
                except ValueError:
                    continue
                if (
                    metadata["parent_hash"] != row["parent_hash"]
                    or metadata["role"] != row.get("role")
                    or row.get("lineage_status") == "conflicting_parent_sources"
                ):
                    row.update(
                        display_name=metadata["display_name"],
                        name_source=metadata["name_source"],
                        parent_name=None,
                        root_name=None,
                        root_hash=None,
                        lineage_status="conflicting_parent_sources",
                    )
                else:
                    row.update(metadata)
    except (OSError, ValueError, sqlite3.Error):
        report["catalog_status"] = "partial_or_unavailable"


def run(args):
    if args.limit is not None and not 1 <= args.limit <= 1000:
        raise ValueError("limit must be 1..1000")
    view = args.view
    if view is None:
        if not any(
            (args.thread, args.all_tasks, args.windows, args.since, args.until, args.output)
        ):
            print(MENU, end="")
            return
        view = "window"
    if view == "help":
        print(MENU, end="")
        return
    if view == "tasks" and args.thread:
        raise ValueError("use report task/agents with --thread")
    if args.all_tasks and (args.thread or view not in ("window",)):
        raise ValueError("--all-tasks is only for an explicit cross-Task window")
    if args.all_tasks and not (args.windows or args.since):
        raise ValueError("cross-Task analysis requires an explicit time window")
    ids, known = [], {}
    if view in ("tasks", "agents", "tree") or not args.all_tasks:
        selectors = args.thread or [os.environ.get("CODEX_THREAD_ID")]
        if view != "tasks" and not all(selectors):
            raise ValueError("no current Task; run report tasks, then use --thread")
        try:
            with TaskCatalog(args.codex_home) as catalog:
                if view == "tasks":
                    selected = catalog.recent(min(args.limit or 10, 100))
                else:
                    selected = [catalog.get(value) for value in selectors]
                    if view in ("agents", "tree"):
                        if len(selected) != 1:
                            raise ValueError("select one Task for its agent tree")
                        selected = catalog.family(selected[0], min(args.limit or 20, 64))
                ids = [item["id"] for item in selected]
                known = {item["thread_hash"]: catalog.describe(item) for item in selected}
                limited = catalog.limited
        except (OSError, ValueError, sqlite3.Error):
            # An explicit UUID + exported transcript directory works without a
            # native catalog; never turn a failed selector into an all-Task scan.
            if (
                view in ("tasks", "agents", "tree")
                or not args.directory
                or not all(_uuid(s) for s in selectors)
            ):
                raise ValueError(
                    "Task catalog/selector unavailable; run report tasks "
                    "or supply an exact UUID with --directory"
                ) from None
            ids, limited = [_uuid(s) for s in selectors], False
        if view in ("tasks", "agents"):
            rows = list(known.values())
            if args.format == "json":
                print(
                    json.dumps(
                        {"tasks": rows, "limited": limited, "transcript_pages_read": 0},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(
                    _md_table(
                        ["任務 / 代理", "選擇代碼", "直屬主代理", "所屬主 Task", "角色"],
                        [
                            [
                                r["display_name"],
                                r["selector"],
                                r["parent_name"] or "—",
                                r["root_name"] or "未觀測",
                                r["agent_role"] or r["role"],
                            ]
                            for r in rows
                        ],
                    )
                )
                print(f"\n僅讀中繼資料；{len(rows)} 筆；範圍受限：{limited}。")
            return
    report = build_report(
        sessions=args.directory,
        directory=args.data_dir or data_path(),
        windows=args.windows.split(",") if args.windows is not None else None,
        timezone_name=args.timezone,
        since=args.since,
        until=args.until,
        thread_ids=ids,
        all_tasks=args.all_tasks,
        limit=args.limit or 20,
        detail_limit=args.detail_limit,
    )
    _attach_names(report, args.codex_home, known)
    for key, metadata in known.items():
        report["task_catalog"].setdefault(key, metadata)
    report["scope"]["requested_view"] = view
    if view == "tree":
        report["scope"]["tree_selection_limited"] = limited
    rendered = render_report(report, args.format)
    if args.full and args.output is None:
        print(rendered, end="")
        return
    output = args.output
    if output is None:
        directory = (args.data_dir or data_path()) / "reports"
        if any(parent.is_symlink() for parent in (directory, *directory.parents)):
            raise ValueError("output directory is a symlink")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        extension = {"markdown": "md", "html": "html", "json": "json"}[args.format]
        output = directory / f"usage-{time.time_ns()}.{extension}"
    write_report(output, rendered)
    labels = [r["display_name"] for r in report["task_catalog"].values()]
    print(
        "範圍："
        + ("；".join(labels[:3]) or "選定範圍無請求觀測")
        + (" …" if len(labels) > 3 else "")
    )
    for window in report["windows"]:
        usage = window["usage"] or {}
        print(
            f"{window['name']}：{usage.get('total_tokens', '未觀測')} Token；"
            f"{usage.get('unique_responses', '未觀測')} 筆請求"
        )
    print(f"僅分析 {report['coverage']['selection']['selected_files']} 個紀錄頁；完整報告已存檔。")
    if view == "tree" and limited:
        print("代理樹已達數量或深度上限；不是完整後代用量。")
    print(f"[開啟報告](<{Path(output).absolute()}>)")
