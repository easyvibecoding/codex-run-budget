# Validation evidence

## Cross-task subscription and configuration meter — 2026-09-12, v0.7.0

138 tests passed, including cross-task filtering, within-turn settings changes,
duplicate metadata conflicts, preceding-only context, missing quota-plan clearing,
schema-1 snapshot readback, subscription/billing-route conflicts, Fast/default/
priority separation, privacy and bounded native reads. Ruff and repository,
plugin and skill validators passed. A separate review found unrecognized quota
IDs/display labels could pass through unchanged; both now hash before storage.

A real bounded one-day cohort returned 89 identifiable Tasks with model/effort
and token observations. An exact single-Task filter returned only that Task's
requests. Across the older saved quota interval, it reported Astra/low and
1,760,856 local tokens while preserving the same account-wide +1 percentage
point; it did not assign that increase to the selected Task. Historical plan
observations were Pro; service tier was absent or default in the inspected
rows, so Fast remained unknown instead of being labelled off.

The isolated installed cachebuster read the actual signed-in Codex account at
13:05:40 UTC: ChatGPT/Pro, main weekly quota 12% used and 88% remaining. Native
thread usage was unavailable. The account read used `refreshToken:false`, and
only allowlisted type/plan crossed the account source seam. Existing schema-1
snapshots remained readable without backfilling current subscription metadata.

The hook archive differs from v0.6.0 only in the package version member; no
governance, transcript enforcement reader, ledger or hook policy changed.
SHA-256: `12b1399dcda56d4e2ccc0a4e273d9678a4b8b0b56bde61e838400c84247516ee`.

## Native account quota meter — 2026-09-12, v0.6.0

The suite passed 114 tests, plus Ruff and repository/plugin/skill validators.
Coverage includes multiple quota buckets, weekly-in-primary, missing data,
account/plan/reset changes, permission preservation, integer-resolution limits,
backend estimates, conflicting token subtotals, private identifiers, isolated
storage, symlink rejection, native handshake/EOF/deadline failures and exact
local interval edges. The independent review identified a missing-plan case;
it now suppresses the delta instead of assuming the plan stayed unchanged.

Using the actual signed-in Codex CLI 0.154.0 app-server, two native snapshots
captured an increase of one percentage point in the same main weekly quota
window. The bounded matching local interval contained two different models;
the report retained their observed request tokens and left their quota shares
unknown. A separate unused model bucket returned changing reset times and was
correctly marked not comparable. No model workload was created to move the
meter, and no reset-credit mutation or budget control was used.

Account token summary/daily buckets were available. Native estimated usage
for two requested real threads returned `threadUsage: null`; both were shown
as unavailable, never as free usage or a token-to-quota conversion. The adapter
keeps raw responses in memory only; CLI and storage pass through the numeric
allowlist and identity hashing. An isolated installed cachebuster also read
the live quota and the saved two-snapshot/local-token report successfully.

The hook archive differs from v0.5.0 only in its package version member. Native
meter calls are outside hooks and the enforcement ledger. Runtime SHA-256:
`47c9773ab8640edf8df4372809525152e9aad016148719dc5638587a015c645f`.

## Turn lifecycle telemetry — 2026-09-12, v0.5.0

The dependency-free suite passed 92 tests, plus Ruff, repository, plugin, and
skill validators. Fresh read-back review covered identity isolation, replay,
window clipping, contradictory timing/model evidence, privacy, and CLI bounds.
The later-turn index was additionally exercised with 16,000 synthetic turns
(32,000 events): 0.21 seconds on the validation machine. This is a local
scaling check, not a performance guarantee.

Fixed real-task cohort: 101 local pages, from 2026-09-10 20:26:01 UTC through
2026-09-11 22:40:59 UTC. Hashed source identities fixed membership before
implementation; a separate shape/count probe agreed with the new report.

- 143 observed turns: 119 completed, 21 aborted, 3 without a terminal record.
- 12 aborted turns had a subsequent different turn start in the same thread.
  This does not prove same-work recovery; the 9 others are not labelled failures.
- 2 starts were before the lower bound and remained observed context.
- 121 compaction records represented 97 distinct window IDs; 24 were replays.
  3 compactions lacked a usable turn association and stayed unattributed.
- Request usage, model usage, tool aggregates, wait aggregates, raw compaction
  counts, and largest-request totals exactly matched the v0.4.2 baseline.

The cohort remained partial evidence: 3 oversized records were skipped, and
missing terminal/compaction attribution was reported. It is not an account-wide
inventory, a live task-state check, billing usage, or measured token savings.

