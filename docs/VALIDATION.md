# Validation evidence

## Description-first workflow routing — 2026-09-13 Asia/Taipei, v0.12.1

This is a skill/description/reference update, not a semantic search engine or
observer-runtime change. The skill now resolves plain-language work descriptions
through bounded native names/summaries, then binds exact Task/host identities.
It separates deictic current-Task requests, ambiguous matches, advice-only intent,
authorized implementation and explicit recurring intent. Semantic summaries remain
ephemeral. The deterministic CLI and observation schema are unchanged.

194 existing tests passed; Ruff and repository/plugin/skill validators passed.
A real native listing requested 20 recent Tasks and filtered metadata before
model-visible output. It returned the expected current plugin-development Task
with its native name, short summary and local host, without reading conversation
turns. This is an availability/discovery smoke check, not a blind semantic-match
accuracy benchmark or proof of every ambiguity/authorization scenario.

An isolated `0.12.1+codex.20260912195731` install succeeded. Stable installation
matched source, preserved pre-change 0.3.0–0.12.0 cache identities and saved report
preferences, and changed only 11 reviewed hook trust hashes in the main config.
Native `skills/list` returned `codex-run-budget:workflow-observe` enabled with the
new plain-language description and installed routing reference. All plugin hooks
and the unrelated Railway hook stayed enabled/trusted, without hook warnings.
The hook archive differs from 0.12.0 only in the package version member; no new
model canary, observation schedule or repair of a candidate workflow was run.
Runtime SHA-256: `2b190a4abaac3744b4dcbb2bd3784241de536ec12539b1ad7dd26670fa2cc7d4`.

## On-demand workflow observer — 2026-09-13 Asia/Taipei, v0.12.0

194 tests passed. Eight added workflow cases exercise exact scope and overlapping
root deduplication, native names/parentage, capped trees, explicit cursor binding
and expiry, unchanged-source reuse, append deltas, gaps/reset/truncation,
unavailable/wrong-identity/symlink sources, partial records, clock reversal,
abort/stale/cleared signals, privacy and exclusion of the calling Task from
native wait targets. Ruff, repository/plugin/changed-skill validators passed.

Two real captures of the current Task's capped eight-entry tree took 0.077 seconds
combined in one observed run. The first read 2,280,823 bytes; the unchanged second
read 183,663 bytes and reported no new evidence. Both used no model requests.
These are local read-cost observations, not measured workflow time/token savings
or a latency guarantee. The selected tree was explicitly incomplete. A native
`wait_threads` snapshot of one exact descendant returned `notLoaded` alongside a
completed latest turn, confirming why load state and turn completion stay separate.
The native self-wait guard was also observed; the new target adapter excludes self.

Installed `0.12.0+codex.20260912194725` in an isolated Codex home and generated a
real two-Task named report using that installed CLI. Stable installation matched
the source tree, preserved byte-identical 0.3.0–0.11.0 caches against the pre-change
backup, and changed only 11 reviewed hook trust hashes in the main config. All
plugin hooks and the unrelated Railway hook remained enabled/trusted, with no
hook warnings/errors. Saved per-turn report preferences were byte-identical.
Native `skills/list` returned `codex-run-budget:workflow-observe` enabled from
the stable 0.12.0 cache.

Hook archive comparison against 0.11.0 changed only the package version member;
no lifecycle or enforcement implementation changed. Runtime SHA-256:
`603b59b0d7eccce03f4afa27dd65e82f8acd5ea9d3e0b94da06358ff9773861a`.
No new model canary, recurring automation, background process or intervention
in the observed workflow was created. Continuous mode remains a skill-guided,
explicit-user-opt-in route through Codex's native automation tool, not a new
deterministic scheduler or a zero-token model wakeup.

## Named, scope-first Task reports — 2026-09-12 UTC, v0.11.0

186 tests passed, including native-name-only display (no prompt-like fallback),
nested immediate-parent/root ownership, cycle and traversal limits, exact Task
filtering before transcript audit, output escaping, metadata-only commands,
compact artifact output and rejection of implicit cross-Task scans. Ruff and
repository/plugin/four-skill validators and runtime reproducibility checks passed.

The native current Task name was cross-checked with the app's Task read API.
A real single-Task report selected only one transcript page and returned a short
summary/link. A five-entry agent query read metadata only and displayed agent
aliases, immediate parents and root Task names. A five-entry tree report marked
its descendant selection as incomplete and named Tasks without request evidence;
it did not infer zero usage or silently expand the selection.

An isolated `0.11.0+codex.20260912173629` plugin install succeeded. After stable
installation, Codex CLI 0.154.0 app-server `skills/list` returned all three new
skills enabled: `codex-run-budget:usage-task`, `codex-run-budget:usage-agents`
and `codex-run-budget:usage-window`. These use the supported `/skills` picker,
not a custom native slash-command parser.

Direct execution of the installed pinned UserPromptSubmit and Stop hooks against
the real Task metadata/transcript, using isolated report storage, produced one
receipt with the matching native Task name. This observed run took 0.101 and
0.093 seconds respectively and invoked no model. This is a runtime smoke test,
not a new model turn, a performance guarantee, or proof of visible native UI
delivery. Actual model-turn lifecycle evidence remains the v0.10.0 test below.

Stable installation matched the complete source tree and retained byte-identical
0.3.0–0.10.1 caches against the pre-change backup. All 11 reviewed plugin hooks
were enabled and trusted; only their trust hashes changed in the main config.
The report preference remained byte-identical (enabled, threshold 0), and the
unrelated Railway hook remained enabled/trusted. Runtime SHA-256:
`82cc742570ddeca9181364fa5b8cb436dd3dea4c441baea8f81ca3d65e039057`.

