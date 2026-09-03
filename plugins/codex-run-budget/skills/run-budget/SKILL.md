---
name: run-budget
description: Set, inspect, halt, resume, or explain a shared token budget for the current Codex session and its subagents. Use when the user asks for a run budget, token cap, cost guard, STEER/HALT governance, token lineage, or bounded multi-agent work.
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
- `agents`: concurrently active subagent ceiling, default `4`.
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
