"""Scope-first report commands. Large artifacts never enter stdout by default."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .report import build_report, render_report, write_report
from .report_i18n import ReportText, human_text
from .report_render import _md_table
from .task_catalog import TaskCatalog, _uuid
from .util import data_path


def _attach_names(report, home, known, labels=None):
    try:
        options = {}
        if labels is not None:
            options["unnamed_label"] = labels("unnamed_task")
        with TaskCatalog(home, **options) as catalog:
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


def run(args, *, locale=None):
    if args.limit is not None and not 1 <= args.limit <= 1000:
        raise ValueError("limit must be 1..1000")
    view = args.view
    # Machine JSON never needs a human adapter, even if a caller accidentally
    # forwards a locale.  The CLI normally passes ``locale`` only on its human
    # route; keeping this guard here protects direct library callers too.
    labels = (
        ReportText(locale, domain="reports")
        if locale is not None and args.format != "json"
        else None
    )

    def human_labels():
        nonlocal labels
        if labels is None:
            labels = human_text("reports", home=args.codex_home)
        return labels

    if view is None:
        if not any(
            (args.thread, args.all_tasks, args.windows, args.since, args.until, args.output)
        ):
            print(human_labels()("menu"), end="")
            return
        view = "window"
    if view == "help":
        print(human_labels()("menu"), end="")
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
        human = human_labels() if args.format != "json" else None
        catalog_options = {"unnamed_label": human("unnamed_task")} if human else {}
        try:
            with TaskCatalog(args.codex_home, **catalog_options) as catalog:
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
                        [
                            human("column_task_agent"),
                            human("column_selector"),
                            human("column_parent"),
                            human("column_root"),
                            human("column_role"),
                        ],
                        [
                            [
                                r["display_name"],
                                r["selector"],
                                r["parent_name"] or human("dash"),
                                r["root_name"] or human("not_observed"),
                                r["agent_role"] or r["role"],
                            ]
                            for r in rows
                        ],
                        human,
                    )
                )
                print(
                    "\n"
                    + human(
                        "metadata_summary",
                        count=human.number(len(rows)),
                        limited=human("bool_yes") if limited else human("bool_no"),
                    )
                )
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
    human = human_labels() if args.format != "json" else None
    _attach_names(report, args.codex_home, known, human)
    for key, metadata in known.items():
        report["task_catalog"].setdefault(key, metadata)
    report["scope"]["requested_view"] = view
    if view == "tree":
        report["scope"]["tree_selection_limited"] = limited
    rendered = render_report(report, args.format, text=human)
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
    # A JSON artifact is still followed by a human-readable summary unless
    # ``--full`` streamed the canonical payload directly above.  Resolve the
    # catalog only at this mixed-output boundary; JSON bytes were written
    # before any human formatting is attempted.
    if human is None and args.format == "json":
        human = human_labels()
    names = [_task_display_name(row, human) for row in report["task_catalog"].values()]
    print(
        human(
            "summary_scope",
            tasks=("；".join(names[:3]) or human("scope_empty"))
            + (" …" if len(names) > 3 else ""),
        )
    )
    for window in report["windows"]:
        usage = window["usage"] or {}
        print(
            human(
                "summary_window",
                name=window["name"],
                tokens=human.number(usage.get("total_tokens")),
                requests=human.number(usage.get("unique_responses")),
            )
        )
    print(
        human(
            "summary_files",
            files=human.number(report["coverage"]["selection"]["selected_files"]),
        )
    )
    if view == "tree" and limited:
        print(human("summary_tree_limited"))
    print(
        "["
        + human("report_output_link")
        + "](<"
        + _safe_link_path(Path(output).absolute())
        + ">)"
    )


def _task_display_name(row, labels):
    name = row.get("display_name")
    if name and row.get("name_source") not in ("unnamed", "unavailable"):
        return str(name)
    return labels("unnamed_task_hash", hash=row.get("selector", "unknown")) if labels else (
        "Unnamed task · " + str(row.get("selector", "unknown"))
    )


def _safe_link_path(path: Path) -> str:
    """Keep the Markdown destination harmless when a user chooses a odd path."""
    return str(path).replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")
