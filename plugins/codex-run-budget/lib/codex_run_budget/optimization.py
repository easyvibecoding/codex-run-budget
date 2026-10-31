"""Codex-specific, deterministic observations; raw hook data never leaves this fold.

This is an advisory interface, not another budget. Code-mode wrappers remain opaque:
text mentioning a tool call is not evidence that the tool executed.
"""
from __future__ import annotations

import math
import os
import re
import shlex
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .util import stable_hash

WINDOW = 24
MIN_CALLS = 8
MIN_SAMPLES = 5
MAX_CALLS = 512
MAX_TURNS = 500
CAPABILITIES = ("collaboration", "goals", "image_media")
EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "Interrupt", "ExecObservation"}
INTERNAL_ENV = "CODEX_RUN_BUDGET_OBSERVER_INTERNAL"
_OBSERVING = ContextVar("codex_optimizer_observing", default=False)
_WAIT = {"wait", "write_stdin", "sleep", "wait_agent", "wait_threads"}
_EDIT = {"apply_patch", "edit", "write", "multiedit", "str_replace_editor"}
_READ = {"read", "view", "grep", "glob"}
_EXEC = {"exec_command", "shell", "shell_command", "local_shell", "bash"}
_CAPABILITY = {
    **dict.fromkeys(("spawn_agent", "send_message", "send_input", "followup_task",
                     "resume_agent", "close_agent", "interrupt_agent", "list_agents",
                     "wait_agent"), "collaboration"),
    **dict.fromkeys(("create_goal", "get_goal", "update_goal"), "goals"),
    **dict.fromkeys(("view_image", "image", "audio", "generated_image", "imagegen"),
                    "image_media"),
}
_ERRORS = (
    ("missing_executable", re.compile(r"command not found|not recognized as .*command|"
                                     r"No such file or directory.*(?:python|node|bun)", re.I)),
    ("missing_module", re.compile(r"ModuleNotFoundError|No module named|Cannot find module", re.I)),
    ("permission", re.compile(r"Permission denied|Operation not permitted|EACCES|EPERM", re.I)),
    ("timeout", re.compile(r"TimeoutError|ETIMEDOUT|timed out", re.I)),
    ("network", re.compile(r"Could not resolve|ENOTFOUND|ECONNREFUSED|Connection refused|"
                          r"Network is unreachable", re.I)),
)
_FAILURE_LINE = re.compile(r"\b(?:\w*Error|FAILED|FAIL|Exception|fatal)\b|"
                           r"command not found|Permission denied|Could not resolve", re.I)
_VOLATILE = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s\"']+|0x[0-9a-f]+|"
                       r"\b[0-9a-f]{16,}\b|\d+(?:\.\d+)*", re.I)


def _name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    # Native names, namespaces and MCP names; never persist a custom tool name.
    return value[:200].lower().rsplit(".", 1)[-1].rsplit("__", 1)[-1]


def _intent(name: str, inputs: Any) -> tuple[str, str | None, bool]:
    capability = _CAPABILITY.get(name)
    if name in _WAIT:
        return "wait", capability, False
    if capability:
        return "capability", capability, False
    if name == "exec":
        return "opaque", None, False
    if name in _EDIT:
        return "edit", None, False
    if name in _READ:
        return "read", None, False
    if name not in _EXEC:
        return "other", None, False
    command = inputs.get("cmd", inputs.get("command")) if isinstance(inputs, dict) else None
    if not isinstance(command, str) or len(command) > 16384:
        return "execution", None, False
    # A compound shell command can hide a failing check behind a successful final command.
    # Such commands are still observed, but cannot establish a successful-check baseline.
    if re.search(r"[\n;|&<>`]|\$\(", command):
        return "execution", None, False
    try:
        words = shlex.split(command)
    except ValueError:
        return "execution", None, False
    if not words:
        return "execution", None, False
    executable = words[0].rsplit("/", 1)[-1]
    arguments = words[1:]
    is_python = bool(re.fullmatch(r"python(?:\d+(?:\.\d+)?)?", executable))
    if is_python and arguments and Path(arguments[0]).name == "run_budget.py":
        # The public read/measurement commands must not feed their own retry detector.
        # Run budgets still count and govern this call normally.
        commands = [word for word in arguments[1:] if word in {
            "optimizer", "report", "survey", "audit", "meter", "workflow", "exec-activity"}]
        if commands and not (commands[0] == "exec-activity" and "run" in arguments[1:]):
            return "observer", None, False
    if executable in {"sed", "perl"} and any(x.startswith(("-i", "-pi")) for x in arguments):
        return "edit", None, False
    if executable == "git" and arguments[:1] == ["apply"]:
        return "edit", None, False
    check = executable in {"pytest", "py.test"}
    check |= executable == "ruff" and arguments[:1] == ["check"]
    check |= (is_python
              and arguments[:2] in (["-m", "unittest"], ["-m", "pytest"]))
    check |= (executable in {"npm", "pnpm", "bun", "yarn"}
              and (arguments[:1] == ["test"] or arguments[:2] in (
                  ["run", "test"], ["run", "check"], ["run", "lint"], ["run", "build"])))
    check |= executable in {"cargo", "go"} and arguments[:1] in (["test"], ["check"])
    if any(word.split("=", 1)[0] in {
        "--help", "-h", "--version", "-V", "--collect-only", "--co",
        "--show-files", "--show-settings", "--list-tests", "--listTests",
    } for word in arguments) or "$" in command:
        check = False
    return "execution", None, check


