# Design

## Goal

Give one Codex session tree one shared, local budget and an explainable token
lineage. Enforce deterministic STEER and HALT decisions at every Codex hook
seam that supports interception.

## Interface

All lifecycle events enter one deep module:

```python
Governor.dispatch(hook_payload) -> dict | None
```

The instance `Governor.handle(payload)` evaluates one hook event;
`Governor.dispatch(payload)` is the failure-aware bootstrap used by the hook
adapter. Callers do not coordinate SQLite transactions, transcript reconciliation,
idempotency, leases, lineage, or policy ordering. The hook runner and tests use
the same interface. The CLI is a read-only adapter over the same ledger except
for explicit operator halt, resume, and disable commands.

## Flow

```text
Codex hook event
      |
      v
 Governor.dispatch (bootstrap failures included)
      |
      +--> reconcile transcript token_count totals
      |
      +--> SQLite BEGIN IMMEDIATE
      |      expire leases -> evaluate -> admit/steer/halt -> append event
      |
      +--> Codex hook response
             allow / additionalContext / deny / continue:false
```

`session_id` is the run key. Codex documents that subagent hooks receive the
parent session id, so parent and descendant agents use one ledger row. Each
transcript is a lineage source identified by a SHA-256 hash; its cumulative
token counter is converted to a delta exactly once.

## Operator control lines

Put a control line at the beginning of the user's Task message. The parser
accepts `start`, `status`, `halt`, `resume`, and `off`; quoted examples later
in a message do not run. `start` begins a new epoch while retaining earlier
audit events. `resume tokens=` sets an absolute ceiling above observed spend.

```text
run-budget:start tokens=100k warn=80% block_agents=90% tools=200 agents=4 inflight=8 output=50k repeat_steer=3 repeat_halt=5 fail=closed
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

All start options belong on one line. Counts accept `k` and `m`; ratios
accept decimals or percentages. Unknown or duplicate options are rejected.
`tokens` is required; the displayed values are the defaults for the other
options. `block_agents` must be at least `warn`, and `repeat_halt` must
exceed `repeat_steer`. `fail=closed` pauses supported admissions when ledger
or usage evidence is unavailable; `fail=open` is an explicit operator choice.
The ceiling must leave room for a full request because the plugin has no
pre-model hook for every request.

## Policy order

1. Explicit operator controls.
2. Reconcile observed token usage.
3. Existing HALT state.
4. Token ceiling.
5. Tool-call and repeat ceilings.
6. Active-subagent and in-flight-call ceilings.
7. STEER thresholds.
8. Admit the call with an idempotent tool-use id.

No model participates in policy decisions.

## Consistency

SQLite uses WAL, a busy timeout, foreign keys, and `BEGIN IMMEDIATE` for every
decision that changes counters. A unique `(run_id, epoch, tool_use_id)` key
makes hook retries idempotent. In-flight calls use leases so a missing
`PostToolUse` cannot permanently exhaust concurrency.

Starting a new budget increments the run epoch. Old audit events remain
available, while new counters and transcript baselines start at zero.

See [reliability hardening](HARDENING.md) for observation health, atomic pending
agent reservations, output-aware repeat handling, and schema-v2 migration.

## Enforcement boundary

Codex `UserPromptSubmit` is a pre-model boundary for a new user turn.
`PreToolUse` is a hard pre-execution boundary for supported local tools.
`PostToolUse`, `SubagentStop`, and `Stop` reconcile usage and can keep results
from continuing normally.

Codex does not expose a plugin hook before every model request, and hosted
tools are not covered by local tool hooks. Installed validation also observed
that `token_count` was persisted at turn completion rather than before the
turn's Bash call. Therefore the plugin cannot promise same-turn enforcement,
zero token overshoot, or universal tool coverage. It fails closed at supported
boundaries after HALT is observed and reports the gap explicitly.