Native canary: installed v0.5.0 into an isolated Codex home, reviewed/trusted
its hooks, and used the desktop-bundled Codex 0.153.4 app-server. One thread
completed a turn, began a bounded `sleep 20` test command, was explicitly
interrupted by the controller, then completed a new turn. The controller waited
for command execution before interruption: an immediate interrupt after the
`turn/start` response had correctly returned "no active turn to interrupt".

The native terminal statuses were `completed`, `interrupted`, `completed`.
The transcript audit reported `completed`, `aborted`, `completed`, with the
aborted row linked to the later turn. Three starts and three terminal events
were observed. No budget was selected, resumed, or disabled. The successful
canary thread's SHA-256 prefix is `107234b3f3ea`; failed controller attempts
were retained separately and were not counted as successful canaries.

The hook runtime differs from v0.4.2 only in the package version member;
governor, ledger, bootstrap, and admission semantics are unchanged. The pinned
runtime SHA-256 is
`119919542c1d37a14358afe4f0ff7b85823f5b5ba4d4b7b498e463a667a746a4`.

## Reliability hardening — 2026-09-07, v0.3.0

The 44-test suite, validators, existing-ledger migration, installed hook review,
and real two-turn HALT validation are recorded in
[HARDENING.md](HARDENING.md#local-installed-evidence--2026-09-07).
The first turn recorded 52,072 observed tokens against 10k; the next turn used
zero model tokens and executed no tool. This preserves the next-boundary
guarantee, not a same-turn cap.

## Upgrade recovery and restart — 2026-09-06, v0.2.1

Incident: directly installing v0.2.0 removed the v0.1.1 cache while an existing
task still referenced its absolute hook path. PreToolUse and Stop then failed
before the Python hook could run. The operator disabled this plugin's hooks.

Recovery and observed validation:

- Restored the original v0.1.1 plugin tree from commit `c4b9a89`, comparing all
  11 tracked files against Git. No stub or alternate policy replaced old hooks.
- Re-enabled only this plugin's 11 previously disabled hook entries; preserved
  their trust hashes and verified all other configuration was unchanged.
- Ran `python3 scripts/update_plugin.py` to install v0.2.1. The actual installer
  removed old caches; the helper restored v0.1.1 and v0.2.0 before returning.
- Invoked PreToolUse and Stop through each of the three installed versions with
  isolated ungoverned state. All six invocations exited 0.
- Ran a fresh `codex exec --skip-git-repo-check --json` with read-only sandbox,
  the normal saved hook settings, and a `run-budget:status` prompt asking for one
  `pwd` call followed by `HOOK_RESTART_OK`. No hook trust bypass was used.
- The shell call succeeded, the expected final text arrived, and the process
  exited 0. Reported usage: 51,911 input, 25,728 cached input, 71 output tokens.
  No missing-hook error recurred. Unrelated existing feature/icon warnings were
  present. No budget was started, so this is a lifecycle recovery smoke test,
  not a new token-HALT measurement.

The helper mitigates the observed cache deletion; it does not change Codex's
cache manager or eliminate the install/restore interval. Other tasks should be
idle during updates. Backups remain available if installation is interrupted.
Hooks are enabled; this test did not restart the desktop app or other tasks.

## Automated suite

The dependency-free test suite covers transcript reconciliation, shared parent
and subagent accounting, token HALT, STEER thresholds, repeated-call HALT,
tool-output replacement, fail-closed behavior, privacy, and concurrent SQLite
admission.

```sh
python3 -m unittest discover -s tests -v
ruff check plugins/codex-run-budget/lib plugins/codex-run-budget/scripts tests scripts
python3 scripts/validate_repo.py
```

## Installed Codex test — 2026-09-03

Environment: Codex CLI on macOS, plugin installed from the repository's local
marketplace, hooks explicitly trusted for the test invocation.

Procedure:

1. Start a persisted Codex task with `tokens=10k`, `tools=2`.
2. Ask Codex to run one `pwd` command and return `OK`.
3. Inspect the local lineage ledger.
4. Resume the same task and ask for another command.

Observed result:

- The initial model request and one Bash call completed.
- Codex persisted the `token_count` total at turn completion, not before the
  Bash call. The Stop hook reconciled 47,507 observed tokens and changed the
  run to HALT against the 10,000-token ceiling.
- The next user turn was rejected by `UserPromptSubmit` before a model request:
  Codex reported zero input, output, and reasoning tokens, and no Bash call ran.
- The ledger contained `run_started`, `tool_admitted`, `tool_completed`,
  `usage_observed`, and `halt` events in that order.

This validates the advertised next-boundary circuit breaker and disproves a
stronger same-turn or zero-overshoot guarantee. The README reflects that
observed limitation.
