"""Explicit, project-scoped optimization reports and local Codex input probes."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from .ledger import ObservationHealth, OptimizationLedger
from .optimization import CAPABILITIES, INTERNAL_ENV, baseline
from .util import stable_hash

_TOGGLES = {
    "collaboration": ["include_collaboration_mode_instructions=false", "agents.enabled=false",
                      "features.multi_agent=false"],
    "goals": ["features.goals=false"],
    "image_media": ["features.view_image=false"],
}
_ENV_ADVICE = {
    "missing_executable": "Check the available interpreter and executable before retrying.",
    "missing_module": (
        "Check existing environments and dependencies before installing another copy."),
    "permission": "Check the exact permission requirement before repeating the operation.",
    "timeout": "Check timeout limits and progress evidence before another bounded retry.",
    "network": "Check connectivity and the execution environment before another network retry.",
}


def add_parser(commands):
    parser = commands.add_parser("optimizer", help="Codex progress and capability observations")
    actions = parser.add_subparsers(dest="optimizer_action", required=True)
    for action in ("status", "enable", "disable", "report", "measure"):
        sub = actions.add_parser(action)
        sub.add_argument("--project", type=Path, default=Path.cwd(),
                         help="Exact checkout directory; no cross-project aggregation")
        sub.add_argument("--channel", choices=("hooks", "exec"), default="hooks",
                         help="Keep native hooks separate from explicit exec stream observations")
        if action == "measure":
            sub.add_argument("--capability", action="append", choices=CAPABILITIES, required=True)
            sub.add_argument("--codex-binary", default="codex")


def report(root: Path, project: Path, channel="hooks") -> dict:
    project = project.expanduser().resolve()
    value = OptimizationLedger.snapshot(root / "optimizer.sqlite3", stable_hash(str(project)))
    health = ObservationHealth.snapshot(root / "optimizer-health.sqlite3")
    turns, calls = value.pop("turns"), value.pop("calls")
    for turn in turns:
        if (health.get("epoch") is not None and turn["health_epoch"] < health["epoch"]
                and (turn["ended"] == "active" or (
                    turn["created"] <= (health.get("gap_until") or 0)
                    and turn["updated"] >= (health.get("gap_since") or float("inf"))))):
            turn.update(limited=1, check_sample=0,
                        issue_code=turn.get("issue_code") or "observer_gap")
    turns = [turn for turn in turns if (turn["role"] == "exec") == (channel == "exec")]
    selected = {turn["turn_hash"] for turn in turns}
    calls = [call for call in calls if call["turn_hash"] in selected]
    value["status"] = "observed" if turns else "no_observations"
    ended = [turn for turn in turns if turn["ended"] != "active"]
    tasks = {turn["task_hash"] for turn in ended}
    incomplete = (any(turn["limited"] or not turn["started"] for turn in turns)
                  or health["state"] not in {"healthy", "no_observations"})
    opaque = sum(call["kind"] == "opaque" for call in calls)
    unclassified = sum(call["kind"] == "other" for call in calls)
    uses = Counter(call["capability"] for call in calls if call["capability"])
    capabilities = []
    for capability in CAPABILITIES:
        status = "observed_use" if uses[capability] else "insufficient_history"
        if not uses[capability] and len(ended) >= 5 and len(tasks) >= 2:
            status = ("coverage_incomplete" if incomplete or opaque or unclassified
                      or channel == "exec" else "review_configuration")
        capabilities.append({"capability": capability, "observed_attempts": uses[capability],
                             "status": status, "loaded_catalog": "unknown"})
    environment = []
    for category, advice in _ENV_ADVICE.items():
        affected = {call["turn_hash"] for call in calls if call["error_class"] == category}
        roots = {turn["task_hash"] for turn in turns if turn["turn_hash"] in affected}
        if len(affected) >= 3 and len(roots) >= 2:
            environment.append({"category": category, "observed_turns": len(affected),
                                "advice": advice})
    value.update(
        schema_version=2, project_hash=stable_hash(str(project)),
        retained_turns=len(turns), ended_turns=len(ended), observed_tasks=len(tasks),
        observed_completed_calls=sum(call["completed_order"] is not None for call in calls),
        unknown_outcomes=sum(call["outcome"] == "unknown" for call in calls),
        pending_calls=sum(call["outcome"] == "pending" for call in calls),
        observer_calls=sum(call["kind"] == "observer" for call in calls),
        opaque_calls=opaque, unclassified_calls=unclassified,
        limited_turns=sum(bool(turn["limited"]) for turn in turns),
        advisories=sum(turn["warnings"] for turn in turns),
        coverage_issues=dict(Counter(turn["issue_code"] for turn in turns
                                     if turn.get("issue_code"))),
        sensor_health=health,
        evidence_status=("unknown" if not turns else "partial" if incomplete or opaque
                         or unclassified or any(call["outcome"] in {"unknown", "pending"}
                                                for call in calls) else "observed"),
        baselines={role: baseline([turn for turn in turns if turn["role"] == role])
                   for role in (("exec",) if channel == "exec" else ("task", "agent"))},
        capabilities=capabilities, environment_advice=environment, model_requests=0,
        channel=channel,
        coverage="explicit_exec_stream" if channel == "exec" else "supported_local_hooks_only",
        interpretation=[
            "Observed attempts are not a loaded-tool catalog; absent use is not proof of no use.",
            "Code-mode wrappers remain opaque and suppress capability review suggestions.",
            "Review configuration means inspect it; no settings are changed or tools disabled.",
            "A successful local check does not establish workflow acceptance.",
            "No token savings, charges or account-quota allocation are inferred.",
            "Exec stream and native hook observations can overlap; never add their call counts.",
        ],
    )
    last = health.get("last_success")
    age = time.time() - last if isinstance(last, (int, float)) else None
    health["last_success_age_seconds"] = round(age, 3) if age is not None and age >= 0 else None
    health["freshness"] = ("unknown" if age is None else "clock_discontinuity" if age < 0
                           else "old_observation" if age > 900 else "recent")
    return value


def measure(project: Path, capabilities: list[str], binary: str = "codex") -> dict:
    """Compare local rendered input bytes. No model call, config write or raw input storage."""
    project = project.expanduser().resolve()
    if not project.is_dir() or not capabilities or set(capabilities) - set(CAPABILITIES):
        raise ValueError("invalid project or capability")
    env = {**os.environ, "CODEX_PLUGIN_AUTO_UPDATE": "0", INTERNAL_ENV: "1"}

    def capture(overrides):
        command = [binary, "debug", "prompt-input"]
        for override in overrides:
            command += ["-c", override]
        completed = subprocess.run(command, cwd=project, env=env, capture_output=True, timeout=30)
        if completed.returncode or not 0 < len(completed.stdout) <= 8 * 1024 * 1024:
            raise ValueError("Codex input probe unavailable")
        # Only serialized model input is measured; formatting and stderr are excluded.
        value = json.loads(completed.stdout)
        if not isinstance(value, list):
            raise ValueError("unsupported Codex input format")
        def size(data):
            return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())

        schemas = [item["tools"] for item in value
                   if isinstance(item, dict) and isinstance(item.get("tools"), list)]
        return {"input": size(value), "schemas": sum(size(item) for item in schemas)
                if schemas else None}

    selected = sorted(set(capabilities))
    full = capture([])
    lean = capture([flag for capability in selected for flag in _TOGGLES[capability]])
    return {"status": "measured", "capabilities": selected,
            "rendered_input_bytes_full": full["input"],
            "rendered_input_bytes_lean": lean["input"],
            "rendered_input_bytes_difference": full["input"] - lean["input"],
            "tool_schema_bytes_full": full["schemas"], "tool_schema_bytes_lean": lean["schemas"],
            "tool_schema_bytes_difference": full["schemas"] - lean["schemas"]
            if full["schemas"] is not None and lean["schemas"] is not None else None,
            "saved_tokens": None, "model_requests": 0,
            "interpretation": "local_rendered_input_bytes_not_tokens_or_billed_savings"}


def run(args, root: Path) -> int:
    try:
        if args.optimizer_action in {"enable", "disable"}:
            ledger = OptimizationLedger(root / "optimizer.sqlite3")
            try:
                ledger.configure(args.optimizer_action == "enable")
            finally:
                ledger.close()
        value = (measure(args.project, args.capability, args.codex_binary)
                 if args.optimizer_action == "measure"
                 else report(root, args.project, args.channel))
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        # Exception strings may contain private paths or command output.
        print('{"status":"unavailable","detail":"optimizer observation or probe unavailable"}',
              file=sys.stderr)
        return 2
