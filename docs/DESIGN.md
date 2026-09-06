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

Callers do not coordinate SQLite transactions, transcript reconciliation,
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
