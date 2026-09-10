---
name: run-budget
description: Set, inspect, halt, resume, or explain a shared token budget, or audit local Codex tasks for model usage, waiting, and repeated tool work. Use for run budgets, token lineage, STEER/HALT governance, or retrospective task-efficiency analysis.
---

# Run Budget

Use the installed hooks as the enforcement mechanism. Never claim that a skill
instruction by itself enforces a budget.

## Start a governed run

Tell the user to begin the task message with a control line, or include the
control line yourself when showing an exact prompt:

```text
run-budget:start tokens=100k
<task>
```

Supported start options:

- `tokens`: required shared observed-token ceiling; supports `k` and `m`.
- `warn`: STEER threshold, default `80%`.
- `block_agents`: stop admitting new subagents, default `90%`.
- `tools`: tool-call ceiling, default `200`.
- `agents`: combined pending and active subagent ceiling, default `4`.
- `inflight`: in-flight local tool-call ceiling, default `8`.
- `output`: maximum serialized tool-result characters, default `50k`.
- `repeat_steer`: identical-call warning, default `3`.
- `repeat_halt`: identical-call HALT, default `5`.
- `fail`: `closed` by default, or `open`.

Do not silently select a token ceiling when the user has not supplied one.

## Operate the current run

Use one control line in a new user message:

```text
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

`resume tokens=` is an absolute ceiling and must exceed observed spend.
`start` creates a new epoch with a fresh counter baseline while preserving old
lineage events.

Put controls and their options on the first line; examples elsewhere in a
message are not commands. Status reports `usage_status`: `pending` means no
usage has been reported yet; `unavailable` preserves previous counters and
pauses supported admissions under `fail=closed`. Valid observations recover
automatically. Do not reset the epoch merely to bypass missing data.

Changed output hashes reset repeat streaks; explicit wait/poll tools are exempt
from the repeat guard, but not token, tool-call, or in-flight ceilings.

## Explain enforcement accurately

State these boundaries when relevant:

- Parent and descendant hooks share the parent `session_id` and one SQLite row.
- `UserPromptSubmit` can block the next user turn before its model request.
- `PreToolUse` can hard-block supported local tool calls.
- Transcript `token_count` events are reconciled at lifecycle boundaries; in
  installed validation, Codex persisted them at turn completion.
- Codex does not expose plugin hooks before every model request.
- Hosted tools and specialized tool paths may bypass local tool hooks.
- A whole turn may overshoot before the shared ledger observes HALT. Therefore
  the plugin is a next-supported-boundary guardrail, not a same-turn,
  zero-overshoot, or billing-grade guarantee.

## Inspect lineage

For local operator diagnostics, use the bundled CLI:

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" list
python3 "$PLUGIN_ROOT/scripts/run_budget.py" show latest
python3 "$PLUGIN_ROOT/scripts/run_budget.py" events latest
```

The ledger intentionally contains no prompt, command, input, output, or
transcript content. Never bypass that privacy rule when troubleshooting.

## Audit recent tasks

For retrospective task-efficiency questions, start with the read-only survey;
it also covers tasks that never enabled a budget:

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" survey
```

By default this inspects up to 200 recent local transcript pages over seven
days and prints a compact summary. Use `--json` for per-thread evidence.
Optional `--days` and `--limit` narrow or expand the cohort; `audit <path>
<other-page>` inspects exact files. These commands do not start a budget or
change hooks, waiting settings, or task state.

Check coverage and conflicts before quoting totals. Use thread identity and
explicit turn/model metadata, not a shared `session_id`, to distinguish parents
and subagents. For waits, `timed_out=false` means an event return, not necessarily
agent completion. Separate old and new task trees when evaluating a settings
change. Repeated unchanged results are review candidates, not proof of waste;
do not claim token savings from elapsed waits or before/after cohorts alone.

## Update safely

From a source checkout, use `python3 scripts/update_plugin.py` to retain old
cache versions and prepare SHA-pinned runtimes outside the replaceable cache.
The helper does not enable or trust hooks. New v0.4.1 commands load verified
runtime bytes even after cache eviction; missing code blocks admission with a
structured failure rather than requesting a Stop retry loop.

Tasks with older pathname commands need a one-time finish/restart and retained
cache. Do not claim that installing new code updates an already captured old
command. Preserve hook settings unless enabling them is authorized, and review
new command hashes before trusting them. Never clear HALT or silently turn
enforcement off to recover from a missing runtime.
