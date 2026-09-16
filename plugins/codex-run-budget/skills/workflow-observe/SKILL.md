---
name: workflow-observe
description: Inspect project codex exec activity and launcher attribution. Find related Codex Tasks from a plain-language description of work, observe their workflow and agents, and investigate efficiency problems. Use when the user describes a process to inspect or improve without Task IDs. On-demand by default; changes and recurring observation follow the user's explicit scope.
---

# Workflow observer

Users can describe the work, not its Task IDs. For a topic/process description,
or a request to improve the workflow, first read
[Resolve work and improvement intent](references/resolve-and-improve.md).
Find relevant Tasks from bounded native names/summaries, bind exact identities,
then use the deterministic CLI. Do not default a described topic to this Task.
Only a genuinely deictic request such as “this Task” uses the current identity.
If neither topic nor target is supplied, ask what work the user means.

Resolve `PLUGIN_ROOT` two directories above this skill. Exact user-supplied
identities may go directly to observation. Never read all conversations to choose.
Use native Task names in the explanation; IDs remain internal tool parameters.

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
When the user's same request includes implementation, carry that existing
authority through the resolved scope using the reference; do not ask for it again.

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

## Project exec activity

For extra `codex exec` activity, select one project directory (the current workspace
when unambiguous), then run from the plugin root:

```sh
python3 scripts/run_budget.py exec-activity list --project "$PROJECT_DIR" --format json
python3 scripts/run_budget.py exec-activity watch --project "$PROJECT_DIR" --duration 60
python3 scripts/run_budget.py exec-activity run --project "$PROJECT_DIR" -- --ephemeral "Summarize the repository"
```

Set `PROJECT_DIR` to the selected project, not the plugin directory.
Default to `list` for investigation. Use foreground `watch` only when monitoring is
requested. `run` is an opt-in launcher for an already authorized exec invocation;
an inspection request does not authorize starting model work. Explicit
`--parent-task` or inherited `CODEX_THREAD_ID` records launcher evidence, not native
child lineage. Same-directory activity never establishes parent ownership.
Session cumulative tokens and invocation usage stay separate from parent usage
and the shared budget ledger. Last-turn events do not prove process liveness.
Missing records and scan caps remain unknown/partial. Hooks notify at tool-return
boundaries; this feature installs no daemon, schedule or enforcement extension.
