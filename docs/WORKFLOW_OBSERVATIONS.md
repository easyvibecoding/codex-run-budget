# On-demand workflow observations

`WorkflowObserver.capture()` is the shared deterministic interface. The CLI and
`workflow-observe` skill reuse it. No daemon, timer, model call, network call,
agent message, restart, model override, budget mutation, QA or publishing effect
is part of this module. Existing per-turn automatic receipts remain independent.

## Exact scope and cost

The skill accepts plain-language descriptions of work. Its model-based discovery
uses bounded native Task titles/summaries and, only when needed, short candidate
turn reads. It binds exact IDs before calling the CLI, and asks only when the
workflow cannot be resolved confidently. A described topic never silently falls
back to the current Task. Remote/cloud native targets are not remapped to local
Tasks. Semantic summaries stay ephemeral; no full-history prompt index is built.
This semantic discovery uses normal model tokens; only deterministic capture is
model-free. Natural-language skill selection follows the official
[description-matching mechanism](https://learn.chatgpt.com/docs/build-skills#how-chatgpt-and-codex-use-skills).

Observation and suggestion requests remain read-only. A request that also asks
to implement an improvement carries that authority through the resolved scope;
the skill then uses the target repository's real verification and execution
rules. Improving workflow code is outside the deterministic observer module,
not a hidden side effect of capture. Ambiguity, ownership conflicts and missing
approvals remain explicit. Continuous observation still requires separate intent.

Bare `workflow` is a no-I/O menu. `workflow observe` uses the current Task unless
explicit `--thread` UUIDs or listed hash selectors are supplied. Missing identity
fails, never falls back to all Tasks. Up to 8 explicit roots and 32 total Tasks
are supported, with a default cap of 8. Descendants require `--include-agents`.
Overlapping roots/descendants deduplicate. Every explicitly selected root is
retained; breadth-first descendant selection is bounded and can omit newer or
active agents. A capped tree is never called complete.

The read-only native catalog supplies names, direct parents, root Tasks and exact
rollout paths. The reader validates each transcript's header identity. It reads
at most a 128 KiB header, a 256 KiB tail and small continuity anchors, rejecting
symlink/nonregular sources. There is no recursive transcript discovery or full
history audit. Unchanged files reuse the previous sanitized observation after
identity, size, mtime and boundary-anchor checks.

Raw paths and IDs stay in memory. Only allowlisted native display metadata,
hashed identities, lifecycle kinds, counters and coverage enter the private
observation store. No prompt-like title fallback or tool inputs/outputs are
stored. A local source schema change fails explicitly.

## Explicit cursors and reports

The returned `cursor` refers to one private snapshot. Pass it as `--after` on
the next invocation with exactly the same roots, descendant option and cap.
Separate consumers can keep independent cursors. Scope mismatch, expiry and
backward clock movement error rather than silently starting another baseline.
The SQLite store retains the newest 500 observations; older cursor references
expire. Generated Markdown reports are separate private files and are retained.

Default stdout is a bounded change summary and new/cleared signal counts, not
the entire snapshot. It saves a Markdown report only on a detected change.
`--json` is an explicit full structured response. No automatic model read-back
of the report is required. Changes include changed local source bytes/metadata;
these are not necessarily semantic workflow progress.

Token deltas require the same source identity, nondecreasing size, a matching
boundary anchor and complete append coverage. Counter decreases, inconsistent
components, invalid records and coverage gaps make the delta unavailable.
Unobserved tasks are not zero. Comparable-task counts accompany totals; never
sum a partial cohort as complete workflow usage or allocate account quota.
These are observed boundary counter differences, not final billing.

## Live state and acceptance are different evidence

The last `task_started`, `task_complete` or `turn_aborted` record is an observed
turn event, not a live process state. A stopped turn can leave an unfinished
workflow. Missing records and 15-minute-old evidence prompt a check, not an
automatic stall verdict. Explicitly unknown state is expected.

`workflow targets` returns parameters for native `wait_threads` without reading
transcripts. It excludes the calling Task (native waits reject self-waits) and
restricts each batch to 8 local targets. Use native `timeoutMs: 0` for a requested
snapshot; use native event waits with `afterCursor` for continued waits in an
active turn. A native wait cursor is not a workflow observation cursor.
`notLoaded` is not a failure; the latest native turn may separately be completed.
Read one bounded turn only when an actionable change needs explanation.

Evaluation can use ownership, abort signals, evidence freshness, comparable
token changes and observation overhead to choose the next diagnostic. Direct
tool/wait counts are bounded-tail counts; code-mode wrappers are not unpacked,
and elapsed wait duration, dependency critical paths and semantic duplicate work
remain unmeasured. There is no composite efficiency score. Verify any proposed
optimization against the same work scope and acceptance criteria before claiming
time/token savings. Business workflow quality needs its own tests, receipts,
database or deployment read-back.

## Optional recurring observation

The default is user-triggered. A request to use the observer does not authorize
a recurring monitor. When the user explicitly enables continuous observation,
the skill resolves exact targets and uses Codex's native automation tool,
preferring an existing thread heartbeat over duplicate/new schedules. Its prompt
preserves the scope/cursor, read-only authority and quiet-when-unchanged behavior.
It notifies on meaningful changes, failure, completion or required user action,
while keeping turn completion separate from workflow acceptance.

This matches the official [agent improvement loop's optional heartbeat and human
gates](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop#step-9-close-the-loop).
Scheduled model wakes still consume normal tokens. The deterministic CLI itself
does not call a model. This release creates no recurring automation.
