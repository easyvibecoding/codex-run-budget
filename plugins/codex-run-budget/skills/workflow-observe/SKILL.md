---
name: workflow-observe
description: Inspect an explicitly selected Codex workflow across Tasks and subagents, compare compact evidence with a cursor, and identify follow-up checks. On-demand by default; recurring observation requires an explicit user request. Never automatically intervene in the workflow.
---

# Workflow observer

Use the deterministic CLI first. Resolve `PLUGIN_ROOT` two directories above
this skill. Select the user's named Tasks with native Task tools or the existing
metadata-only `report tasks --limit 10`; never read all conversations to choose.
No specific target means the current Task, not all Tasks. Use native names.

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" workflow observe --thread SELECTOR
```

Only add `--include-agents` when the requested workflow includes descendants.
Default cap: 8 Tasks. Preserve the exact root set, descendant option and cap;
pass the previous returned `--after CURSOR` on a later observation of that scope.
Expired/mismatched cursors require an explicitly disclosed fresh baseline,
never silently broaden scope. A bounded tree may omit new children at its cap.

Return only changes, new/cleared signals, coverage and the private report link.
Do not read the full report/JSON or all transcripts by default. No change means
a short “no new evidence” result, not another full analysis. Report generation
has zero model calls; the conversation and any scheduled model wake still cost tokens.

## Confirm live status only when needed

Local lifecycle evidence is not live process state. `task_complete` is a turn
ending, not workflow acceptance. Old/missing records are not proof of a stall.
For live status, `workflow targets` with the same scope emits exact local native
targets, excluding this calling Task. Use those with `wait_threads` (at most 8)
and `timeoutMs: 0` for an on-demand snapshot. Preserve the returned native cursor
as `afterCursor` for subsequent native waits; it differs from the CLI cursor.
For a continued wait in the active turn, use native event waits rather than
repeated `read_thread`. Read one bounded turn without outputs only if needed to
explain an actionable change. Unavailable native tools mean live state is unknown.

## Evaluate before recommending changes

Check agent ownership, explicit errors/approvals, observed turn endings, source
coverage and comparable token deltas. Repeated unchanged observations suggest
using event waits, not proof of agent waste. Tool counts cover direct calls in
a bounded tail; wrapped code-mode calls and elapsed wait duration are unknown.
Do not infer duplicate work from names, allocate quota, or claim savings from
before/after tokens alone. Workflow completion needs its own tests/receipts/DB
or deployment read-back under the user's existing acceptance criteria.

Only propose optimization hypotheses supported by observations. Do not send
messages, restart/stop agents, alter models, edit workflow code, publish, or
launch QA under observation authority. Those are separate execution requests.

## Optional explicit continuous mode

Default is user-triggered; invoking this skill never creates a monitor. Only
when the user explicitly asks to enable continuous observation, resolve exact
Task IDs and use Codex's native automation tool, preferring a thread heartbeat.
Inspect existing automations to avoid duplicates; preserve unrelated settings.
Bind targets, cap and read-only authority in its prompt. Carry the CLI cursor
forward. Stay quiet for unchanged/non-actionable state and notify only on a
meaningful change, completion, failure or required user action. Retain the
distinction between turn completion and workflow acceptance. Do not create cron,
launchd, shell loops or a background model polling process as a workaround.

Invocation: `/skills` → `workflow-observe`, or `$workflow-observe`.
