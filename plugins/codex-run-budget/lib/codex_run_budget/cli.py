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
from .report_i18n import ReportText, human_text
from .survey import survey_summary, survey_transcripts
from .util import data_dir, data_path, parse_count, stable_hash


def _cli_text(text=None):
    """Return a CLI catalog without discovering locale more than once."""
    return text if isinstance(text, ReportText) else ReportText("en", domain="cli")


def _status_summary(run: dict[str, Any] | None, text: ReportText) -> str:
    """Human CLI status; Governor.status_text remains the hook contract."""
    if not run:
        return text("run_not_configured")
    status = str(run.get("status", "unknown"))
    status_key = {
        "running": "run_status_running",
        "halted": "run_status_halted",
        "off": "run_status_off",
    }.get(status, "run_status_unknown")
    status_label = text(status_key)
    spent = text.number(int(run.get("spent_tokens", 0)))
    maximum = text.number(int(run.get("max_tokens", 0)))
    remaining = text.number(max(0, int(run.get("max_tokens", 0)) - int(run.get("spent_tokens", 0))))
    summary = text(
        "run_status",
        status=status_label,
        epoch=run.get("epoch", "?"),
        spent=spent,
        maximum=maximum,
        remaining=remaining,
        tool_calls=text.number(int(run.get("tool_calls", 0))),
        max_tool_calls=text.number(int(run.get("max_tool_calls", 0))),
        active_agents=text.number(int(run.get("active_agents", 0))),
        max_agents=text.number(int(run.get("max_agents", 0))),
    )
    if run.get("halt_reason"):
        summary += text("run_reason", reason=str(run["halt_reason"]))
    if run.get("usage_status"):
        summary += text("run_usage", usage=str(run["usage_status"]))
    if run.get("usage_issues"):
        summary += text("run_issues", issues=", ".join(map(str, run["usage_issues"])))
    if run.get("pending_agents"):
        summary += text("run_pending", pending=text.number(int(run["pending_agents"])))
    return summary


def _help_requested(argv: list[str]) -> bool:
    # Argparse's own error/help handling remains untouched; this only decides
    # whether help strings should be loaded in the user's Codex language.
    return any(token in {"-h", "--help"} for token in argv)


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


