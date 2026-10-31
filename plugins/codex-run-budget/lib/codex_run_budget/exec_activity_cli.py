"""Explicit foreground observation and instrumented exec launch; no idle service."""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .exec_activity import record_launch, scan, tokens
from .util import stable_hash


def add_parser(commands, *, native_home_option=False):
    parser = commands.add_parser("exec-activity", help="Observe codex exec in one project")
    actions = parser.add_subparsers(dest="activity_action", required=True)
    for action in ("list", "watch", "run"):
        sub = actions.add_parser(action)
        sub.add_argument("--project", type=Path, required=True, help="Exact working directory")
        if native_home_option:
            sub.add_argument("--codex-home", type=Path)
        if action in {"list", "watch"}:
            sub.add_argument("--hours", type=float, default=24)
            sub.add_argument("--limit", type=int, default=50)
            sub.add_argument("--format", choices=("json", "markdown"), default="markdown")
        if action == "watch":
            sub.add_argument("--interval", type=float, default=2)
            sub.add_argument("--duration", type=float, default=60,
                             help="Foreground seconds; 0 runs until interrupted")
        if action == "run":
            sub.add_argument("--parent-task",
                             help="Explicit launcher attribution, not native lineage")
            sub.add_argument("--codex-binary", default="codex")
            sub.add_argument("exec_args", nargs=argparse.REMAINDER,
                             help="After --: codex exec arguments; JSON output is enabled")


def render(report, format="markdown"):
    if format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = ["Codex exec activity · " + report["status"], "",
             "Session counters and launcher invocation usage are separate from parent Task totals.",
             "Last-turn state does not prove process liveness. Unknown is not zero.", "",
             "| Started (UTC) | Exec | Last evidence | Parent attribution | Tokens | Scope |",
             "| --- | --- | --- | --- | ---: | --- |"]
    for row in report["activities"]:
        usage = row.get("usage")
        parent = row.get("parent_hash")
        attribution = row["attribution"] + (" · " + parent[:12] if parent else "")
        state = row.get("launcher_state", row["state"])
        if row.get("exit_code") is not None:
            state += " (" + str(row["exit_code"]) + ")"
        amount = str(usage["total"]) if usage else "unknown"
        if row.get("usage_status") != "observed":
            amount += " (" + row.get("usage_status", "unavailable") + ")"
        started = datetime.fromtimestamp(row["started"], timezone.utc).isoformat(timespec="seconds")
        lines.append("| " + " | ".join((started, row["key"][:12], state, attribution, amount,
                     row.get("usage_scope", "unknown"))) + " |")
    if not report["activities"]:
        lines.append("\nNo matching observations. This does not prove no exec ran.")
    if report["issues"]:
        lines.append("\nCoverage: " + ", ".join(report["issues"]))
    return "\n".join(lines)


def _emit(value):
    try:
        print(json.dumps(value, ensure_ascii=True), file=sys.stderr, flush=True)
    except OSError:
        pass


