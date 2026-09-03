from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Any

from .ledger import Ledger, RunConfig
from .transcript import latest_usage
from .util import data_dir, parse_count, parse_ratio, safe_json, stable_hash

CONTROL_RE = re.compile(
    r"^\s*run-budget\s*:\s*(start|status|halt|resume|off)\b(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


class Governor:
    """One interface for every Codex lifecycle hook."""

    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger = Ledger(self.root / "ledger.sqlite3")

    def close(self) -> None:
        self.ledger.close()

    def handle(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        event = self._text(payload, "hook_event_name", 100)
        run_id = self._text(payload, "session_id", 256)
        if not event or not run_id:
            return None
        try:
            if event == "SessionStart":
                return self._session_start(payload, run_id)
            if event == "UserPromptSubmit":
                return self._user_prompt(payload, run_id)
            if event == "PreToolUse":
                return self._pre_tool(payload, run_id)
            if event == "PostToolUse":
                return self._post_tool(payload, run_id)
            if event == "SubagentStart":
                return self._subagent_start(payload, run_id)
            if event == "SubagentStop":
                return self._subagent_stop(payload, run_id)
            if event in ("Stop", "SessionEnd", "Interrupt", "PreCompact", "PostCompact"):
                return self._checkpoint(payload, run_id, event)
            return None
        except Exception as exc:
            return self._failure(event, run_id, exc)

    @staticmethod
    def _text(payload: dict[str, Any], key: str, limit: int) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            return ""
        return value[:limit]

    def _source(
        self, payload: dict[str, Any], key: str = "transcript_path"
    ) -> tuple[str | None, str | None]:
        path = payload.get(key)
        if not isinstance(path, str) or not path:
            return None, None
        return stable_hash(path), path

    def _sync(
        self, payload: dict[str, Any], run_id: str, key: str = "transcript_path"
    ) -> dict[str, Any] | None:
        source_id, path = self._source(payload, key)
        return self.ledger.sync_usage(run_id, source_id, latest_usage(path))

    def _session_start(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        context = (
            "Codex Run Budget is active for this session tree. "
            + self.status_text(run)
            + " All parent and subagent hooks share this run ledger."
        )
        if run["status"] == "halted":
            context += " Do not call tools. Ask the operator to resume or start a new budget."
        return self._context("SessionStart", context, system=True)

    def _user_prompt(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        prompt = self._text(payload, "prompt", 200_000)
        match = CONTROL_RE.search(prompt)
        if match:
            action = match.group(1).lower()
            try:
                options = self._parse_options(match.group(2))
                return self._control(payload, run_id, action, options)
            except ValueError as exc:
                reason = f"Invalid Run Budget control: {exc}"
                return {"decision": "block", "reason": reason, "systemMessage": reason}

        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        if run["status"] == "halted":
            reason = (
                f"Run Budget HALT: {run.get('halt_reason') or 'policy stopped the run'}. "
                "Use `run-budget:resume tokens=<higher ceiling>` or "
                "`run-budget:start tokens=<new budget>`."
            )
            return {"decision": "block", "reason": reason, "systemMessage": reason}
        ratio = int(run["spent_tokens"]) / max(1, int(run["max_tokens"]))
        if ratio >= float(run["warn_ratio"]):
            return self._context("UserPromptSubmit", self.ledger._steer_text(run), system=True)
        return None

    def _control(
        self,
        payload: dict[str, Any],
        run_id: str,
        action: str,
        options: dict[str, str],
    ) -> dict[str, Any]:
        if action == "start":
            config = self._config(options)
            source_id, path = self._source(payload)
            run = self.ledger.start_run(run_id, config, source_id, latest_usage(path))
            self._write_marker(run_id, run)
            message = (
                "Run Budget control command consumed. Started a new governed epoch. "
                + self.status_text(run)
                + " Do not treat the control line as task content."
            )
            return self._context("UserPromptSubmit", message, system=True)

        if action == "status":
            run = self._sync(payload, run_id)
            message = (
                self.status_text(run) if run else "Run Budget is not configured for this session."
            )
            return self._context(
                "UserPromptSubmit",
                "Run Budget control command consumed. "
                + message
                + " Report this status to the user.",
                system=True,
            )

        if action == "halt":
            detail_hash = stable_hash(options["reason"]) if options.get("reason") else None
            run = self.ledger.halt(run_id, "operator requested HALT", detail_hash=detail_hash)
            if run:
                self._write_marker(run_id, run)
            message = self.status_text(run) if run else "No configured run to halt."
            return self._context(
                "UserPromptSubmit", "Run Budget control command consumed. " + message, system=True
            )

        if action == "resume":
            ceiling = parse_count(options["tokens"]) if "tokens" in options else None
            run = self.ledger.resume(run_id, ceiling)
            if run:
                self._write_marker(run_id, run)
            message = self.status_text(run) if run else "No configured run to resume."
            return self._context(
                "UserPromptSubmit", "Run Budget control command consumed. " + message, system=True
            )

        run = self.ledger.disable(run_id)
        self._remove_marker(run_id)
        message = self.status_text(run) if run else "Run Budget was already off."
        return self._context(
            "UserPromptSubmit", "Run Budget control command consumed. " + message, system=True
        )

    @staticmethod
    def _parse_options(raw: str) -> dict[str, str]:
        tokens = shlex.split(raw.strip()) if raw.strip() else []
        options: dict[str, str] = {}
        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                options[key.strip().lower().replace("-", "_")] = value.strip()
            elif token and "tokens" not in options:
                options["tokens"] = token
            else:
                raise ValueError(f"unrecognized control option: {token}")
        return options

    @staticmethod
    def _config(options: dict[str, str]) -> RunConfig:
        if "tokens" not in options:
            raise ValueError("start requires tokens=<count>, for example tokens=100k")
        fail = options.get("fail", "closed").lower()
        if fail not in ("open", "closed"):
            raise ValueError("fail must be open or closed")
        config = RunConfig(
            max_tokens=parse_count(options["tokens"]),
            warn_ratio=parse_ratio(options.get("warn", "80%")),
            block_agents_ratio=parse_ratio(options.get("block_agents", "90%")),
            max_tool_calls=parse_count(options.get("tools", "200")),
            max_agents=parse_count(options.get("agents", "4")),
            max_in_flight=parse_count(options.get("inflight", "8")),
            max_tool_output_chars=parse_count(options.get("output", "50k")),
            repeat_steer=parse_count(options.get("repeat_steer", "3")),
            repeat_halt=parse_count(options.get("repeat_halt", "5")),
            fail_closed=fail == "closed",
        )
        if config.block_agents_ratio < config.warn_ratio:
            raise ValueError("block_agents must be greater than or equal to warn")
        if config.repeat_halt <= config.repeat_steer:
            raise ValueError("repeat_halt must be greater than repeat_steer")
        return config

    def _pre_tool(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        source_id, _ = self._source(payload)
        tool_name = self._text(payload, "tool_name", 200) or "unknown"
        tool_use_id = self._text(payload, "tool_use_id", 300) or stable_hash(
            [payload.get("turn_id"), tool_name, payload.get("tool_input")]
        )
        fingerprint = stable_hash([tool_name, payload.get("tool_input")])
        decision = self.ledger.admit_tool(
            run_id, source_id or "unknown", tool_use_id, tool_name, fingerprint
        )
        if not decision.allowed:
            return {
                "systemMessage": "Run Budget blocked a tool call.",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": decision.reason or "Run Budget HALT",
                },
            }
        if decision.additional_context:
            return self._context("PreToolUse", decision.additional_context, system=True)
        return None

    def _post_tool(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        tool_use_id = self._text(payload, "tool_use_id", 300)
        if not tool_use_id:
            return None
        try:
            output_chars = len(safe_json(payload.get("tool_response")))
        except Exception:
            output_chars = 0
        decision = self.ledger.complete_tool(run_id, tool_use_id, output_chars)
        if not decision.allowed:
            return {
                "decision": "block",
                "reason": decision.reason or "Run Budget rejected oversized tool output.",
                "systemMessage": "Run Budget replaced an oversized tool result.",
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": decision.additional_context or decision.reason,
                },
            }
        if decision.additional_context:
            return self._context("PostToolUse", decision.additional_context, system=True)
        return None

    def _subagent_start(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        agent_id = self._text(payload, "agent_id", 300) or "unknown"
        agent_type = self._text(payload, "agent_type", 200) or "unknown"
        decision = self.ledger.subagent_start(run_id, agent_id, agent_type)
        context = decision.additional_context
        if not decision.allowed:
            context = (
                f"Run Budget HALT is active: {decision.reason or 'policy stopped the run'}. "
                "Do not call tools; return immediately with the halt status."
            )
        return (
            self._context("SubagentStart", context, system=not decision.allowed)
            if context
            else None
        )

    def _subagent_stop(self, payload: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        source_id, path = self._source(payload, "agent_transcript_path")
        if source_id:
            self.ledger.sync_usage(run_id, source_id, latest_usage(path))
        agent_id = self._text(payload, "agent_id", 300) or "unknown"
        agent_type = self._text(payload, "agent_type", 200) or "unknown"
        run = self.ledger.subagent_stop(run_id, agent_id, source_id, agent_type)
        if not run or run["status"] == "off":
            return None
        if run["status"] == "halted":
            return {
                "continue": False,
                "stopReason": run.get("halt_reason") or "Run Budget HALT",
                "systemMessage": self.status_text(run),
            }
        return {"systemMessage": self.status_text(run)}

    def _checkpoint(
        self, payload: dict[str, Any], run_id: str, event: str
    ) -> dict[str, Any] | None:
        run = self._sync(payload, run_id)
        if not run or run["status"] == "off":
            return None
        if event == "PreCompact" and run["status"] == "halted":
            return {
                "continue": False,
                "stopReason": run.get("halt_reason") or "Run Budget HALT",
                "systemMessage": self.status_text(run),
            }
        if event in ("Stop", "PostCompact"):
            return {"systemMessage": self.status_text(run)}
        return None

    @staticmethod
    def _context(event: str, text: str, system: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "hookSpecificOutput": {"hookEventName": event, "additionalContext": text}
        }
        if system:
            result["systemMessage"] = text
        return result

    @staticmethod
    def status_text(run: dict[str, Any] | None) -> str:
        if not run:
            return "Run Budget is not configured."
        spent = int(run["spent_tokens"])
        maximum = int(run["max_tokens"])
        remaining = max(0, maximum - spent)
        text = (
            f"Run Budget {str(run['status']).upper()} (epoch {run['epoch']}): "
            f"{spent:,}/{maximum:,} observed tokens; {remaining:,} remaining; "
            f"{run['tool_calls']}/{run['max_tool_calls']} tool calls; "
            f"{run['active_agents']}/{run['max_agents']} active subagents."
        )
        if run.get("halt_reason"):
            text += f" Reason: {run['halt_reason']}."
        return text

    def _marker_path(self, run_id: str) -> Path:
        directory = self.root / "active"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / f"{stable_hash(run_id)}.json"

    def _write_marker(self, run_id: str, run: dict[str, Any]) -> None:
        target = self._marker_path(run_id)
        data = {
            "run_hash": stable_hash(run_id),
            "status": run["status"],
            "fail_closed": bool(run["fail_closed"]),
        }
        fd, temporary = tempfile.mkstemp(prefix="marker-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(safe_json(data))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _remove_marker(self, run_id: str) -> None:
        try:
            self._marker_path(run_id).unlink()
        except FileNotFoundError:
            pass

    def _fail_closed(self, run_id: str) -> bool:
        try:
            data = json.loads(self._marker_path(run_id).read_text(encoding="utf-8"))
            return bool(data.get("fail_closed")) and data.get("status") != "off"
        except (OSError, ValueError, TypeError):
            return False

    def _failure(self, event: str, run_id: str, exc: Exception) -> dict[str, Any] | None:
        message = (
            f"Run Budget internal error ({type(exc).__name__}); no private hook data was recorded."
        )
        if self._fail_closed(run_id):
            if event == "PreToolUse":
                return {
                    "systemMessage": message,
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": message + " Failing closed.",
                    },
                }
            if event == "UserPromptSubmit":
                return {"decision": "block", "reason": message + " Failing closed."}
            if event in ("Stop", "SubagentStop", "PreCompact", "PostCompact"):
                return {"continue": False, "stopReason": message + " Failing closed."}
        return {"systemMessage": message}