def build_parser(
    text: ReportText | None = None, *, include_help: bool = True,
) -> argparse.ArgumentParser:
    # English is the deterministic library default.  ``main`` supplies a
    # resolved catalog only for an explicit help request.
    text = _cli_text(text) if include_help else lambda key: None
    parser = argparse.ArgumentParser(
        prog="run-budget",
        description=text("cli_description"),
    )
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help=text("cli_audit_help"))
    audit.add_argument("transcript", type=Path, nargs="+")

    survey = sub.add_parser("survey", help=text("cli_survey_help"))
    survey.add_argument("directory", type=Path, nargs="?")
    survey.add_argument("--days", type=float, default=7)
    survey.add_argument("--limit", type=int, default=200)
    output = survey.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help=text("cli_survey_json_help"))
    output.add_argument(
        "--lifecycle", action="store_true", help=text("cli_survey_lifecycle_help")
    )

    meter = sub.add_parser("meter", help=text("cli_meter_help"))
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
        help=text("cli_meter_thread_help"),
    )
    meter.add_argument("--json", action="store_true")
    meter.add_argument(
        "--no-save", action="store_true", help=text("cli_meter_nosave_help")
    )
    meter.add_argument("--directory", type=Path, help=text("cli_meter_directory_help"))
    meter.add_argument("--days", type=float, default=7, help=text("cli_meter_days_help"))
    meter.add_argument(
        "--limit", type=int, help=text("cli_meter_limit_help")
    )
    meter.add_argument(
        "--baseline", type=int, help=text("cli_meter_baseline_help")
    )
    meter.add_argument("--codex-binary", default="codex", help=text("cli_meter_codex_binary_help"))
    meter.add_argument(
        "--timeout", type=float, default=30, help=text("cli_meter_timeout_help")
    )

    report = sub.add_parser("report", help=text("cli_report_help"))
    report.add_argument(
        "view", nargs="?", choices=("help", "tasks", "task", "agents", "tree", "window")
    )
    report.add_argument(
        "--thread", action="append", default=[], help=text("cli_report_thread_help")
    )
    report.add_argument(
        "--all-tasks", action="store_true", help=text("cli_report_all_tasks_help")
    )
    report.add_argument(
        "--full", action="store_true", help=text("cli_report_full_help")
    )
    report.add_argument("--codex-home", type=Path, help=text("cli_report_codex_home_help"))
    report.add_argument("--windows", help=text("cli_report_windows_help"))
    report.add_argument("--timezone", default="UTC", help=text("cli_report_timezone_help"))
    report.add_argument("--since", help=text("cli_report_since_help"))
    report.add_argument("--until", help=text("cli_report_until_help"))
    report.add_argument("--directory", type=Path, help=text("cli_report_directory_help"))
    report.add_argument("--limit", type=int, help=text("cli_report_limit_help"))
    report.add_argument(
        "--detail-limit", type=int, default=20, help=text("cli_report_detail_limit_help")
    )
    report.add_argument("--format", choices=("markdown", "html", "json"), default="markdown")
    report.add_argument(
        "--output", type=Path, help=text("cli_report_output_help")
    )

    workflow = sub.add_parser("workflow", help=text("cli_workflow_help"))
    workflow.add_argument("action", nargs="?", choices=("observe", "targets"))
    workflow.add_argument("--thread", action="append", default=[])
    workflow.add_argument("--include-agents", action="store_true")
    workflow.add_argument("--limit", type=int, default=8)
    workflow.add_argument("--after", help=text("cli_workflow_after_help"))
    workflow.add_argument("--codex-home", type=Path)
    workflow.add_argument(
        "--json", action="store_true", help=text("cli_workflow_json_help")
    )

    automatic = sub.add_parser("auto-report", help=text("cli_auto_report_help"))
    automatic.add_argument("action", choices=("status", "enable", "disable", "list"))
    automatic.add_argument(
        "--threshold-seconds",
        type=float,
        default=0,
        help=text("cli_auto_report_threshold_help"),
    )

    listing = sub.add_parser("list", help=text("cli_list_help"))
    listing.add_argument("--limit", type=int, default=20)

    show = sub.add_parser("show", help=text("cli_show_help"))
    show.add_argument("run_id")
    show.add_argument("--json", action="store_true")

    events = sub.add_parser("events", help=text("cli_events_help"))
    events.add_argument("run_id")
    events.add_argument("--epoch", type=int)

    halt = sub.add_parser("halt", help=text("cli_halt_help"))
    halt.add_argument("run_id")
    halt.add_argument("--reason", default="operator requested HALT")

    resume = sub.add_parser("resume", help=text("cli_resume_help"))
    resume.add_argument("run_id")
    resume.add_argument("--tokens", help=text("cli_resume_tokens_help"))

    off = sub.add_parser("off", help=text("cli_off_help"))
    off.add_argument("run_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser_text = human_text("cli") if _help_requested(raw_argv) else None
    args = build_parser(parser_text, include_help=parser_text is not None).parse_args(raw_argv)
    # Machine JSON routes intentionally keep their existing shape and avoid a
    # locale preference read.  Human routes resolve once and pass the catalog
    # through their formatter.
    machine_route = (
        getattr(args, "json", False)
        or args.command in {"audit", "auto-report", "events"}
        or (args.command == "workflow" and args.action == "targets")
        or (args.command == "meter" and args.action == "rates")
        or (args.command == "report" and args.format == "json")
    )
    human = None
    if not machine_route:
        home = getattr(args, "codex_home", None)
        human = human_text("cli", home=home)
    if args.command == "workflow":
        from .workflow import run

        try:
            args.data_dir = args.data_dir or data_path()
            run(args, text=human)
            return 0
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, RecursionError):
            print(
                (human or _cli_text())("cli_workflow_error"),
                file=sys.stderr,
            )
            return 2
    if args.command == "auto-report":
        from .auto_report import configure, recent, settings

        try:
            root = args.data_dir or data_path()
            if args.action in ("enable", "disable"):
                result = configure(
                    root, enabled=args.action == "enable", threshold_seconds=args.threshold_seconds
                )
            else:
                result = recent(root) if args.action == "list" else settings(root)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except (OSError, ValueError, TypeError, sqlite3.Error):
            print((human or _cli_text())("cli_auto_report_error"), file=sys.stderr)
            return 2
    if args.command == "report":
        from .report_commands import run

        try:
            run(args, locale=human.locale if human else None)
            return 0
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, RecursionError):
            print(
                (human or _cli_text())("cli_report_error"),
                file=sys.stderr,
            )
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
                rendered = (
                    None
                    if args.json
                    else snapshot_summary(report, locale=(human.locale if human else "en"))
                )
            elif args.action == "report":
                report = meter_report(
                    root,
                    sessions=args.directory,
                    limit=args.limit if args.limit is not None else 200,
                    baseline_id=args.baseline,
                    thread_ids=args.thread,
                )
                rendered = (
                    None
                    if args.json
                    else report_summary(report, locale=(human.locale if human else "en"))
                )
            elif args.action in ("tasks", "estimate"):
                reader = meter_estimate if args.action == "estimate" else meter_tasks
                report = reader(
                    sessions=args.directory,
                    days=args.days,
                    limit=args.limit if args.limit is not None else 200,
                    thread_ids=args.thread,
                )
                rendered = None
                if not args.json:
                    rendered = (
                        estimate_summary(report, locale=(human.locale if human else "en"))
                        if args.action == "estimate"
                        else tasks_summary(report, locale=(human.locale if human else "en"))
                    )
            elif args.action == "rates":
                report = pricing_context()
                rendered = json.dumps(report, indent=2, sort_keys=True)
            else:
                report = load_snapshots(root, limit=args.limit if args.limit is not None else 20)
                rendered = None
                if not args.json:
                    rendered = (
                        "\n\n".join(
                            snapshot_summary(row, locale=(human.locale if human else "en"))
                            for row in report
                        )
                        or (human or _cli_text())("cli_no_saved_snapshots")
                    )
            print(json.dumps(report, indent=2, sort_keys=True) if args.json else rendered)
            return (
                2 if args.action == "snapshot" and report["source_status"] == "unavailable" else 0
            )
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError, RecursionError):
            print(
                (human or _cli_text())("cli_meter_error"),
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
                survey_summary(
                    report,
                    lifecycle_details=args.lifecycle,
                    locale=(human.locale if human else "en"),
                )
                if args.command == "survey" and not args.json
                else json.dumps(report, indent=2, sort_keys=True)
            )
            return 0
        except (OSError, ValueError):
            print(
                (human or _cli_text())("cli_audit_error"),
                file=sys.stderr,
            )
            return 2
    governor = Governor(args.data_dir or data_dir())
    ledger = governor.ledger
    try:
        if args.command == "list":
            for run in ledger.list_runs(args.limit):
                text = human or _cli_text()
                print(_status_summary(run, text) + f" {text('run_id')}: {run['run_id']}")
            return 0

        run_id = _resolve_run(ledger, args.run_id)
        if args.command == "show":
            run = ledger.get_run(run_id)
            if not run:
                raise ValueError(f"unknown run: {run_id}")
            print(
                json.dumps(_public_run(run), indent=2, sort_keys=True)
                if args.json
                else _status_summary(run, human or _cli_text())
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
        print(_status_summary(run, human or _cli_text()))
        return 0
    except (OSError, ValueError):
        print((human or _cli_text())("cli_run_error"), file=sys.stderr)
        return 2
    finally:
        governor.close()
