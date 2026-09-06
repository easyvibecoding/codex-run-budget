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

## Install from GitHub

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Start a new Codex task after installation. Review and trust the bundled hooks
when Codex prompts you; untrusted hooks are skipped by design.

### Updating an installed version

With other Codex tasks idle, run from this checkout:

```sh
python3 scripts/update_plugin.py
```

The helper calls the official installer, snapshots existing version directories,
and restores versions removed by installation even when the installer fails.
Older tasks can still invoke their original hook code; new tasks load the new
version. Recovery copies remain in the sibling `run-budget-retained` directory.
The helper does not alter trust, enabled states, or budget policy.

Direct `codex plugin add` can delete the cache referenced by an active task and
cause repeated PreToolUse/Stop errors. There is still a brief removal/restore
interval during installation, so keep other tasks idle. This helper cannot fix
Codex cache lifecycle internally or recover versions already deleted before its
first use. Retained versions should only be removed after their tasks have ended.

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

Options can appear on one line. Counts support `k` and `m`; ratios accept a
decimal or percentage.

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
- SHA-256 hashes of transcript paths and tool inputs.

It does not intentionally record prompts, command text, tool arguments, tool
responses, or transcript content. Nothing is sent over the network.

Inspect recent runs and privacy-preserving lineage:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py list
python3 plugins/codex-run-budget/scripts/run_budget.py show latest --json
python3 plugins/codex-run-budget/scripts/run_budget.py events latest
```

## Development

### Audit recent task and tool records

Analyze an existing local Codex JSONL transcript, including tasks that never
enabled a budget:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/rollout.jsonl
```

The JSON report is read-only and does not open the governance ledger. It reports:

- Request usage deduplicated by response ID, with cached and uncached input
  separated, plus the largest observed request for budget planning.
- The latest cumulative snapshot, cumulative decreases, and its difference from
  request totals. These accounting views are never added together.
- Tool call counts, UTF-8 output sizes, call/output elapsed spans, repeated inputs,
  and repetitions after compaction. Tool identities and source paths are hashed.
- Missing, partial, duplicate, conflicting, and unmatched records as diagnostics.

Repeated calls are investigation candidates: polling, changed external state,
and required verification can justify them. Timings may overlap and include
waiting. Nested calls inside `exec` are opaque. A single transcript is not a full
session-tree accounting report; do not sum parent/child reports without verifying
their accounting scopes. No request records means unknown usage, not zero. A
nonzero accounting difference or invalid records requires investigation before
using totals for comparisons. No prices or savings are inferred.

Only the initial file-size snapshot is read (maximum 256 MiB); a trailing partial
line is reported and skipped. Raw prompts, names, arguments, outputs, response
IDs, and paths are not emitted. See [audit validation](docs/AUDIT_VALIDATION.md).

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
