# Codex Run Budget

An open-source Codex plugin that gives one Codex session tree one shared token
budget, privacy-preserving token lineage, deterministic STEER guidance, and
HALT controls.

It is a Codex-native reinterpretation of the run-scoped governance ideas
described by [Microsoft TokenOps](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/),
built against the public [Codex hooks interface](https://learn.chatgpt.com/docs/hooks).

> [!IMPORTANT]
> This is an independent community project, not an OpenAI or Microsoft product.
> It is a guardrail, not a billing meter or a zero-overshoot guarantee.

Human-facing reports, menus and summaries follow the saved Codex language, with
nine bundled languages and an English fallback. Machine JSON, commands, evidence
codes and model/native names stay unchanged; no model translates output at runtime.
See [localization scope](docs/LOCALIZATION.md) and [sensitive-data protection](SECURITY.md).

## Project exec activity

Inspect extra `codex exec` sessions by working directory, watch for changes in the foreground, or use the optional launcher to retain start/exit and usage receipts for ephemeral runs. Hooks notify at tool-return boundaries after an updated hook review and a new Task. Launcher attribution stays distinct from native child lineage; exec usage is separate from parent totals. [Commands and coverage](docs/EXEC_ACTIVITY.md).

## What it does

- Uses Codex's parent `session_id` as a shared run key for the main agent and
  descendant subagents.
- Reconciles cumulative `token_count` transcript events into one atomic SQLite
  ledger without double-counting repeated hook delivery.
- Applies a token ceiling, tool-call ceiling, subagent ceiling, in-flight-call
  ceiling, repeated-call progress guard, and tool-output size guard.
- STEERs before HALT by injecting deterministic, model-visible guidance near
  the ceiling and refusing new subagents at a configurable threshold.
- Hard-blocks supported local tool calls at `PreToolUse` after HALT.
- Keeps an explainable event lineage while storing no prompt, command, tool
  input, tool output, or transcript content.
- Has no runtime package dependencies beyond Python 3.10+ and SQLite.

### Reliability defaults (v0.3)

No new configuration is required. Unknown or regressed usage preserves the last
known counter and pauses supported admissions under the existing `fail=closed`
policy; readable data recovers automatically. Status distinguishes pending,
available, and unavailable observations. A counter reset needs an explicit new
epoch, not an automatic accounting reset.

Agent admission reserves pending capacity atomically; pending plus active agents
share `agents`. Changed result hashes reset repeat streaks, and explicit wait/poll
tools do not trigger the repeat guard (all other ceilings still apply). Ledger
upgrades automatically back up v1 data before the additive migration. See
[hardening design and evidence](docs/HARDENING.md).

## Update reminders

The first prompt in each Task checks for plugin updates and hooks awaiting trust.
After updating, open a terminal, run `codex`, enter `/hooks`, and review/trust the
changed hooks. A separate reminder can stay trusted across routine updates;
**trust this new reminder once when first installing this version**. Checks are
cached, nonblocking, and make no model calls. No update or trust is automatic.
[Coverage, manual checks, and disabling notices](docs/UPDATE_NOTICES.md).

## Install from GitHub

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Start a new Codex task after installation. Review and trust the bundled hooks
when Codex prompts you; untrusted hooks are skipped by design.

### On-demand workflow observations

Describe the work you want inspected or improved; Task IDs are not required.
For a fictional example: “找範例發佈流程的 Task，觀察重複檢查的原因，先提出改善建議。”
The `workflow-observe` skill resolves bounded native Task names/summaries and
locks exact identities before observing. A clear match proceeds; ambiguity gets
one meaningful question, not a request to copy UUIDs. “直接改善流程” can authorize
scoped implementation; an observation/suggestion request remains read-only.

Use `/skills` → `workflow-observe` to select the skill explicitly. It
resolves native Task/agent names, compares bounded evidence with an explicit
cursor, and returns changes plus a private report link. Observation is read-only
with respect to Codex and the workflow; only its separate private evidence store
is written. It never starts a monitor or intervenes in agents implicitly.

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py workflow
python3 plugins/codex-run-budget/scripts/run_budget.py workflow observe --thread TASK_SELECTOR
# Only if descendants are part of the requested scope:
python3 plugins/codex-run-budget/scripts/run_budget.py workflow observe \
  --thread TASK_SELECTOR --include-agents --after PREVIOUS_CURSOR
```

Default cap is 8 Tasks, with a 256 KiB transcript tail per Task. A cursor is bound
to the exact roots, descendant option and cap. Local evidence is not native live
state or workflow acceptance. Use the skill's native status confirmation when
needed. Recurring observation is opt-in through Codex's automation tool after
the user explicitly asks to enable it. See [workflow observations](docs/WORKFLOW_OBSERVATIONS.md).

### Task reports

Start with a no-scan menu, then select one scope without starting a budget:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py report
python3 plugins/codex-run-budget/scripts/run_budget.py report task --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report agents
python3 plugins/codex-run-budget/scripts/run_budget.py report window --windows 5h
```

In Codex, use `/skills` and select `usage-task`, `usage-agents`, or `usage-window`.
The Task/window commands default to the current Task, 20 pages and 20 details;
they save the report and return only a short summary/link. `report tasks` lists
10 native names/selectors without reading token transcripts. `report agents`
shows immediate parents and root Tasks using native names and agent aliases.
`report tree` explicitly includes descendants in usage analysis. Cross-Task
analysis requires `report window --all-tasks --windows WINDOW`; it is never an
implicit fallback. `--full` explicitly opts into full stdout output.

Includes Task/turn and model/Fast/reasoning evidence, independent time windows,
saved native account quota, and clearly separated Standard/Fast credit scenarios.
Markdown (the default) works in Codex's file viewer; HTML adds offline filtering
and print/save-as-PDF; JSON preserves the evidence schema. Exact `--thread`
filters accept exact UUIDs or listed selectors and run before transcript analysis.
Native names may be sensitive; they are not prompt/title/preview fallbacks.
Output never overwrites an existing file. See
[report semantics and coverage](docs/REPORTS.md) before interpreting totals.

### Automatic inline usage cards (v0.13)

Automatic receipts are **on by default**, independently of token budgets.
Use the persistent report-only switch (it does not disable the plugin):

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report enable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report disable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report status
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report list
```

An explicit off setting is preserved across upgrades; only a missing settings
file gets the default on value. You can also ask Codex to “turn automatic
per-turn reports on/off”; it runs the same switch and reads back the result.
This is a local plugin setting, not a new native Codex Settings toggle.

When enabled, `UserPromptSubmit` creates a private pending Markdown target and
provides a short instruction to run one deterministic preview command before the
normal final answer. That command returns only a native `visualize` reference:
the answer displays an inline usage card rather than a clickable report link.
Its HTML fragment uses a fixed bundled template, not model-generated markup.
If the prompt hook missed a start, the first eligible supported tool hook can
recover that exact active turn's native start and issue the same instruction once.
Duplicate tool events do not reread the transcript or add more report context.
Recovery needs a valid start in the bounded local record; no hooks/no tools and
missing or stale records cannot guarantee an inline card.
The first eligible `Stop` separately fills the Markdown target and writes HTML/JSON. The
default threshold is **zero**: elapsed time is information, not a cost gate.
This is a turn-stop receipt, not proof the whole Task is complete. It makes no
model/API requests from its Python renderer and never requests continuation.
The normal model/tool round trip, instruction and final reference use tokens;
this is not zero-token display or a zero-additional-inference guarantee.
Local CPU, disk and storage still have a cost; asking a model to read the result
later uses normal tokens. Disable with `auto-report disable`; existing files
remain. For an explicitly desired duration filter, use
`auto-report enable --threshold-seconds 300` (strictly greater than 300 seconds).

These bounded receipts are lighter than the manual multi-window report above:
parent boundary counters plus deduplicated descendant request records in the
current turn's observation window, with no unrelated Task scan. The existing
pre-final call also makes one bounded, read-only native quota capture: account
remaining percentages and movement since this Task's immediately previous card.
These are shared account observations, not quota consumed by this Task. Actual
native window durations are used for every plan, including Pro; reset or
incomparable snapshots establish a new baseline, and unchanged percentages do
not mean zero usage. Start and Stop do not refresh quota; Stop retains the
pre-final quota timestamp. `SubagentStop` saves available numeric evidence; the parent's one
pre-final read reconciles late records without asking children to self-report,
wait, stop or continue. Parent/child subtotals, names/ownership and incomplete
coverage are shown in the card. Missing counters stay unknown; Stop may precede
the final persisted usage event. The inline card is explicitly a **pre-final
snapshot**; it excludes subsequent tools/final text and is not updated by Stop.
From v0.14, the Stop adapter can launch one report-only background completion
check: at most eight bounded reads within 25 seconds. An explicitly matched
native `task_complete` event permits a separate revision with final parent
counters; later-turn records are excluded. The child observation window and
saved quota timestamp remain unchanged. Missing or incomplete evidence stays
provisional/partial; no Governor event, model call or continuation is generated.
Read `auto-report list` to locate the latest report. The original Stop JSON/HTML/Markdown
and inline card stay unchanged; the report index points to a separate completion
revision. Report files show revision, completion
status and update time. The mobile A/B experiment found that a new reference
read the updated file while the original card retained its old contents;
reopening a Task is not a supported refresh mechanism.
The reference is model-written in the normal answer, not an edit to a sent answer.
Report labels follow Codex's saved desktop language choice; Auto uses a read-only
host-language fallback. Bundled languages: English, Traditional/Simplified Chinese,
Japanese, Korean, German, French, Spanish and Portuguese; unsupported languages
fall back to English. No model translation or additional report turn is used.
See [language selection and limits](docs/AUTO_REPORTS.md#report-language).
An incompatible exact-output request or disabling reports takes precedence;
model omission and native presentation support are still limitations. Preview
failure skips the card without retries. Missing observations are unknown, not zero.
See [automatic receipt boundaries](docs/AUTO_REPORTS.md).

### Updating an installed version

With other Codex tasks idle, run from this checkout:

```sh
python3 scripts/update_plugin.py
```

The helper calls the official installer, snapshots existing version directories,
restores removed versions even if installation fails, and prepares the new
SHA-pinned runtime outside the plugin cache. Recovery copies remain under
`~/.codex/run-budget/cache-backups` (or `CODEX_RUN_BUDGET_HOME`). The helper does
not alter hook trust, enabled states, or budget policy.

After each update that changes hook definitions, open `/hooks` in the Codex CLI
and review the changed `codex-run-budget` hooks again. Trust is tied to the exact
hook hash: a plugin can be installed and enabled while its hooks are `modified`
and skipped. Restarting the app or creating a Task from a phone does not grant
trust. Finish the review before starting a new Task. The updater prints this
reminder but never changes trust state or uses a trust-bypass flag.

Starting in v0.4.2, trusted hook commands contain a small bootstrap and the exact
runtime hash. They load verified bytes from the durable `runtimes` directory,
so deleting/replacing the plugin cache does not remove an initialized task's
hook code. Older tasks keep their pinned code, not an unreviewed newer version.
Missing or corrupt runtime code blocks admission with structured hook output;
Stop does not request a retry loop. See [upgrade safety](docs/UPGRADE_SAFETY.md).

One-time migration: tasks created with legacy pathname commands still reference the
old cache path. Finish/restart those tasks, retain their cache until then, and
review/trust the new commands. The new bootstrap cannot retroactively replace
a command already captured by an old task. Keep tasks idle for this migration.

For local development:

```sh
git clone https://github.com/easyvibecoding/codex-run-budget
cd codex-run-budget
codex plugin marketplace add "$PWD"
codex plugin add codex-run-budget@codex-run-budget
```

## Quick start

Begin a task message with a control line:

```text
run-budget:start tokens=100k

Implement the feature, use subagents only when they save time, and run tests.
```

The `100k` ceiling is shared by every transcript source attached to the parent
Codex session id. The plugin starts a new audit epoch and uses the token totals
already present in the transcript as its zero baseline.

Choose a ceiling large enough to cover at least one full Codex request,
including system/developer context and cached input. A ceiling smaller than the
first request cannot stop that request because plugins have no pre-model hook.

Useful controls:

```text
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

`resume tokens=` sets a new absolute ceiling; it must exceed observed spend.
`start` creates a fresh epoch while preserving earlier events.

### Start options

```text
run-budget:start \
  tokens=100k \
  warn=80% \
  block_agents=90% \
  tools=200 \
  agents=4 \
  inflight=8 \
  output=50k \
  repeat_steer=3 \
  repeat_halt=5 \
  fail=closed
```

Put all options on the first control line (the line wrapping above is for
readability). Counts support `k` and `m`; ratios accept a decimal or percentage.
Quoted examples later in a message do not activate controls. Unknown or duplicate
options are rejected to catch typos.

## Enforcement model

```text
main agent ─┐
subagent A ─┼─ session_id ─ Governor ─ SQLite run ledger ─ ALLOW / STEER / HALT
subagent B ─┘
```

Codex documents that subagent hooks use the parent `session_id`. Every hook
process therefore opens the same run record. `BEGIN IMMEDIATE`, unique
tool-use ids, and leases make admission atomic and retry-safe across concurrent
hook processes.

Policy order is deterministic:

1. Reconcile observed transcript usage.
2. Honor an existing HALT.
3. Enforce token, tool-call, and repeat ceilings.
4. Enforce in-flight and active-subagent ceilings.
5. Inject STEER context near the budget.
6. Admit and record the supported tool call.

No model decides whether its own budget policy applies.

## Honest limitations

Codex hooks are not a universal model gateway:

- `UserPromptSubmit` can block a new user turn before its model request, but
  plugins do not receive a pre-hook before every model request inside a turn.
- `PreToolUse` covers shell, unified exec, file edits, MCP tools, `Agent`, and
  most local function tools. Hosted tools such as web search and specialized
  tool paths may not use the local hook path.
- In the current installed Codex validation, cumulative `token_count` data was
  persisted at turn completion, not between the model response and its Bash
  tool call. A whole turn can therefore cross the ceiling before `Stop`
  observes it; subagent totals may likewise arrive only at a later lifecycle
  boundary.
- Tool-output caps act after the tool ran. They can prevent oversized output
  from continuing normally, but cannot undo tool side effects.
- ChatGPT/Codex subscription usage and provider billing may apply accounting
  rules that differ from transcript `total_tokens`.

The practical guarantee is: **once the shared ledger observes HALT, later
supported local tool calls and new user turns are refused until resume or
off.** An installed Codex test confirmed that the next user turn completed
with zero model tokens and no tool call after HALT. See
[docs/VALIDATION.md](docs/VALIDATION.md). This is not a claim of zero token
overshoot or complete tool mediation.

## Privacy and local data

The default data directory is:

```text
~/.codex/run-budget/
```

Set `CODEX_RUN_BUDGET_HOME` to override it. The SQLite database records:

- session id and epoch;
- numeric token/tool/agent counters;
- timestamps and policy decisions;
- SHA-256 hashes of transcript paths, tool inputs, and tool results;
- observation health and pending-agent reservations.

It does not intentionally record prompts, command text, tool arguments, tool
responses, or transcript content. Governance and offline audits do not send
telemetry over the network. The automatic pre-final quota capture uses Codex's
signed-in connection for read-only account and rate-limit requests, not token
history. The manual native meter additionally supports usage requests, including
thread IDs explicitly selected for backend usage lookup. Private quota storage
contains allowlisted numeric observations and hashed identities, not raw account
IDs, names, email addresses or provider error text.

Inspect recent runs and privacy-preserving lineage:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py list
python3 plugins/codex-run-budget/scripts/run_budget.py show latest --json
python3 plugins/codex-run-budget/scripts/run_budget.py events latest
```

## Native account quota sensing

Read the current quota percentage without saving a snapshot, or record
observations around normal work:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py meter --no-save
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
# After ordinary work, record another snapshot, then:
python3 plugins/codex-run-budget/scripts/run_budget.py meter report
# Cross-task model / reasoning / Fast observations, no baseline needed:
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --days 1
# Counterfactual Standard/Fast credits for observed tokens, not actual charges:
python3 plugins/codex-run-budget/scripts/run_budget.py meter estimate --days 1
```

The meter preserves each native bucket's actual duration, used/remaining
percentage and reset time. Saved snapshots live in a separate local database;
no budget or hook setting is changed. `--thread <UUID>` requests optional
backend-estimated model credits and tokens; `--json` retains all bounded detail.
Snapshots also detect the native subscription plan and billing route. `tasks`
and `report` accept `--thread` as an exact local Task filter; account percentages
remain account-wide. Historical Fast/effort/plan come only from contemporaneous
metadata, and omitted values remain unknown. `meter rates` shows a dated official
Fast/plan reference, not measured charges or a detected Pro allowance multiplier.

Account percentage-point changes and local model-token observations are shown
side by side, **not allocated proportionally**. Missing official thread usage
is unknown, and unchanged percentages do not prove free usage. Estimates are
not settled billing or included-quota percentages. There is no background
polling or extra model workload. See [native meter details](docs/METER.md).

Snapshots also expose native included-usage permission, credit balance and spend
controls independently; zero purchased credits is not zero included allowance.
The offline `estimate` action splits uncached input, cached input and output
using the dated official rate card, showing Standard/Fast scenarios and excluded
coverage. It never derives actual charges, dollars, or quota percentages. See
[the documented mechanism and code path](docs/METER_MECHANICS.md).

## Development

### Audit recent task and tool records

Get a compact, read-only overview of recent local tasks, even if they never
enabled a budget:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py survey
```

Defaults are seven days and up to 200 recently modified transcript pages from
Codex's local sessions directory. No setup or new budget policy is required.
Use `survey --json` for per-thread evidence, or optional `--days` / `--limit`
to adjust the cohort. Discovery uses file modification time; analysis filters
by record timestamps. The report explicitly identifies limited coverage.

The survey distinguishes actual thread identity from the shared session key,
attributes usage and waiting to explicit turn/model metadata, and merges
paginated files without summing cumulative snapshots. It reports actual
`wait_agent` timeouts separately from event returns and unknown outcomes.
Changed versus unchanged result hashes help review repeated tool work; neither
is a semantic judgment about progress or waste.

Use `survey --lifecycle` to inspect turn endings, interruptions, later turn
starts, and compaction counts. The default summary includes lifecycle totals;
the detail view shows at most 20 hashed turn rows, with full evidence in
`survey --json`. A missing ending is not proof of a running or stuck task, and
a later turn is not proof that the same work recovered. See
[lifecycle interpretation](docs/LIFECYCLE.md).

Analyze an existing local Codex JSONL transcript, including tasks that never
enabled a budget:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/rollout.jsonl
```

Pass several paths to audit an exact multi-page cohort. Custom identifiers and
model names are hashed; only a fixed allowlist of standard model names appears
as labels. Request data remains distinct from subscription/billing accounting.

The JSON report is read-only and does not open the governance ledger. It reports:

- Request usage deduplicated by response ID, with cached and uncached input
  separated, plus the largest observed request for budget planning.
- The latest cumulative snapshot, cumulative decreases, and its difference from
  request totals. These accounting views are never added together.
- Tool call counts, UTF-8 output sizes, call/output elapsed spans, repeated inputs,
  and repetitions after compaction. Tool identities and source paths are hashed.
- Missing, partial, duplicate, conflicting, and unmatched records as diagnostics.
- Deduplicated per-turn lifecycle evidence, explicit versus observed duration,
  compactions, and whether another turn subsequently started in that thread.

Repeated calls are investigation candidates: polling, changed external state,
and required verification can justify them. Timings may overlap and include
waiting. Nested calls inside `exec` are opaque. A single transcript is not a full
session-tree accounting report; do not sum parent/child reports without verifying
their accounting scopes. No request records means unknown usage, not zero. A
nonzero accounting difference or invalid records requires investigation before
using totals for comparisons. No prices or savings are inferred.

Only initial file-size snapshots are read (maximum 256 MiB per page and 4 GiB
per audit); oversized records and unfinished trailing lines are reported and
skipped. A complete final JSON record needs no trailing newline. Raw prompts,
custom names, arguments, outputs, response IDs, and paths are not emitted.
See [audit validation](docs/AUDIT_VALIDATION.md) and
[recent-task survey](docs/SURVEY.md).

### Checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate_repo.py
python3 /path/to/plugin-creator/scripts/validate_plugin.py \
  plugins/codex-run-budget
```

The design and consistency model are documented in
[docs/DESIGN.md](docs/DESIGN.md). Security and disclosure guidance is in
[SECURITY.md](SECURITY.md).

## Prior art and attribution

The shared run ledger, token lineage, and STEER-before-HALT vocabulary are
credited to Microsoft TokenOps in [NOTICE.md](NOTICE.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This plugin is a new Codex
hooks implementation and does not vendor TokenOps source.

Other useful prior art includes Taskflow's observed-usage stop-loss, Codex
Usage Audit, and Codex Token Guard. Codex Run Budget focuses specifically on a
single shared session-tree ledger and deterministic hook admission.

## License

[MIT](LICENSE)