## Default-on report switch — 2026-09-12 UTC, v0.10.1

182 tests passed. The added cases establish that missing preferences default
to enabled without writing settings, explicit off prevents report I/O, and
the switch is reread between start/Stop and across turns. The pinned-runtime
cache-eviction test now also exercises reporting without any preferences file.
Only the missing-settings default and package metadata changed in runtime code;
the lifecycle and enforcement implementation is unchanged from v0.10.0.

An isolated `0.10.1+codex.20260912171543` install returned on from `auto-report
status` without creating the selected data directory, then persisted/read back
off and on through separate CLI processes. No governance ledger was created.
Repository/plugin/skill validators and runtime reproducibility checks passed.
No additional model canary was needed for this settings-only change; the actual
turn/Stop lifecycle evidence remains the v0.10.0 validation below.

Stable installation matched source, retained 0.3.0–0.10.0 caches, and refreshed
only the 11 reviewed hook trust hashes. The saved report preference was byte-for-byte
unchanged. This user remained enabled with threshold 0. Runtime SHA-256:
`0a726c523bd9ece300b76e6ab256455b1cdc3bffed28f6a948cf22be80ac55ab`.

## Automatic deterministic Stop receipts — 2026-09-12 UTC, v0.10.0

180 tests passed, including concurrent Task initialization and duplicate Stops,
strict optional thresholds, zero-threshold immediate reporting, interrupted and
missing-start turns, counter resets/replacement/truncation, bounded scans,
privacy, symlinks, failure isolation, preserved HALT decisions and execution of
the bundled auto-reporter after plugin cache eviction. Ruff and repository,
plugin and skill validators passed. Hook runtime SHA-256:
`ef734ea39e4640078df96ba0be5c3dff2cf9509f0edff324b17ba9b2e384e688`.

Installed `0.10.0+codex.20260912170543` through Codex in an isolated home, then
installed and trusted the reviewed stable-version hooks in the real home. The
automatic marketplace refresh had cached an earlier development snapshot under
the same version. The retention-aware updater rejected its replacement, kept
recovery copies, and succeeded after the development cache was moved aside.
Read-back matched the complete installed plugin tree to source, verified retained
0.3.0–0.9.0 caches, and found only the 11 reviewed hook trust-hash changes in
the main config. A CLI-created trust entry for the temporary test directory was
removed; unrelated enabled states and configuration remained unchanged.

Two real Codex CLI 0.154.0 invocations (a fresh test Task and one resume) used
isolated report storage and the existing configured Sol/medium model. Each
invocation produced exactly one `turn.completed`, one literal assistant reply,
no tool calls, and one automatic Markdown/HTML/JSON receipt. No report-driven
continuation occurred. The fresh Task correctly left usage unknown without a
starting counter. The resumed turn measured 22,485 boundary-delta tokens:
22,478 input (including 22,144 cached), 7 output, 0 reasoning. Fast stayed unknown.
The resumed receipt covered 1.729 seconds, scanned 241,159 bytes and occupied
4,521 bytes across its three files. These are observed test values, not a latency
or billing guarantee; the test model turns themselves consumed tokens.

The JSON CLI emitted an `error`-typed startup item; the diagnostic captured on
resume was the existing `chronicle` unstable-feature warning, not a report
failure. The CLI did **not** expose the informational report message in its
captured output. Hook unit/runtime tests verify the `systemMessage` contract;
visible native UI delivery remains unverified. Opening the generated Markdown
through the app file-viewer tool returned `queued`, not proof it was visible.
No native HTML auto-open or modification of the final assistant answer is claimed.

The user's global auto-report setting was enabled with threshold 0 and read back.
New Tasks load the new pinned runtime; already initialized Tasks retain old code.

## Documented credit scenarios and native controls — 2026-09-12, v0.8.0

154 tests passed, including offline estimate selection, Decimal credit arithmetic,
cached/reasoning subset handling, unpriced Spark/unknown models, unknown Fast
rates, unsupported cache-write bases, reference freshness, credit-only quota
observations, native limit reasons, missing-vs-false controls, permission
independence and contradictory backend cache splits. Ruff and repository,
plugin and skill validators passed.

Official pricing, speed, app-server and workspace-control documentation were
fetched and compared with the installed Codex CLI 0.154.0 generated schema and
the meter's source path. The new field is additive in schema-2 snapshot payloads;
SQLite schema and old payloads are unchanged.

An isolated CLI install at `0.8.0+codex.20260912132946` successfully ran the native
read and offline estimate. A real native response simultaneously reported zero
credits and allowed ordinary included usage, validating why those fields must
stay separate. A bounded one-day scan selected 90 Tasks / 10,957 requests, with
9,780 priceable text-token requests and 1,177 excluded Spark/unknown-model
requests. Historical Fast remained unknown; actual charge and quota-attribution
fields remained null. These are local coverage figures, not billed account usage.

The meter SQLite file SHA-256 was identical before and after both read-only
commands. The hook archive differs from v0.7.0 only in the package-version
member; governance, ledger, transcript enforcement and hook policy are unchanged.

## Cross-task subscription and configuration meter — 2026-09-12, v0.7.0

141 tests passed, including cross-task filtering, within-turn settings changes,
duplicate metadata conflicts, preceding-only context, missing quota-plan clearing,
schema-1 snapshot readback, subscription/billing-route conflicts, Fast/default/
priority separation, privacy and bounded native reads. Ruff and repository,
plugin and skill validators passed. A separate review found unrecognized quota
IDs/display labels could pass through unchanged; both now hash before storage.
Historical plan evidence is restricted to quota observations; absent plan
snapshots clear prior plan context, and invalid explicit Task/turn IDs cannot
inherit an active identity. Negative read-back cases cover all three gates.

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
