# Codex optimization

The optimizer observes supported local Codex hooks through `Governor.handle(payload)`.
It is enabled by default, needs no active run budget, calls no model and never
stops a Task. An existing budget denial wins before any optimization observation.
This design takes inspiration from [Microsoft TokenEconomizer](https://github.com/microsoft/TokenEconomizer)
while preserving this plugin's deterministic governance and content-free storage.

## Commands

From the repository checkout:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer status
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer report --project "$PWD"
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer report --project "$PWD" --channel exec
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer disable
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer enable
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer measure --project "$PWD" --capability collaboration
```

An installed plugin uses `python3 scripts/run_budget.py`. Every command emits
JSON. Reports select one exact checkout directory, resolved and hashed; different
worktrees have independent histories. `enable`/`disable` controls the observation
layer for this installation and persists across runtime updates. Disabling does
not erase earlier observations. A report does not create a missing database.

## Failure-loop advisories

The fold retains hashes of inputs/results, explicit result outcomes, normalized
failure fingerprints, tool categories and counters. It uses explicit exit codes
or error flags, including explicit `structuredContent` exit metadata. Conflicting
exit metadata stays unknown. JSON embedded in unstructured text is never promoted
to native result metadata. Explicit in-progress command events remain pending;
absent results and unknown formats stay unknown.
A string mentioning an error in a file read does not become a failed execution.
Wait tools are excluded from failure evidence. Code-mode `exec` wrappers remain
opaque: quoted or unexecuted helper text is never counted as an actual tool use.

After at least eight completed calls, an execution that repeats a failure at
least three times in the latest 24-call segment may receive an advisory when
inputs changed or edits intervened. A successful recognized local check resets
the segment. There are at most two advisories per turn, at least eight completed
calls apart. Changed failures alone do not trigger the advisory. The message is
an investigation signal, not a claim that progress stopped.
The latest failure must itself recur; an older repeated failure cannot make a new
error look stuck. Alternating two- or three-failure sequences are identified as
`failure_cycle` after three repeats. The plugin's own observer commands are
excluded from this detector's window, gate and cooldown.

Recognized checks include simple invocations of unittest, pytest, Ruff check,
common package test/check/lint/build scripts, and Cargo/Go test/check commands.
Compound shell commands cannot establish a passed-check baseline, because their
final exit status can hide a failed check. The supported list is deliberately
conservative. Arbitrary command execution succeeding is not a passed check.
Help, version, collection-only and settings-display invocations do not count as
checks, and unresolved shell variable expansion cannot establish a check baseline.

History requires a delivered start event and a stopped turn with a passed local
check after the last observed edit, no later execution, no pending calls and no
opaque or unclassified tool. Native calls must be fully paired; stream calls
must have a completed typed event. Interrupted turns are excluded even if a later Stop arrives.
With at least five samples, a nearest-rank p90 calibrates the advisory gate,
bounded between 8 and 24 calls. Histories are separate for parent and agent
roles; explicit exec invocations have a third, separate role. These are
local-check proxies, never workflow acceptance, deployment
proof or permission to change the user's token ceiling.

## Capability and environment advice

The report counts directly observed collaboration, goals and image/media
attempts. An observed attempt protects that capability from a review suggestion.
After five ended turns spanning at least two native root Tasks, an absent
capability may be marked `review_configuration`. This asks for inspection:
the loaded catalog remains `unknown`, and hook absence never proves the tool
was unused. Opaque calls or limited observations suppress those suggestions.
The optimizer does not edit `.codex/config.toml` or disable any capability.
Unknown tools or missing start evidence also suppress review suggestions.

Repeated fixed error categories across at least three turns and two root Tasks
can produce template advice about missing executables/modules, permissions or
connectivity. No learned free-text fact, failing command, module name, host or
error message is saved or injected. These category observations are not a
diagnosis of an environment's current state.

## Code-mode and explicit exec streams

Native hooks can expose only an outer code-mode call and an unstructured result.
The optimizer preserves those outcomes as unknown. It does not parse JavaScript
helper names or fabricated JSON in tool text as execution evidence.

The existing explicit launcher also supplies real `codex exec --json` events:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py exec-activity run --project "$PWD" -- --ephemeral "Perform the requested work"
python3 plugins/codex-run-budget/scripts/run_budget.py optimizer report --project "$PWD" --channel exec
```

Only typed `item.completed` command-execution and file-change events are folded.
An event's output is examined in memory and immediately reduced to hashes and
finite categories. JSON mentioned in an agent message is ignored. Missing,
oversized or malformed stream records mark the turn limited. Advisories go to
stderr; the child's stdout bytes and process exit status are preserved. The
launcher already starts the user's requested model work; observation adds no
model requests or detached agent. It does not interrupt or steer that model.

The stream reader binds the first valid native Task identity and refuses rebinding.
Duplicate starts mark a gap without resetting the turn; exact terminal replays
are idempotent. A valid final JSON record needs no newline. Malformed or oversized
tails, including an oversized unterminated final line, mark coverage incomplete.
A later unfinished turn cannot be hidden by an earlier completion. Gaps that
could hide lifecycle events also make invocation usage unknown; a later summary
does not erase the gap or replace it with zero.

Stream observations use invocation-local turn identities and the native Task
identity when supplied. They are separate from native hook turns, usage receipts
and the parent-shared budget. Hook and stream observations may cover the same
work, so their call counts must not be added together. Stream coverage is not
a full capability catalog and never produces capability-removal suggestions.

## Sensor health and observation-loop protection

`optimizer status` and `report` include `sensor_health`, `evidence_status` and
fixed `coverage_issues`. Health is installation-wide; reports still select one
exact project and one observation channel. Freshness describes the last sensor
write, not process liveness or task progress. Evidence older than 15 minutes is
`old_observation`; backward clocks produce uncertain freshness rather than a
stall verdict. Missing health data is unknown, not zero failures.

The separate `optimizer-health.sqlite3` stores one row of times, counters,
coverage generations and fixed error codes. There is no raw exception text.
Three consecutive observer failures open a circuit for 30 seconds. Repeated
failed recovery increases the cooldown, capped at 300 seconds. After expiry,
one process holds a two-second recovery lease; peers skip observation rather
than retry. Late results cannot release another process's lease. No retry loop,
model wake, timer or detached recovery worker is created. Lock waits are bounded
at 50 ms for health and 250 ms for observation storage.

Dropped/suppressed events advance a coverage generation. On recovery, active
or overlapping turns are marked limited before new evidence is accepted;
earlier settled samples are preserved. A health-store failure makes one
best-effort gap write to the independent evidence store. Simultaneous storage
failure or missing native delivery cannot provide an unlimited loss audit.
These are observation limits, not enforcement over every Codex operation.

A process-local reentry guard prevents recursive observation. Explicit local
input probes set an internal observer marker on their child process. Neither
mechanism bypasses budget policy. Observer output of an unexpected type is
discarded without replacing the Governor's decision. Turning observation off
marks active turns limited; re-enabling cannot retroactively restore coverage.

The foreground `exec-activity watch` reader backs off on unavailable data and
stops after three consecutive unavailable reads, with exit status 1. It emits
one unchanged snapshot rather than an error on every poll. Healthy reads retain
the requested interval; partial results remain explicitly partial.

## Explicit local input probe

`measure` renders `codex debug prompt-input` twice in the selected checkout,
once normally and once with command-line capability overrides. Available choices
are `collaboration`, `goals` and `image_media`; repeat `--capability` to combine
them. It edits no configuration and makes no model call. It reads the CLI's
normal configuration, so its result applies to that exact CLI and checkout.

The output compares canonical UTF-8 JSON bytes. When the local Codex input
explicitly exposes tool schemas, their bytes are reported separately; older
formats without that field return `null` for schema size. The full rendered
input may already include those schemas: do not add the two sizes together.
Dynamic context and CLI-version differences can affect measurements. A failed
probe is unavailable, not zero savings. `saved_tokens` remains `null`: local
rendering does not establish server tokenization, prompt-cache effects, billed
charges or task success. There is no automatic probe, model judge, detached
optimizer agent, model-generated redirect or automatic tool-pruning writer.

## Storage, recovery and scope

`optimizer.sqlite3` is a separate version-2 store, with atomic transactions,
foreign keys, a 250 ms lock timeout and bounded retention: 500 recent turns
globally and 512 call identities per turn. Saturated or conflicting turns are
marked limited and excluded from baseline training. Replay is idempotent while
its observation is retained; retention is not an unlimited audit log.
Raw native identifiers, Task names, prompts, commands, tool inputs/outputs,
transcript content and raw paths are not stored. Identities and content needed
for correlation are SHA-256 hashes; error classes and tool categories are finite.

Optimizer errors do not alter budget decisions. The active fail-closed budget
still denies supported admissions after its own ledger failures. Installing
this feature does not migrate the budget ledger, replace older Task runtime
pins or change hook definitions. A version-1 observation store is backed up with
SQLite's online backup, quick-checked, then upgraded under a write lock with a
locked schema recheck. Existing counts and advisories survive; legacy coverage
is marked limited and does not train the new baseline. The migration resource is
`003_optimizer_sensing.sql`. A failed backup or migration preserves the original
schema and enters bounded observer recovery. For rollback, disable observation,
restore the prior package/runtime and restore the verified version-1 observation
backup if that runtime needs it. The shared budget database is not migrated.

Hook coverage is limited to delivered events with stable Task, turn and source
identity. Missing hooks, hosted tools and opaque code-mode helpers are not fully
observable. The separate stream channel covers only explicitly launched Codex
invocations and their typed events. Parent and child observations are separated, while budget accounting
continues to use the one parent-shared run ledger. No saved observation proves
process liveness, final acceptance, account quota allocation or actual savings.
