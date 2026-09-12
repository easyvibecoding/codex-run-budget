from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .audit import audit_transcript, audit_transcripts
from .governor import Governor
from .ledger import Ledger
from .survey import survey_summary, survey_transcripts
from .util import data_dir, data_path, parse_count, stable_hash


def _resolve_run(ledger: Ledger, value: str) -> str:
    if value != "latest":
        return value
    runs = ledger.list_runs(1)
    if not runs:
        raise ValueError("no run-budget records found")
    return str(runs[0]["run_id"])


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "run_id",
        "epoch",
        "status",
        "max_tokens",
        "spent_tokens",
        "warn_ratio",
        "tool_calls",
        "max_tool_calls",
        "in_flight",
        "max_in_flight",
        "active_agents",
        "max_agents",
        "pending_agents",
        "usage_status",
        "usage_issues",
        "halt_reason",
        "created_at",
        "updated_at",
    )
    return {key: run.get(key) for key in keep}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-budget",
        description="Inspect and operate the local Codex Run Budget ledger.",
    )
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="read-only, privacy-preserving transcript diagnostics")
    audit.add_argument("transcript", type=Path, nargs="+")

    survey = sub.add_parser("survey", help="read-only overview of recent local tasks")
    survey.add_argument("directory", type=Path, nargs="?")
    survey.add_argument("--days", type=float, default=7)
    survey.add_argument("--limit", type=int, default=200)
    output = survey.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="include complete per-thread evidence")
    output.add_argument(
        "--lifecycle", action="store_true", help="include up to 20 turn-lifecycle evidence rows"
    )

    meter = sub.add_parser("meter", help="sense native account quotas; keep local snapshots")
    meter.add_argument(
        "action",
        choices=("snapshot", "report", "history", "tasks", "rates", "estimate"),
        nargs="?",
        default="snapshot",
    )
    meter.add_argument(
        "--thread",
        action="append",
        default=[],
        help="snapshot: backend UUID (up to 8); report/tasks/estimate: exact local task filter",
    )
    meter.add_argument("--json", action="store_true")
    meter.add_argument(
        "--no-save", action="store_true", help="snapshot without writing local history"
    )
    meter.add_argument("--directory", type=Path, help="local sessions directory for report")
    meter.add_argument("--days", type=float, default=7, help="tasks lookback in days (default 7)")
    meter.add_argument(
        "--limit", type=int, help="report file limit (200) or history row limit (20)"
    )
    meter.add_argument(
        "--baseline", type=int, help="report from a saved snapshot id (within last 1000)"
    )
    meter.add_argument("--codex-binary", default="codex", help="Codex executable for native reads")
    meter.add_argument(
        "--timeout", type=float, default=30, help="total native-read deadline in seconds"
    )

    report = sub.add_parser("report", help="export read-only multi-window Task reports")
    report.add_argument("--thread", action="append", default=[], help="exact Task UUID; repeatable")
    report.add_argument("--windows", help="comma-separated: 5h,24h,7d,30d,today,week,month")
    report.add_argument("--timezone", default="UTC", help="IANA timezone, e.g. Asia/Taipei")
    report.add_argument("--since", help="custom start; ISO timestamp with explicit UTC offset")
    report.add_argument("--until", help="report end; ISO timestamp with explicit UTC offset")
    report.add_argument("--directory", type=Path, help="local sessions directory")
    report.add_argument("--limit", type=int, default=200, help="maximum transcript pages")
    report.add_argument(
        "--detail-limit", type=int, default=200, help="turn/context rows per window"
    )
    report.add_argument("--format", choices=("markdown", "html", "json"), default="markdown")
    report.add_argument(
        "--output", type=Path, help="create private report; existing files are refused"
    )

    listing = sub.add_parser("list", help="list recent governed runs")
    listing.add_argument("--limit", type=int, default=20)

    show = sub.add_parser("show", help="show one run; use 'latest' for the newest")
    show.add_argument("run_id")
    show.add_argument("--json", action="store_true")

    events = sub.add_parser("events", help="export privacy-preserving lineage events")
    events.add_argument("run_id")
    events.add_argument("--epoch", type=int)

    halt = sub.add_parser("halt", help="operator HALT")
    halt.add_argument("run_id")
    halt.add_argument("--reason", default="operator requested HALT")

    resume = sub.add_parser("resume", help="resume a halted run")
    resume.add_argument("run_id")
    resume.add_argument("--tokens", help="new absolute token ceiling, such as 200k")

    off = sub.add_parser("off", help="disable governance for a run")
    off.add_argument("run_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        from .report import build_report, render_report, write_report

        try:
            report = build_report(
                sessions=args.directory, directory=args.data_dir or data_path(),
                windows=args.windows.split(",") if args.windows is not None else None,
                timezone_name=args.timezone, since=args.since, until=args.until,
                thread_ids=args.thread, limit=args.limit, detail_limit=args.detail_limit,
            )
            rendered = render_report(report, args.format)
            if args.output is not None:
                write_report(args.output, rendered)
                print(f"Report created: {args.output.absolute()}")
            else:
                print(rendered, end="")
            return 0
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, RecursionError):
            print("run-budget: cannot create report (invalid range, source or output; "
                  "existing files are never overwritten)", file=sys.stderr)
            return 2
    if args.command == "meter":
        # Keep native reads and meter storage out of the enforcement runtime.
        from .meter import (
            estimate_summary,
            load_snapshots,
            meter_estimate,
            meter_report,
            meter_tasks,
            normalize_snapshot,
            record_snapshot,
            report_summary,
            snapshot_summary,
            tasks_summary,
        )
        from .meter_policy import pricing_context
        from .meter_source import read_meter_sources

        try:
            root = args.data_dir or data_path()
            if args.action == "snapshot":
                sources = read_meter_sources(
                    codex_binary=args.codex_binary,
                    thread_ids=args.thread,
                    timeout=args.timeout,
                )
                report = (
                    normalize_snapshot(sources) if args.no_save else record_snapshot(root, sources)
                )
                rendered = snapshot_summary(report)
            elif args.action == "report":
                report = meter_report(
                    root,
                    sessions=args.directory,
                    limit=args.limit if args.limit is not None else 200,
                    baseline_id=args.baseline,
                    thread_ids=args.thread,
                )
                rendered = report_summary(report)
            elif args.action in ("tasks", "estimate"):
                reader = meter_estimate if args.action == "estimate" else meter_tasks
                report = reader(
                    sessions=args.directory,
                    days=args.days,
                    limit=args.limit if args.limit is not None else 200,
                    thread_ids=args.thread,
                )
                rendered = (
                    estimate_summary(report) if args.action == "estimate" else tasks_summary(report)
                )
            elif args.action == "rates":
                report = pricing_context()
                rendered = json.dumps(report, indent=2, sort_keys=True)
            else:
                report = load_snapshots(root, limit=args.limit if args.limit is not None else 20)
                rendered = (
                    "\n\n".join(snapshot_summary(row) for row in report) or "No saved snapshots."
                )
            print(json.dumps(report, indent=2, sort_keys=True) if args.json else rendered)
            return (
                2 if args.action == "snapshot" and report["source_status"] == "unavailable" else 0
            )
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, RecursionError):
            print(
                "run-budget: cannot read meter (invalid selection, storage or native source)",
                file=sys.stderr,
            )
            return 2
    if args.command in ("audit", "survey"):
        try:
            if args.command == "survey":
                report = survey_transcripts(args.directory, days=args.days, limit=args.limit)
            elif len(args.transcript) == 1:
                report = audit_transcript(args.transcript[0])
            else:
                report = audit_transcripts(args.transcript)
            print(
                survey_summary(report, lifecycle_details=args.lifecycle)
                if args.command == "survey" and not args.json
                else json.dumps(report, indent=2, sort_keys=True)
            )
            return 0
        except (OSError, ValueError):
            print(
                "run-budget: cannot audit transcripts (unreadable files or invalid selection)",
                file=sys.stderr,
            )
            return 2
    governor = Governor(args.data_dir or data_dir())
    ledger = governor.ledger
    try:
        if args.command == "list":
            for run in ledger.list_runs(args.limit):
                print(Governor.status_text(run) + f" Run id: {run['run_id']}")
            return 0

        run_id = _resolve_run(ledger, args.run_id)
        if args.command == "show":
            run = ledger.get_run(run_id)
            if not run:
                raise ValueError(f"unknown run: {run_id}")
            print(
                json.dumps(_public_run(run), indent=2, sort_keys=True)
                if args.json
                else Governor.status_text(run)
            )
            return 0
        if args.command == "events":
            for event in ledger.events(run_id, args.epoch):
                print(json.dumps(event, sort_keys=True, separators=(",", ":")))
            return 0
        if args.command == "halt":
            detail_hash = stable_hash(args.reason) if args.reason else None
            run = ledger.halt(run_id, "operator requested HALT", detail_hash=detail_hash)
        elif args.command == "resume":
            run = ledger.resume(run_id, parse_count(args.tokens) if args.tokens else None)
        else:
            run = ledger.disable(run_id)
        if not run:
            raise ValueError(f"unknown run: {run_id}")
        if args.command == "off":
            governor._remove_marker(run_id)
        else:
            governor._write_marker(run_id, run)
        print(Governor.status_text(run))
        return 0
    except (OSError, ValueError) as exc:
        print(f"run-budget: {exc}", file=sys.stderr)
        return 2
    finally:
        governor.close()
