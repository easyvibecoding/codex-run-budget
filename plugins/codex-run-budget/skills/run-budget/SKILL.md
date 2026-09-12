---
name: run-budget
description: Operate shared token budgets, sense native quota and subscription plans, compare cross-task model/Fast/reasoning token observations, or audit task lifecycle and efficiency. Use for quota sensing, token lineage, STEER/HALT governance, and retrospective task analysis.
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

For turn endings, interruptions, and context compaction, use `survey --lifecycle`.
It shows at most 20 hashed evidence rows; `--json` includes all observed turns.
`no_terminal_observed` means the selected snapshot lacks an ending, not that a
task is running or stuck. `later_turn_observed` means a different turn started
in the same thread, not that the interrupted work was completed. Check window
boundaries, missing starts, conflicts, and compaction attribution before drawing
conclusions. These diagnostics never authorize automatic restart, resume, or HALT.

Check coverage and conflicts before quoting totals. Use thread identity and
explicit turn/model metadata, not a shared `session_id`, to distinguish parents
and subagents. For waits, `timed_out=false` means an event return, not necessarily
agent completion. Separate old and new task trees when evaluating a settings
change. Repeated unchanged results are review candidates, not proof of waste;
do not claim token savings from elapsed waits or before/after cohorts alone.

## Sense native account quota

For a current percentage without saving history, use `meter --no-save`. For
requested measurement, save snapshots around ordinary work and compare them:

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" meter snapshot
python3 "$PLUGIN_ROOT/scripts/run_budget.py" meter report
python3 "$PLUGIN_ROOT/scripts/run_budget.py" meter history
```

Each snapshot calls the signed-in Codex app-server, without a model request,
and appends allowlisted usage to a separate local `meter.sqlite3`. It never
resets quota, spends reset credits, starts a budget, or changes hooks. There
is no automatic polling. Capture again after the work; `report --baseline N`
can compare with an earlier saved snapshot. Use `--json` for all observations.

`--thread <UUID>` optionally requests official thread/model usage (up to 8
threads). Missing `threadUsage` means unavailable, not zero. When supplied,
`estimatedUsageCreditsMicros` is a backend estimate, not settled billing or
included-quota percentage. Preserve model, reasoning effort, speed, and the
cached/input/output basis when interpreting credits per million tokens.

Name quota windows by their actual duration; `primary` is not always five
hours. A changed account, plan or reset invalidates its before/after delta.
Zero displayed change is not proof of free usage. Local token-share percentages
must not be used to split account quota among models: concurrent tasks, other
devices, partial transcripts and reporting lag prevent that inference. Do not
run extra model workloads just to force the percentage meter to move.

## Compare tasks, subscription and Fast/effort

Use `meter tasks --days 1` for recent cross-task history without needing two quota
snapshots. `--thread UUID` filters exact Task identities in `tasks` and `report`;
it does not restrict the account quota to those Tasks. JSON contains per-turn
configuration rows and each field's evidence source/status; check these before
claiming Fast was active or a reasoning level was used.

Historical settings come from metadata at the request position, never today's
configuration or prompt text. Missing Fast is unknown; `default` and API
`priority` do not establish ChatGPT Fast. Current Codex transcripts may omit
speed entirely. Official thread-usage speed groups, when present, are separate
backend estimates and cannot be retroactively assigned to local requests.

Snapshots report the account plan and billing route. Historical transcript
plans are nearby quota observations, not exact per-request billing facts. Do
not turn a `pro`/`prolite` enum into a detected 5x/20x allowance without direct
evidence or backfill old Task plans from the current subscription.

Snapshots also show native included-usage permission, limit-reached reasons,
credit balance and spend controls when reported. A zero credit balance does not
mean included quota is exhausted. Missing controls are unknown, not cleared;
percentages and reset times do not prove permission to start another turn.
Credit-only accounts can have usable observations without percentage windows.

`meter rates` shows a dated official token/Fast/plan reference, not live prices
or measured charges. `meter estimate --days 1` (with optional exact `--thread`)
reprices observed text tokens as Standard and Fast **counterfactual scenarios**.
It is offline, uses the same token cohort for both columns, and never chooses
the historical mode or a Pro tier. Check excluded-request coverage and reference
freshness; its 30-day review reminder is not an official tariff validity period.

Recheck linked official sources for current pricing claims. The formula uses
uncached input, cached input and output at their separate rates; output already
includes reasoning. Neither scenario is actual credits deducted, USD, historical
pricing, or an included-quota percentage. It excludes unpriced models,
unsupported cache-write bases and separate tool/image/voice charges. API,
legacy Enterprise and negotiated USD billing may use different rate cards.
Reasoning levels have no fixed consumption multiplier in this meter.

## Update safely

From a source checkout, use `python3 scripts/update_plugin.py` to retain old
cache versions and prepare SHA-pinned runtimes outside the replaceable cache.
The helper does not enable or trust hooks. New v0.4.2 commands load verified
runtime bytes even after cache eviction; missing code blocks admission with a
structured failure rather than requesting a Stop retry loop.

Tasks with older pathname commands need a one-time finish/restart and retained
cache. Do not claim that installing new code updates an already captured old
command. Preserve hook settings unless enabling them is authorized, and review
new command hashes before trusting them. Never clear HALT or silently turn
enforcement off to recover from a missing runtime.