def launch(args, root):
    """Stream Codex JSON unchanged; store only lifecycle, hashes and usage.

    The wrapper is opt-in and runs only the user's supplied exec invocation.
    Telemetry errors never prevent or change that invocation's exit status.
    """
    arguments = list(args.exec_args)
    if arguments[:1] == ["--"]:
        arguments.pop(0)
    if not arguments:
        raise ValueError("exec arguments required")
    if any(x in {"--cd", "-C"} or x.startswith(("--cd=", "-C")) for x in arguments):
        raise ValueError("use --project for the working directory")
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError("project unavailable")
    parent = args.parent_task or os.environ.get("CODEX_THREAD_ID")
    if parent:
        try:
            parent = str(uuid.UUID(parent))
        except ValueError:
            if args.parent_task:
                raise
            parent = None
    attribution = "launcher_argument" if args.parent_task else "launcher_environment"
    key = stable_hash(str(uuid.uuid4()))
    task, usage, telemetry_failed, completions = None, None, False, 0
    stream_turn = 0
    stream_active, identity_conflict, unbound_gap, stream_limited = False, False, False, False
    terminal_hash = None

    def observe(event):
        nonlocal usage, stream_limited
        if event.get("type") == "stream.incomplete":
            stream_limited, usage = True, None
        if task is None:
            return
        try:
            from .governor import Governor

            result = Governor.dispatch({
                "hook_event_name": "ExecObservation", "session_id": task,
                "turn_id": stable_hash([key, stream_turn]), "cwd": str(project),
                "stream_event": event,
            }, root)
            advice = (result or {}).get("hookSpecificOutput", {}).get("additionalContext")
            if advice:
                _emit({"optimizer": "advisory", "message": advice})
        except Exception:
            # Stream observation cannot change execution, stdout or the child's exit status.
            pass

    def save(state, code=None):
        nonlocal telemetry_failed
        try:
            record_launch(root, key, project=project, parent=parent, attribution=attribution,
                          task=task, state=state, exit_code=code, usage=usage)
        except Exception:
            if not telemetry_failed:
                _emit({"exec_activity": "recording_unavailable", "key": key})
            telemetry_failed = True

    def consume(event):
        nonlocal task, usage, completions, stream_turn, stream_active
        nonlocal identity_conflict, unbound_gap, terminal_hash
        gap = {"type": "stream.incomplete"}
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            if task is None:
                unbound_gap = True
            observe(gap)
            return
        kind = event["type"]
        if kind == "thread.started":
            try:
                identifier = str(uuid.UUID(event["thread_id"]))
            except (ValueError, KeyError, TypeError, AttributeError):
                unbound_gap = True
                observe(gap)
                return
            if task is None:
                task = identifier
                save("started")
            elif task != identifier:
                identity_conflict, usage = True, None
                observe(gap)
            return
        if task is None:
            unbound_gap = True
            return
        if identity_conflict:
            return
        if kind == "turn.started":
            if stream_active:
                observe(gap)
                return
            stream_turn += 1
            stream_active = True
            terminal_hash = None
            observe(event)
            if unbound_gap:
                observe(gap)
                unbound_gap = False
        elif kind in {"turn.completed", "turn.failed"}:
            fingerprint = stable_hash(event)
            if not stream_active:
                if terminal_hash == fingerprint:
                    return
                usage = None
                observe(gap)
                return
            stream_active, terminal_hash = False, fingerprint
            if kind == "turn.completed":
                completions += 1
                usage = (tokens(event.get("usage"))
                         if completions == 1 and not stream_limited else None)
            else:
                usage = None
            observe(event)
        elif kind == "item.completed":
            observe(event)

    def consume_line(raw):
        try:
            consume(json.loads(raw))
        except (ValueError, TypeError, RecursionError):
            consume(None)

    save("started")
    env = dict(os.environ)
    if getattr(args, "codex_home", None):
        env["CODEX_HOME"] = str(args.codex_home.expanduser().resolve())
    command = [args.codex_binary, "exec", "--json", "--cd", str(project), *arguments]
    try:
        process = subprocess.Popen(command, cwd=project, env=env, stdout=subprocess.PIPE)
    except OSError:
        save("launch_failed", 127)
        _emit({"exec_activity": "launch_failed", "key": key})
        return 127
    _emit({"exec_activity": "started", "key": key,
           "project_hash": stable_hash(str(project)), "attribution": attribution if parent
           else "unknown"})
    try:
        # Bounded line parsing: oversized lines still reach stdout unchanged.
        pending, overflow = bytearray(), False
        while True:
            chunk = process.stdout.read1(65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            for part in chunk.splitlines(keepends=True):
                if not overflow:
                    pending.extend(part)
                    if len(pending) > 256 * 1024:
                        pending.clear()
                        overflow = True
                if not part.endswith(b"\n"):
                    continue
                if not overflow:
                    consume_line(pending)
                else:
                    consume(None)
                pending.clear()
                overflow = False
        code = process.wait()
        if overflow:
            consume(None)
        elif pending:
            consume_line(pending)
        if stream_active or completions == 0:
            observe({"type": "stream.incomplete"})
    except (KeyboardInterrupt, BrokenPipeError):
        observe({"type": "turn.failed"})
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        save("interrupted", 130)
        return 130
    finally:
        process.stdout.close()
    save("exited", code)
    _emit({"exec_activity": "exited", "key": key, "exit_code": code,
           "recording": "unavailable" if telemetry_failed else "recorded"})
    return code if code >= 0 else 128 - code


def run(args, root):
    try:
        if args.activity_action == "run":
            return launch(args, root)
        if not math.isfinite(args.hours) or not 0 < args.hours <= 8760:
            raise ValueError("invalid window")
        if args.activity_action == "watch" and (
            not math.isfinite(args.interval) or not 0.2 <= args.interval <= 60
            or not math.isfinite(args.duration) or not 0 <= args.duration <= 86400
        ):
            raise ValueError("invalid watch timing")
        since = time.time() - args.hours * 3600
        start, previous, unavailable = time.monotonic(), None, 0
        while True:
            report = scan(args.project, root=root, home=getattr(args, "codex_home", None),
                          since=since, limit=args.limit)
            fingerprint = stable_hash(report)
            if fingerprint != previous:
                print(render(report, args.format), flush=True)
                previous = fingerprint
            if args.activity_action != "watch":
                return 0 if report["status"] != "unavailable" else 1
            unavailable = unavailable + 1 if report["status"] == "unavailable" else 0
            if unavailable >= 3:
                _emit({"exec_activity": "watch_stopped", "reason": "repeated_unavailable",
                       "attempts": unavailable})
                return 1
            if args.duration and time.monotonic() - start >= args.duration:
                return 1 if unavailable else 0
            interval = (min(60, args.interval * 2 ** min(unavailable, 4))
                        if unavailable else args.interval)
            remaining = (args.duration - (time.monotonic() - start)
                         if args.duration else interval)
            time.sleep(max(0, min(interval, remaining)))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, sqlite3.Error, RecursionError):
        _emit({"status": "unavailable",
               "reason": "Check project, activity options and local state."})
        return 1
