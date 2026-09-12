---
name: run-budget
description: Operate shared token budgets, sense native quota and subscription plans, produce multi-window Task usage reports, or compare model/Fast/reasoning observations. Use for quota sensing, token lineage, STEER/HALT governance, and retrospective task analysis.
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

For on-demand cross-Task workflow progress/efficiency observation, use
`workflow-observe`: bounded local evidence and explicit cursors, then native
Task checks only as needed. No background monitor is enabled implicitly.

For a generic usage-analysis request, start with `report` (a no-scan menu), or
the scoped `usage-task`, `usage-agents`, or `usage-window` skill. Do not run a
200-page survey, cross-Task meter report, full JSON export or all-window report
by default. The following survey is only for explicitly requested retrospective
cross-Task diagnostics; it also covers Tasks without a budget:

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

Only for an explicit cross-Task request, use `meter tasks --days 1` without needing two quota
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

## Produce a Task usage report

Use `report` with no arguments to display the scope menu without scanning.
Choose one scoped command; it is distinct from `meter report` (native snapshots):

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" report task --windows 24h
python3 "$PLUGIN_ROOT/scripts/run_budget.py" report agents
python3 "$PLUGIN_ROOT/scripts/run_budget.py" report window --windows 5h
```

Choose the user's timezone, or leave the UTC default explicit. Formats are
`markdown` (default), `html` and `json`. `--thread UUID` selects exact Tasks and
is repeatable and accepts UUIDs or listed selectors. Absent a filter, scoped
commands use the current Task; missing identity is an error, never all Tasks.
Only explicit cross-Task requests may use `report window --all-tasks` with a
specified window. `report tree` explicitly includes descendants; `report agents`
is metadata-only. `--since` and `--until` accept ISO
timestamps with offsets for historical intervals. `week` starts Monday; windows
are `[since, until)` and overlap, so do not add their totals.

Check coverage: default analysis is 20 pages, not all account history. Detail
rows can be truncated independently from totals (`--detail-limit`, default 20).
Selection occurs before transcript analysis. Default output is a small summary
and a saved artifact link, not the whole report. Do not read the full artifact
back into context merely to deliver it; use `--full` only when explicitly needed.
Reports preserve unknown historical settings, separate saved account quota from
local tokens, and label Standard/Fast credits as scenarios. Native snapshots are
read from history, not refreshed; capture separately only when requested. The
report does not start polling, enforce a budget, or change task/settings state.

Prefer Markdown in Codex's native file viewer for readable summaries and HTML
for local window/Task filtering and print/save-as-PDF. Use the available app
file/browser opening tool after creating the report when helpful. Do not assume
raw HTML will render inline in a Markdown message or claim this modifies the
built-in quota widget. A conversation visualization is optional when supported
and useful, not a dependency. Use new filenames: report output refuses overwrites
and symlink paths. Task/turn IDs remain hashed; display names and agent aliases
come from Codex metadata. Never fall back to prompt/title/preview text or invent
names. Names may be sensitive: keep reports private unless sharing is requested.

## Automatic turn-stop receipts

When the user asks to turn automatic per-turn reports on/off, use the report-only
switch; do not disable the plugin or its budget hooks. For on, run `enable`;
for off, run `disable`; always read back `status`:

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" auto-report enable
python3 "$PLUGIN_ROOT/scripts/run_budget.py" auto-report disable
python3 "$PLUGIN_ROOT/scripts/run_budget.py" auto-report status
```

Choose only the requested action above, not both. The default is on when settings
are absent; an explicit off setting survives upgrades. Do not rewrite user
preferences merely to apply the default. Enabling defaults to threshold 0, so every
eligible main user turn can report. Do not add a five-minute gate unless the
user requests one (`--threshold-seconds 300`). `auto-report list` reads recent
receipt state, and `auto-report disable` preserves existing files. These
commands are independent of budget enforcement; do not start a budget for them.
The setting is checked at each relevant hook, not cached per Task. This is a
local plugin configuration, not a new native app Settings toggle. A conversational
request to change it uses normal tokens; automatic generation needs no model call.

UserPromptSubmit records a baseline and creates a pending Markdown target. From
v0.13 it supplies a short `additionalContext` instruction to run one deterministic
preview command before the normal final answer. Select a task-owned writable
visualization directory, run that command once, and include its returned native
`visualize` reference on its own line in the final answer, not as a Markdown link.
Do not read the report body, invent numbers or regenerate layout with a model.
The fixed template supplies the whole inline card. Skip without retries on failure.
Omit it when the user disables reports
or requires an incompatible exact format. The first eligible Stop fills the same
Markdown path and generates HTML/JSON plus an informational `systemMessage`.
The renderer makes no model/network requests; there are no report-driven new
turns or full cross-Task scans. The normal preview tool round trip may add inference.
The instruction, one tool call/result and normal-answer reference use tokens;
do not describe visible reporting as zero-token. Local CPU,
disk and later model reading still cost resources. Do not add a model follow-up
just to produce, decorate or announce these automatic receipts.

Call them user-turn Stop snapshots, not proof the whole Task has completed.
Missing starts, interrupted turns and subagents are excluded; duplicate Stops
are not regenerated. Other hooks may continue after the snapshot. Boundary
counter differences can be missing or lag final persistence, and do not include
descendants, actual quota shares or billing. Historical settings are observed,
not inferred or used to allocate token totals. The bounded index keeps at most
10,000 turns; report failures are informational and never change governance.

Codex owns presentation of `systemMessage`; that warning alone does not append
to the final answer. The v0.13 reference is model-written in the normal answer,
not a deterministic native-footer guarantee or an edit to a sent answer.
The card is a pre-final snapshot, not the Stop settlement; it excludes subsequent
work and is not live-updated. Missing data is unknown, not zero. Native visualize
support is required for inline display; do not claim an auto-open browser panel.
Use the Markdown report path if the
user asks to open a receipt, respecting native file/browser restrictions. After
upgrading, use a new Task for the updated pinned runtime.

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