def _result(response: Any, inputs_hash: str) -> dict[str, Any]:
    outcome = "unknown"
    text = ""
    if isinstance(response, dict):
        structured = response.get("structuredContent")
        codes = [value.get(key) for value in (response, structured) if isinstance(value, dict)
                 for key in ("exit_code", "exitCode") if type(value.get(key)) is int]
        states = {code == 0 for code in codes}
        if len(states) == 1:
            outcome = "passed" if True in states else "failed"
        if response.get("isError") is True or response.get("is_error") is True:
            outcome = "failed"
        # No inference from missing flags, the word 'error' in a read, or exit code None.
        pieces = [response.get(key) for key in ("output", "stdout", "stderr", "error")]
        if isinstance(structured, dict):
            pieces.extend(structured.get(key) for key in ("output", "stdout", "stderr", "error"))
        content = response.get("content")
        if isinstance(content, list):
            pieces.extend(item.get("text") for item in content[:32] if isinstance(item, dict))
        text = "\n".join(piece[:32768] for piece in pieces if isinstance(piece, str))[:65536]
    error_class, fingerprint, basis = None, None, None
    if outcome == "failed":
        error_class = next((kind for kind, pattern in _ERRORS if pattern.search(text)), "other")
        line = next((line for line in text.splitlines() if _FAILURE_LINE.search(line)), None)
        # No diagnostic line: keep failures with unrelated inputs separate.
        normalized = _VOLATILE.sub("#", line[:2048]).strip().lower() if line else inputs_hash
        fingerprint = stable_hash(["failure-v1", error_class, normalized])
        basis = "diagnostic" if line else "input"
    return {"outcome": outcome, "failure_hash": fingerprint, "error_class": error_class,
            "failure_basis": basis}


