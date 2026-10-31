# Detect, distinguish and respond to failures

Use the exact frozen Task/host set, descendant option, cap and observation cursor.
Read compact output first. JSON is useful when the next decision needs health,
`unconfirmed_signals` or `response_plan`; do not load whole source conversations.

## Source or observer failure

- A source unavailable or with a foreign header is an observation failure. It
  does not show that the Task failed. Healthy peers continue to be observed.
- After three source failures the cursor records backoff, starting at 30 seconds
  and capped at 300. Respect `next_probe_at`; no shell sleep/poll loop is needed.
  An explicit one-time diagnostic may use `--probe`; keep the previous cursor.
  This is per-consumer state, not a global lease or a recurring monitor.
- A missing exact UUID remains in scope with unavailable catalog/lineage evidence.
  A missing or ambiguous hash selector cannot resolve a new identity. Never
  replace either with a similarly named Task or the calling Task.
- JSON `observation_failed` has a fixed code and retryability. Catalog/store
  failures require source repair or bounded retries; repeating the same failed
  read is not progress. Stop after one bounded retry of the same catalog/store
  error and report the needed source repair. Cursor expiry, scope mismatch and backward clocks need
  an explicit explanation before a fresh baseline, not a silent restart.
- A repaired source restores observability, not retrospective token credit or
  proof that an earlier tool failure was resolved.

## Native status across Tasks and hosts

For an actionable live-status question, use exact `workflow targets` batches of
at most 8 and native `wait_threads`, normally `timeoutMs: 0`. Keep one native
`afterCursor` per batch; the workflow `--after` cursor is a different object.
Do not duplicate targets between batches or pass the calling Task to a native wait.

Local catalog availability cannot establish a remote host's status. Resolve a
remote/cloud Task through its native host identity and supported native tools;
report local telemetry unavailable. A missing local UUID is never remapped to
host `local` by `targets`. A native host/tool error keeps live status unknown;
preserve the target/host and retry at most once when evidence suggests recovery.
If the same error recurs, report the blocker rather than switching tools, hosts
or Tasks. An empty event wait, `notLoaded`, old evidence and `task_complete` are
not themselves failures or workflow acceptance. Read one short output-free turn
only when needed to explain an actionable state.

## Tool failures and response plans

Native completed command/MCP items with explicit Task, turn and call identity
can establish tool outcomes. Opaque wrapper text and missing status stay unknown.
`tool_failure_observed` and `repeated_tool_failure` describe evidence, not a
workflow failure: a nonzero command can be an intentional probe.

`cross_task_failure` means at least two selected Tasks have an unresolved matching
diagnostic signature. Inspect the shared dependency suggested by `response_plan`;
the signature alone does not prove common causality, duplicate work or waste.
Matching successful operations resolve their own recorded failures. Source loss,
coverage gaps, contradictory duplicate results or missing peers cannot clear
unverified incidents; report `unconfirmed_signals` explicitly.

Response plans are fixed diagnostic steps, not executable instructions. Automatic
behavior is limited to the observer's bounded reads, caching and backoff. Apply a
workflow fix only under the user's existing implementation authority, inspect
the target checkout and preserve ownership. Retry business operations only within
their authorized scope and existing idempotency/evidence rules. Notify another
Task only when the user authorized that handoff; preserve named sender/recipient,
exact identities, original failures/usage and any unknown outcomes. Never infer
permission to approve, restart, resume, change models, publish or bypass a refusal.
