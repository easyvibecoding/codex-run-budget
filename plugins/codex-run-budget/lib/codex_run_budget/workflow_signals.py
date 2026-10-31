"""Bounded native tool evidence and response advice, without workflow effects."""
from __future__ import annotations

import shlex
from pathlib import Path

from .optimization import _intent, _result
from .util import stable_hash

MAX_FAILURES = 16
MAX_SEEN = 64


def _observer_command(command):
    try:
        words = shlex.split(command) if isinstance(command, str) else command
        if not isinstance(words, list) or not all(isinstance(v, str) for v in words):
            return False
        if (len(words) == 3 and Path(words[0]).name in {"sh", "bash", "zsh"}
                and words[1] in {"-c", "-lc"}):
            words = shlex.split(words[2])
        joined = shlex.join(words)
        if _intent("exec_command", {"cmd": joined})[0] == "observer":
            return True
        arguments = words[1:]
        while arguments and arguments[0] in {"-I", "-B", "-u"}:
            arguments = arguments[1:]
        return (len(arguments) > 1 and Path(words[0]).name.startswith("python")
                and (arguments[0].endswith(".pyz") or Path(arguments[0]).name == "hook.py")
                and any(flag in arguments for flag in ("--preview", "--reconcile")))
    except (TypeError, ValueError):
        return False


def fold(record, identifier, state, *, at=None):
    """Only native completed items with explicit owner/turn/call identity qualify."""
    payload = record.get("payload", {})
    if (record.get("type") != "event_msg" or payload.get("type") != "item_completed"
            or payload.get("thread_id") != identifier):
        return
    turn, item = payload.get("turn_id"), payload.get("item")
    if not isinstance(turn, str) or not turn or not isinstance(item, dict):
        return
    call = item.get("id")
    if not isinstance(call, str) or not 0 < len(call) <= 512:
        return
    kind = item.get("type")
    if kind == "CommandExecution":
        inputs = item.get("command")
        if _observer_command(inputs):
            state["excluded_observer_items"] = state.get("excluded_observer_items", 0) + 1
            return
        response = {"exit_code": item.get("exit_code"),
                    "output": item.get("aggregated_output")}
    elif kind == "McpToolCall":
        inputs = [item.get("server"), item.get("tool"), item.get("arguments")]
        result = item.get("result")
        response = dict(result) if isinstance(result, dict) else {}
        if response.get("isError") is False:
            response["exit_code"] = 0
        if item.get("status") == "failed":
            response["isError"] = True
    else:
        return
    input_hash = stable_hash([kind, inputs])
    outcome = _result(response, input_hash)
    key = stable_hash([identifier, turn, call])
    digest = stable_hash([input_hash, outcome])
    seen = state.setdefault("seen", [])
    previous = next((entry for entry in seen if entry[0] == key), None)
    if previous:
        if previous[1] != digest:
            state["limited"] = True
        return
    if at is None or at < state.get("last_outcome_at", at):
        state["limited"] = True
    if at is not None:
        state["last_outcome_at"] = max(at, state.get("last_outcome_at", at))
    seen.append([key, digest])
    del seen[:-MAX_SEEN]
    counts = state.setdefault("counts", {"passed": 0, "failed": 0, "unknown": 0})
    counts[outcome["outcome"]] = min(1000000, counts[outcome["outcome"]] + 1)
    failures = state.setdefault("failures", [])
    if outcome["outcome"] == "passed":
        resolved = [v["failure_hash"] for v in failures if v["input_hash"] == input_hash
                    and at is not None and v.get("last_at") is not None and at >= v["last_at"]]
        state.setdefault("resolved", []).extend(resolved)
        failures[:] = [v for v in failures if v["input_hash"] != input_hash
                       or at is None or v.get("last_at") is None or at < v["last_at"]]
    elif outcome["outcome"] == "failed":
        found = next((v for v in failures if v["input_hash"] == input_hash
                      and v["failure_hash"] == outcome["failure_hash"]), None)
        if found:
            found["count"] = min(1000000, found["count"] + 1)
            found["last_at"] = (max(at, found["last_at"])
                                if at is not None and found.get("last_at") is not None else None)
        elif len(failures) < MAX_FAILURES:
            failures.append({"input_hash": input_hash, "failure_hash": outcome["failure_hash"],
                             "error_class": outcome["error_class"],
                             "failure_basis": outcome["failure_basis"], "count": 1,
                             "last_at": at})
        else:
            state["limited"] = True


def detect(tasks):
    """Evidence-backed signals plus fixed response steps; nothing executes them."""
    signals, responses, shared = [], [], {}
    for row in tasks:
        key, observed = row["thread_hash"], row["observation"]
        health = row["observation_health"]
        if health["state"] == "backoff":
            signals.append({"task": key, "kind": "observation_backoff"})
            responses.append({"task": key, "action": "retry_observation_after",
                              "not_before": health["next_probe_at"], "effects": "observation_only"})
        if observed.get("source_status") != "observed":
            responses.append({"task": key, "action": "verify_exact_native_source",
                              "effects": "read_only"})
            continue
        if observed.get("append_status") == "unproven" and observed.get("has_baseline"):
            signals.append({"task": key, "kind": "observation_coverage_gap"})
        tools = observed.get("tool_evidence", {})
        if tools.get("limited") or tools.get("counts", {}).get("unknown"):
            signals.append({"task": key, "kind": "tool_evidence_incomplete"})
        for failure in tools.get("failures", []):
            signature = failure["failure_hash"]
            base = {"task": key, "failure_hash": signature}
            signals.append({**base, "kind": "tool_failure_observed"})
            if failure["count"] >= 3:
                signals.append({**base, "kind": "repeated_tool_failure"})
            responses.append({**base, "action": "inspect_native_tool_failure",
                              "error_class": failure["error_class"], "effects": "read_only"})
            if failure["failure_basis"] == "diagnostic":
                shared.setdefault(signature, set()).add(key)
    for signature, members in shared.items():
        if len(members) < 2:
            continue
        for key in sorted(members):
            signals.append({"task": key, "kind": "cross_task_failure",
                            "failure_hash": signature})
        responses.append({"tasks": sorted(members), "failure_hash": signature,
                          "action": "inspect_shared_dependency", "effects": "read_only",
                          "causality": "unproven"})
    # Several inputs can share one diagnostic signature.
    unique = {stable_hash(s): s for s in signals}
    return list(unique.values()), responses