def signal(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Allowlist and hash identities before passing anything to the observation ledger."""
    event = payload.get("hook_event_name")
    if not isinstance(event, str) or event not in EVENTS:
        return None
    values = [payload.get(key) for key in ("session_id", "turn_id", "cwd")]
    if any(not isinstance(value, str) or not 0 < len(value) <= 4096 for value in values):
        return None
    session, turn, cwd = values
    project = Path(cwd)
    if not project.is_absolute():
        return None
    agent = payload.get("agent_id")
    source = payload.get("transcript_path")
    actor = source if isinstance(source, str) and source else agent or session
    if not isinstance(actor, str) or len(actor) > 4096:
        return None
    result = {
        "event": event, "project_hash": stable_hash(str(project.resolve())),
        "task_hash": stable_hash(session),
        "turn_hash": stable_hash([session, agent if isinstance(agent, str) else None, actor, turn]),
        "role": "agent" if agent else "task",
    }
    if event == "ExecObservation":
        stream = payload.get("stream_event")
        result["role"] = "exec"
        # Separate invocation/turn identity: these events never impersonate native hooks
        # or invoke budget admissions after a command has already executed.
        result["turn_hash"] = stable_hash(["exec-stream", session, turn])
        if not isinstance(stream, dict) or not isinstance(stream.get("type"), str):
            return {**result, "event": "Incomplete", "issue_code": "invalid_stream_event"}
        kind = stream["type"]
        lifecycle = {"turn.started": "UserPromptSubmit", "turn.completed": "Stop",
                     "turn.failed": "Interrupt", "stream.incomplete": "Incomplete"}
        if kind in lifecycle:
            result["event"] = lifecycle[kind]
            if kind == "stream.incomplete":
                result["issue_code"] = "stream_gap"
            return result
        item = stream.get("item")
        if kind != "item.completed":
            return None
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            return {**result, "event": "Incomplete", "issue_code": "invalid_stream_item"}
        if item["type"] not in {"command_execution", "file_change"}:
            # Agent messages are text. Other executed surfaces are outside this reader.
            if item["type"] in {"agent_message", "reasoning", "todo_list"}:
                return None
            return {**result, "event": "Incomplete", "issue_code": "unsupported_stream_item"}
        if ("status" in item and item["status"] not in ("completed", "failed", "in_progress")):
            return {**result, "event": "Incomplete", "issue_code": "invalid_stream_status"}
        identity = item.get("id")
        if not isinstance(identity, str) or not 0 < len(identity) <= 4096:
            return {**result, "event": "Incomplete", "issue_code": "missing_call_identity"}
        if item.get("type") == "command_execution":
            command = item.get("command")
            if not isinstance(command, str):
                return {**result, "event": "Incomplete", "issue_code": "missing_command"}
            inputs = {"cmd": command}
            tool_kind, capability, check = _intent("exec_command", inputs)
            fingerprint = stable_hash(["exec_command", inputs])
            result.update(event="CompletedExecution", call_hash=stable_hash(identity),
                          input_hash=fingerprint, kind=tool_kind, capability=capability,
                          is_check=check, has_input=True, has_name=True,
                          response_hash=stable_hash([item.get("exit_code"),
                                                     item.get("aggregated_output")]))
            result.update(_result({"exit_code": item.get("exit_code"),
                                   "output": item.get("aggregated_output")}, fingerprint))
            if item.get("status") == "in_progress":
                if item.get("exit_code") is not None:
                    return {**result, "event": "Incomplete", "issue_code": "conflicting_status"}
                result.update(outcome="pending", failure_hash=None, error_class=None,
                              failure_basis=None)
            return result
        if item.get("type") == "file_change":
            if not isinstance(item.get("changes"), list):
                return {**result, "event": "Incomplete", "issue_code": "missing_changes"}
            result.update(event="CompletedExecution", call_hash=stable_hash(identity),
                          input_hash=stable_hash(item.get("changes")), kind="edit",
                          capability=None, is_check=False, has_input=True, has_name=True,
                          response_hash=stable_hash(item.get("status")), outcome="unknown",
                          failure_hash=None, error_class=None, failure_basis=None)
            return result
        return None
    if event in {"PreToolUse", "PostToolUse"}:
        identity = payload.get("tool_use_id")
        if not isinstance(identity, str) or not 0 < len(identity) <= 4096:
            return {**result, "event": "Incomplete", "issue_code": "missing_call_identity"}
        inputs = payload.get("tool_input")
        name = _name(payload.get("tool_name"))
        kind, capability, check = _intent(name, inputs)
        fingerprint = stable_hash([name, inputs])
        result.update(call_hash=stable_hash(identity), input_hash=fingerprint, kind=kind,
                      capability=capability, is_check=check,
                      has_input="tool_input" in payload, has_name=bool(name))
        if event == "PostToolUse":
            if "tool_response" not in payload:
                return {**result, "event": "Incomplete", "issue_code": "missing_result"}
            response = payload.get("tool_response")
            result.update(_result(response, fingerprint), response_hash=stable_hash(response))
    return result


def baseline(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """A successful local check is a proxy, never workflow acceptance or a billing sample."""
    sizes = sorted(row["completed_calls"] for row in turns if row["check_sample"])
    p90 = sizes[math.ceil(0.90 * len(sizes)) - 1] if len(sizes) >= MIN_SAMPLES else None
    return {"samples": len(sizes), "p90_calls": p90,
            "gate_calls": max(MIN_CALLS, min(24, math.ceil(p90 * 0.6))) if p90 else MIN_CALLS,
            "basis": "stopped_turn_with_successful_local_check_not_workflow_acceptance"}


def loop_warning(calls: list[dict[str, Any]], history: dict[str, Any],
                 warnings: int, last_warning: int) -> str | None:
    calls = [call for call in calls if call["kind"] != "observer"]
    if warnings >= 2 or len(calls) < history["gate_calls"]:
        return None
    if warnings and len(calls) - last_warning < MIN_CALLS:
        return None
    # A successful recognized check resets the advisory segment. Reads and waits do not fail.
    since = 0
    for index, call in enumerate(calls):
        if call["is_check"] and call["outcome"] == "passed":
            since = index + 1
    recent = calls[since:][-WINDOW:]
    if not recent or recent[-1]["kind"] != "execution" or recent[-1]["outcome"] != "failed":
        return None
    failures = [call for call in recent if call["kind"] == "execution"
                and call["outcome"] == "failed" and call["failure_hash"]]
    if len(failures) < 3:
        return None
    repeated = Counter(call["failure_hash"] for call in failures)
    inputs = {call["input_hash"] for call in failures}
    edits = sum(call["kind"] == "edit" for call in recent)
    if repeated[failures[-1]["failure_hash"]] < 3 or (len(inputs) < 2 and edits < 2):
        return None
    fingerprints = [call["failure_hash"] for call in failures]
    cycle = any(len(fingerprints) >= period * 3
                and len(set(fingerprints[-period:])) > 1
                and fingerprints[-period * 3:] == fingerprints[-period:] * 3
                for period in (2, 3))
    return (
        "Codex progress advisory (" + ("failure_cycle" if cycle else "repeated_failure")
        + "): the same failure signature has recurred across changed "
        "calls or edits. Recheck the underlying cause before another retry and choose a "
        "different approach when appropriate. This is an observation, not a stall verdict; "
        "intentional verification may repeat. The shared run budget is unchanged."
    )


def check_sample(calls: list[dict[str, Any]], *, ended: str, limited: bool) -> bool:
    if ended != "stopped" or limited or not calls:
        return False
    if any(call["kind"] in {"opaque", "other", "observer"} for call in calls):
        return False
    last_edit = max((index for index, call in enumerate(calls) if call["kind"] == "edit"),
                    default=-1)
    checks = [index for index, call in enumerate(calls)
              if call["is_check"] and call["outcome"] == "passed" and index > last_edit]
    if not checks:
        return False
    return not any(call["kind"] == "execution" for call in calls[checks[-1] + 1:])


def handle(payload: dict[str, Any], root: Path) -> str | None:
    if (_OBSERVING.get() or os.environ.get(INTERNAL_ENV) == "1"
            or not isinstance(payload.get("hook_event_name"), str)
            or payload["hook_event_name"] not in EVENTS):
        return None
    from .ledger import ObservationHealth, OptimizationLedger

    token = _OBSERVING.set(True)
    health, ticket, observation = None, None, None
    try:
        observation = signal(payload)
        if observation is None and payload["hook_event_name"] == "ExecObservation":
            return None
        health = ObservationHealth(root / "optimizer-health.sqlite3")
        ticket = health.reserve()
        if ticket is None:
            return None
        if observation is None:
            raise ValueError("observation identity unavailable")
        observation["health_epoch"] = ticket["epoch"]
        observation["gap_since"] = ticket["gap_since"]
        observation["gap_until"] = ticket["gap_until"]
        ledger = OptimizationLedger(root / "optimizer.sqlite3")
        try:
            message = ledger.observe(observation)
        finally:
            ledger.close()
        health.finish(ticket)
        return message
    except Exception as error:
        if health is not None and ticket is not None:
            try:
                health.finish(ticket, error=error)
            except Exception:
                pass
        elif observation is not None:
            # A health-store outage must not silently leave the evidence store complete.
            # This independent best-effort write is attempted once, without recursion.
            ledger = None
            try:
                ledger = OptimizationLedger(root / "optimizer.sqlite3")
                ledger.observe({**observation, "event": "Incomplete",
                                "issue_code": "health_unavailable"})
            except Exception:
                pass
            finally:
                if ledger is not None:
                    ledger.close()
        return None
    finally:
        try:
            if health is not None:
                health.close()
        finally:
            _OBSERVING.reset(token)
