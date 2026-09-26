# Validation evidence

This file preserves dated release checks. The current package version is in
[pyproject.toml](../pyproject.toml) and the plugin manifest; see the
[changelog](../CHANGELOG.md) for later changes. Historical installed canaries
do not establish the trust or active runtime of a current installation.

## 0.19.9 subagent visualization output — 2026-09-26

The compatible signed runtime has sequence `1790433141` and SHA-256
`50171668c1536565dcebd35495536bcbb96f25e7c1f21352989a438ff0f81628`.
Ruff, all 490 tests, repository and plugin validation, reproducible runtime
checks and signature verification passed. The hook definitions and publisher
bootstrap remain unchanged.

The preview tests exercise verified nested-child relocation across UUIDv7 UTC
dates, preserved relative subdirectories and parent snapshots, unchanged direct
child/workspace output, and rejection of foreign roots, traversal, symlinks and
unproven lineage. Relocation-only `PermissionError` cases cover mkdir and file
creation, a single checked child-workspace fallback, the same collected snapshot
and filename, and no overwrite. Source mutations during rendering or the denied
native write are rejected before either destination is written. Independent
review reproduced these two source-recheck gaps before the final fix and verified
both regressions afterward; ordinary `OSError` does not trigger fallback.

A disposable Codex home installed version 0.19.9. Its manifest, hook definitions,
both runtime archives, release manifest and publisher policy matched the
checkout byte-for-byte. All 36 preview tests passed with package modules loaded
from the installed signed archive. Invoking the installed `SubagentStart` command
against a synthetic native catalog/transcript and then its durable preview
command produced the child's own dated path. A real OS permission denial
(`EACCES`, directory mode 0500) produced the checked workspace fallback; the
fixture's original permissions were restored. Both cards were mode 0600, kept
the observed child counters, and left the parent sentinel unchanged.

An offline harness executed the unmodified reader, schema and path-checking
functions extracted from local Codex Desktop 26.924.22138 (build 11645), with
minimal host adapters and real filesystem I/O. It accepted the installed
runtime's child-root and workspace-fallback files and rejected the parent
sentinel under the same child ID, with the workspace feature flag both enabled
and disabled. The six direct-read checks preserved file hashes and mtimes.
This establishes output-path compatibility for that installed reader; it is
not native GUI painting or model-driven lifecycle verification. Existing Task
runtime pins and previously emitted snapshots remain unchanged.

## 0.19.8 model compatibility matrix — 2026-09-26

The compatible signed runtime has sequence `1790405688` and SHA-256
`0d0698b9f61d007264fc69c31ece36bf39c9139bdcfd49afb50cb383acdd3eea`.
Ruff, all 480 tests, repository and plugin validation, reproducible artifact
checks and signature verification passed. Independent inspection confirmed
unchanged reference payloads across Unicode, escaping and control-character
boundary cases. Archive changes are limited to version metadata, footer wording
and reference serialization.
The eligibility condition precedes command ownership and the preview command;
exact-output requests skip both preview execution and its reference. The final
answer's format determines eligibility, separately from the files produced by
the task. Eligible parent and child replies request the unchanged reference on
its own line. Hook definitions and the bootstrap remain unchanged.

The native model catalog exposed six GPT-5.6 and GPT-6 models. Each was tested
with Codex CLI 0.157.1, the machine's configured v2 model catalog and `high`
reasoning, using an isolated Codex home and installed signed plugin. Each home
retained the previously reviewed hook hashes; native `hooks/list` confirmed
12 enabled, trusted hooks without bypassing review. The browser fixture used
real headless Chrome through a local stdio MCP adapter and CDP; terminal work
computed and read back synthetic file hashes and sizes.

Each model's matrix contains three parent turns and one same-model child:
ordinary browser/terminal work with a child; an exact JSON reply after terminal
work; and ordinary work with reporting disabled after its footer was injected.
Read-back checks use native model/effort records, actual tool completion events,
parent/child identity, preview arguments and counts, exact final replies,
visualization artifacts, Stop receipts and separate completion reconciliation.
Raw transcripts and identifiers remain outside the repository.

The 0.19.7 baseline exposed these failures:

| Model | Exact-output turn | Ordinary child reply |
| --- | --- | --- |
| GPT-5.6 Sol | Unnecessary preview; exact JSON preserved | Passed |
| GPT-5.6 Terra | Preview and appended reference broke exact JSON | Reference omitted |
| GPT-5.6 Luna | Preview and appended reference broke exact JSON | Reference was inline |
| GPT-6 Astra | Unnecessary preview; exact JSON preserved | Passed |
| GPT-6 Sol | Unnecessary preview; exact JSON preserved | Passed |
| GPT-6 Luna | Preview and appended reference broke exact JSON | Passed |

All six baseline models completed the requested browser and terminal work,
maintained parent/child attribution and completion accounting, and handled
disabled reporting. One Terra browser adapter call failed and a same-page
retry succeeded; the underlying adapter exception was unavailable. This was
recorded separately from footer behavior. Earlier browser setup attempts and
an interrupted infrastructure canary were retained separately and excluded
from model verdicts. The finalized CDP adapter is identical in all matrices.

The first 0.19.8 candidate, runtime SHA-256
`35a925afe853f0cec7fef86e91f3887bb1b4339379316830d215607bf99d2e5a`,
passed exact JSON and disabled reporting for all six models. Four models passed
every check. GPT-5.6 Luna's parent and GPT-6 Luna's child removed a separator
space from their reference JSON; marker payloads and paths remained identical,
but literal preservation failed. GPT-5.6 Luna's child emitted no preview or
reference. Its delegated final-format constraint was encrypted in native
records, so eligibility remained unknown rather than being attributed to a
proven model error. Native work, lineage and completion checks still passed.

The second candidate, runtime SHA-256
`73af9855a7cb2af56879983a9f56b0afbe084cbc7e32aeb890c48a451436f3ed`,
narrows the wording to final-answer constraints and emits compact reference
JSON directly. Its ordinary child task explicitly retains
natural-language replies, without adding footer or preview instructions;
strict and disabled tasks and the browser adapter are unchanged. Read-back
recognizes successful shell variable substitution and `sed` reads in addition
to direct fixture reads. Rechecking baseline decisions with the same readers
preserved every pass, fail and unknown verdict.
Split native command output was joined only through an exact matching single
command call. Successful fixture writes alone did not establish parent read-back.

In that candidate, GPT-6 Luna's parent emitted its own correct reference and
also forwarded its child's reference. GPT-5.6 Luna's child again emitted no
preview or reference; the exact child's native initial-message metadata was
empty, so delegated final-format eligibility remained unknown. These findings
were retained. The current candidate explicitly permits only the actor's own
returned reference and prohibits forwarding other agents' references. Its
controlled child task also removes exclusive-work wording while preserving
natural-language replies and no further delegation; it adds no card instructions.
Earlier unknown delegated-format constraints remain unknown; a later controlled
request does not establish their original wording.

The final installed-runtime matrix passed all 92 checks per model, with zero
failed or unknown checks:

| Model | Ordinary parent and child | Exact JSON | Disabled after injection | Receipt identity and completion |
| --- | --- | --- | --- | --- |
| GPT-5.6 Sol | Passed | Passed | Passed | Passed |
| GPT-5.6 Terra | Passed | Passed | Passed | Passed |
| GPT-5.6 Luna | Passed | Passed | Passed | Passed |
| GPT-6 Astra | Passed | Passed | Passed | Passed |
| GPT-6 Sol | Passed | Passed | Passed | Passed |
| GPT-6 Luna | Passed | Passed | Passed | Passed |

Native records confirmed the requested model and `high` for all 24 turns.
All 24 fixture results matched independent file calculations. The 12 ordinary
parent/child previews used their own Task/turn and the signed runtime above;
each final contained exactly its own unchanged reference on a separate line.
The six strict turns ran no preview and returned the exact requested JSON.
All six disabled turns completed their work and made one preview attempt that
returned `disabled`, with no reference, new HTML or Stop receipt. The 18 enabled
receipts retained verified identities and separate revision-2 completion with
explicitly complete accounting. No card reading, report-skill loading or
preview retry was observed. Independent native-record spot checks also verified
both Luna parent/child references. Temporary credential copies and isolated
Chrome processes/profiles were all absent after execution.

This bounded matrix covers one workload at `high` per model, using the configured
local catalog. It does not establish every reasoning level, service tier,
authenticated desktop CUA/X workflow, or Desktop visualization painting. Inline
footer instructions still consume model context, and existing Task pins retain
their earlier runtime and injected wording.

## 0.19.7 usage-card instruction scope — 2026-09-26

The compatible signed runtime has sequence `1790403004` and SHA-256
`caabd59a0a9f4478380c0f46e10c66229aabc0735a97fe57d14ccce669aa60b7`.
Ruff, all 480 tests, repository and plugin validation, signature verification,
and reproducible runtime checks passed. Existing tests cover the delimited
parent and child footer instructions, command ownership, shell quoting,
disabled reporting, start deduplication, and preserved Governor decisions.
The instruction suffix retains its existing 300-character bound.

An isolated publisher store verified and selected the signed archive for a
synthetic new Task. Native `hooks/list` on the active installation reported all
12 hooks enabled and trusted with zero needing review; hook definitions remain
byte-identical to the previous release. This change edits report instructions
only, leaving report lifecycle, admission, and Task pinning unchanged.

These checks establish the emitted instruction's scope and compatible runtime
selection. No model-driven browser canary was performed, and they do not prove
that model distraction or misinterpretation is eliminated. The inline footer
still consumes model context. Existing Task pins and injected messages retain
their original wording.

## 0.19.6 paired review JSON presentation — 2026-09-26

The compatible signed runtime has sequence `1790394896` and SHA-256
`b1672ae5b7b2701e19eb2c0bf1e5dc1e52f0bc4557e3bbd62cda3d356148157b`.
Ruff, all 480 tests, repository validation and signature verification passed.
Synthetic local Git pairs exercised the actual signed archive's initial prompt,
Task-creation instruction and bound relay. All three requested a `json` fenced
code block with visualization references outside it; the relay also passed the
rule to its recipient. Independent inspection confirmed that only presentation
strings changed, and the archive's source matched the checkout.

These checks establish the generated instructions, not guaranteed model
compliance or Desktop rendering. Existing Task runtime pins and historical
messages are unchanged.

## 0.19.6 concurrent child-cache revocation — 2026-09-26

The compatible signed runtime has sequence `1790393593` and SHA-256
`bc7bf797f136469ea0a7b04850da306fa1270020264acb412989c1084e54726f`.
Ruff, all 480 tests, repository and plugin validation, and signature verification
passed. Real SQLite regressions first reproduced stale scans restoring unseen
requests after a parent conflict, including an identity with no prior cache.
They now preserve revocation after database reopen and source removal. Tests also
cover revocation between cache loading or fresh scanning and collection, new
child identities, legacy schema migration, corrupt revocation schema and bounded
storage saturation. The report's revocation snapshot is one final SQLite query;
commits after that query belong to a later report observation.

A fresh isolated Codex home installed 0.19.6. Native `hooks/list` reported all
12 existing hooks enabled and trusted with unchanged definitions and reviewed
hashes. Eight targeted concurrency, recovery, connection-lifetime and Stop identity
regressions passed while importing the actual installed signed zipapp, with no model request. Independent
read-only checks also exercised transaction rollback, cache-only races and
bounded saturation. Governor, ledger and hook definitions were unchanged.

The final runtime also rejected explicit role/lineage contradictions and
unknown roles across preview, Stop and completion, while keeping supported
legacy baselines. Independent SQLite checks covered nine rejection/control
cases and byte-preserved original Stop artifacts. The installed final zipapp
accepted both real parent/child baselines from the recorded 0.19.5 canary and
rejected contradictory or unknown role variants of that same evidence.
The quota timing-index reader now closes its readonly connection on successful
capture and unknown-turn early return; its real-connection regression passed
under Python 3.13 with no ResourceWarning.

Stop verifies the original task, root, direct parent and role before reading its
snapshot. Failed baseline identity skips both the snapshot and descendant
collector, leaves all usage totals unavailable, and retains the original Start
scope. Regression tests first reproduced five invalid-identity cases that still
read observations or collected a nonzero descendant subtotal; the final installed
runtime rejects them while valid root and child controls still collect normally.

This release check proves installed runtime selection and report-cache behavior.
It does not repeat the 0.19.5 model-driven lifecycle canary or establish Desktop
painting. An ordinary scan cannot undo revocation without trusted recovery
evidence; there is no automatic recovery of the same disputed child identity.

## 0.19.5 child lineage and presentation — 2026-09-26

The compatible signed runtime has sequence `1790390014` and SHA-256
`04d0077053b479d9caee5822f0cdbf8bc51a283d9b222bc99dfc482b10274e69`.
Ruff, 466 unit tests, repository and plugin validation, signature verification,
and the staged sensitive-data scan passed. Regressions first reproduced both
orders of contradictory parent metadata, reuse of an older accepted child cache,
missing or changed baseline roots, and incorrect child labels. Independent
review then found a child-to-root role change could bypass the preview guard;
the shared baseline identity check closed that case across preview, Stop and
completion reconciliation. The reviewer's original counterexample now returns
`source_unavailable` without creating an artifact.

A disposable Codex home installed 0.19.5 with a separate Run Budget data directory.
All 12 hook definitions matched the previous reviewed definitions and trust
hashes; only this isolated fixture received those existing grants. Native
`hooks/list` read-back reported 12 enabled/trusted hooks and zero needing review.
A real `codex exec` spawned one child, and both supplied inline preview references.
Installed hooks produced two Stop receipts and two completion revisions. The
child's preview used the child-specific labels, showed its direct parent and
the same hashed selector as the parent report's child row. The saved child
baseline's root and direct-parent hashes matched the parent receipt. Observed
own-turn totals were 53,600 for the child and 62,772 for the parent, with a
separate parent descendant subtotal of 53,600. Receipts contained no raw native
UUIDs. Temporary authentication material was removed after the run.

The canary initially saved a native API capture under the reserved `hooks.json`
filename, causing a configuration warning. It was renamed, and the final native
trust read-back passed. This check proves CLI lifecycle and generated preview
content; Desktop painting was not observed. Token totals are canary observations,
not plugin overhead or account billing.

## 0.19.4 concurrent starts and child preview — 2026-09-26

The signed runtime was rebuilt at sequence `1790388094` with SHA-256
`c33221e03a94278a9245ba86d592e876d8a9f6ce67760ee755618f48d84def61`.
Ruff, 449 unit tests, repository and plugin validation, and signed-release
verification passed. An eight-Task write-lock fixture lost four starts under
the former 0.4-second wait and retained all eight with the new shared two-second
deadline. A separate two-lock test checks that schema creation, the preflight
read, and the write claim cannot each take a fresh full wait. The native hook
timeout remains three seconds; overloaded storage can still yield an explicit
nonblocking report failure.

A fresh disposable Codex home installed plugin 0.19.4 with a separate data
directory. Native `hooks/list` showed all 12 installed commands matched their
previously reviewed trust hashes. Those hashes were seeded only into this
isolated fixture; read-back then showed all 12 enabled and trusted. A real
`codex exec` turn spawned one child. The child's final answer supplied an inline
visualization reference to an existing HTML preview containing its own hashed
selector. The installed hooks wrote parent and child Stop receipts plus
completion revisions. The child selector matched the parent's child row;
the child observed 36,391 own-turn tokens and the parent separately recorded
47,523 own-turn tokens and 36,391 descendant tokens. Neither receipt contained
a raw Task UUID or nonempty `agent_path`.

This proves the isolated CLI hook and preview-file path, not that the Desktop
app painted the card or that the screenshot's renderer error is gone. Canary
token totals include normal Codex context and are not plugin overhead.

## 0.19.3 subagent reports — 2026-09-26

The compatible signed runtime was rebuilt at sequence `1790386733` with SHA-256
`320d5b1c6e6628173aebf89b948a258a1bcb46f0509ece37593a5422732a633d`.
Ruff, 447 unit tests, repository validation and the publisher release check
passed. The package retained the prior 12 hook definitions.

A fresh Codex home and separate Run Budget data directory were used for an
isolated local-plugin installation. Native `hooks/list` first showed 12
untrusted hooks; all 12 current hashes matched the previously reviewed hashes.
Those hashes were copied only into the disposable canary configuration. Native
read-back then showed all 12 hooks trusted and enabled. The maintainer's active
plugin installation and trust settings were not changed by this canary.

A real `codex exec` with one subagent exited 0. The isolated report directory
contained one parent and one child Stop receipt, each with JSON, HTML, Markdown
and a separate completion revision. The child JSON reported
`subagent_turn_stop_boundary`; its short hashed selector matched the parent's
subagent row. The JSON contained no raw Task UUID and no nonempty `agent_path`.
The child Stop observed 15,653 own-turn tokens (`native_turn_counter` from
`native_request`: 15,610 input, including 11,904 cached input, and 43 output).
The parent Stop showed 47,080 own-turn tokens and a separate 15,653 descendant
subtotal. These are observations from this canary, not plugin overhead or
account billing.
The CLI run did not create an inline visualization file. Preview rendering is
covered by synthetic tests; this canary does not prove that the Desktop app
painted the child card.

## 0.19.2 experimental paired-project review — 2026-09-24

The 0.19.2 signed runtime was built and verified locally; its SHA-256 is
`4909b41f1076803d448b1d4e0f62911331617076d6679bb2a5637685f8422a64`.
The installed Codex plugin cache and publisher status reported 0.19.2. A new
real Codex Task was pinned to that digest. The experimental global switch and
the existing `default` pair were enabled. The new named-pair path, overlapping
pairs, isolated cursors and bindings, disabled switches, and unregistered-root
rejection were checked with synthetic local Git projects and the native catalog
fixture; no additional private pair was registered for the live test.

The real Task's Stop observed Run Budget remote `main` advance
`bf38b15..3987435`, reserved the event, then created exactly one Usage Reports
review Task through Codex App. The receiving Task verified the exact source
diff and both remote heads, found the destination contract and four README
languages already aligned, and returned `no-alignment-needed`. The source
Task recorded one-to-one binding and the decision; read-back showed its cursor
at `3987435` and no pending source range. On a later independent Stop, it sent
one summary to that same bound Task and `relay-sent` returned `sent`.

The converse Usage Reports advance `60b6d7c..c0e6033` was then delivered from
the already bound Usage Reports Task to the same Run Budget Task. No third Task
was created. Run Budget verified that the change was documentation-only and
its own contract already matched, recorded `no-alignment-needed`, advanced
the Usage Reports cursor to `c0e6033`, and cleared pending state. The old
Codex project-list paths were symlinks to the moved Git roots; path identity
was checked by resolving both roots before Task creation. This live test covers
the existing `default` pair; multi-pair fan-out and off-switch behavior remain
unit-tested rather than live-Task verified.

The full local suite passed 439 tests, Ruff, repository validation, Plugin
Creator validation, and staged sensitive-data scan. The first remote CI run
exposed a test-only race during temporary-directory cleanup of a detached
report completion reader; the test now waits for that reader to settle. The
pre-push history gate now audits the refs being pushed so private local Codex
checkpoint refs cannot block a clean public branch. Its exact-ref behavior was
checked against a synthetic private checkpoint, while the pushed `main`
history passed the same sensitive-data scan with zero findings.

## 0.18.0 documentation and isolated installation read-back

Checked on 2026-09-24 in this checkout. Ruff, all 422 unit tests, repository
validation, and local-link checks across 26 Markdown files passed. A fresh,
disposable `CODEX_HOME` installed this checkout's marketplace and plugin
0.18.0. The installed CLI exposed the documented command groups, and signed
runtime status reported active version 0.18.0. This check did not grant native
hook trust or run a model, so it verifies installation and local CLI selection,
not current-host enforcement or Desktop rendering.

## 0.17.0 signed updates and native trust continuity

Validated on macOS, Python 3.12.8 and Codex CLI 0.154.0 on 2026-09-17.

- All 419 unit/integration tests passed, including independent OpenSSL signing,
  actual fixed-command execution of signed A/B runtimes, old Task pin retention,
  signature/payload/metadata rejection, anti-replay rollback, corrupt-cache
  fallback, disabled and in-flight updates, private hashed state, future entry
  migrations, bounded worker scheduling, and the packaged hook/CLI.
- Ruff, deterministic artifacts, signed manifest/runtime verification, plugin
  validation and the staged sensitive-data scan passed.
- A real native CLI canary installed `0.17.0+canary.A` in a disposable
  Codex home. Trust grants were seeded once in that isolated fixture only.
  The installed `UserPromptSubmit` command started its ordinary background worker,
  fetched the signed `0.17.0` runtime from the public GitHub `main`
  endpoint, and activated its exact published digest. No model call was made.
- A new synthetic Task's actual hook executed the published runtime. The older
  Task's verified pin remained on A. Native `hooks/list` reported all
  **12 hooks enabled and trusted**, with identical hashes before and after
  the automatic update. The entire isolated native config file was unchanged.
- A subsequent normal package reinstall from A to the published version also
  preserved all native hook hashes and trust states without another grant.

Published runtime SHA-256:
`98c46fa2be03e57874c43c93b0ef267f1bec832260979ad9e1f2a71b69c811a7`.

This proves real download/verification/activation, installed hook execution and
native trust classification. It is not a model-driven Desktop rendering test.
Migrating an existing pre-publisher installation still requires one review of the
new fixed entry. Future hook/key/entry changes require their own native review.
See [signed update controls and boundaries](SIGNED_UPDATES.md).


## 0.16.0 repository updater compatibility

The repository-side retention updater now validates the standalone reminder's
exact embedded source and event independently of the pinned main runtime.
Unknown commands, extra arguments, duplicate reminders, and missing main
runtime commands remain rejected. No plugin package or hook definition changed.

All 407 tests, Ruff and repository validation passed. A fresh isolated Codex
home ran the actual `scripts/update_plugin.py`, installed 0.16.0, and prewarmed
runtime `ceb2314b78ea03ed25fdb2e678fb2075ff85c42a4291afa7f4570f848f089664`.
Installed and retained bytes matched source; no native trusted hashes were set.

## 0.16.0 first-prompt update and trust notices

Validated on macOS, Python 3.12.8 and Codex CLI 0.154.0 on 2026-09-17.

- All 405 tests passed, including first-prompt/installation deduplication,
  cache expiry and failure backoff, unknown trust, disabled hooks, scoped plugin
  identity, private hashed state, bounded/reaped native RPC, independent embedded
  commands, CLI fallback, and verified TLS with the macOS system-CA fallback.
- Ruff, repository/runtime validation and Plugin Creator/skill validation passed.
- A fresh isolated Codex home installed 0.16.0; installed runtime and hook bytes
  matched source. Its actual installed CLI fetched the public GitHub manifest
  successfully and read native pending trust. No model request was made.
- A separate native upgrade canary installed synthetic versions 9.0.0 and 9.0.1
  using the real plugin CLI. Trust was seeded only in disposable isolated homes.
  `hooks/list` observed all 12 hooks trusted before the upgrade; afterwards the
  11 changed main hooks were `modified`, while the standalone reminder retained
  exactly the same native hash and remained `trusted` across cache-version paths.
- Invoking that installed reminder emitted both update and reauthorization
  notices, then no duplicate on the next prompt. After isolated re-trust, the
  trust warning disappeared. The cached-release/native-trust fixture took
  0.131 seconds; this is an observation, not a production latency guarantee.

Installed runtime SHA-256:
`ceb2314b78ea03ed25fdb2e678fb2075ff85c42a4291afa7f4570f848f089664`.

The test proves native trust classification and the actual handler's output. It
is not a model-driven Desktop rendering test, nor evidence that untrusted hooks
can execute. First installation of the reminder still requires user review.
The maintainer's active installation and hook grants were not changed.

## 0.15.0 project exec activity

Validated on macOS, Python 3.12.8 and Codex CLI 0.154.0 on 2026-09-16.

- All 393 unit/integration tests passed. New coverage uses synthetic catalogs
  and real local subprocesses for exact project scope, foreign metadata, symlinks,
  native/legacy counter separation, same-source resets, distinct resume launch
  attribution, private hashed state, hook notice deduplication, partial rendering,
  exit propagation, ambiguous JSON usage and nonblocking telemetry failures.
- Ruff, repository/runtime validation and Plugin Creator validation passed.
- Fresh isolated Codex homes installed the plugin from its local marketplace.
  The installed bootstrap and pinned runtime emitted one exec notice after a
  synthetic catalog insertion and none on repetition. The post-tool call took
  0.0842 seconds in this small fixture; this is not a production latency bound.
- Installed CLI list/render and source identity read-back passed. An installed
  launcher invoked the real Codex binary with `exec --help`, forwarded its output
  and recorded start/exit with status 0. This smoke made no model request.
- Read-only parsing of one selected real native exec session found its metadata
  and completion event. Parent ownership and missing usage stayed unknown. No
  real transcript, identifier, path or generated report is included here.

Installed runtime SHA-256:
`aefdd45c2d5c664b736a9b33a0f36adfaaa24e874ab40fd6ee931ef6ff44976c`.

The hook test uses synthetic native state and actual installed hook commands; it
does not prove every Desktop host delivers or displays every hook event. Native
turn completion does not prove process exit. Only instrumented launches retain
receipts for ephemeral runs; no background service or shared-budget enforcement
was added. The maintainer's active plugin setup was not changed.


## 2026-09-13: counter-source isolation (0.14.1)

- Installed `0.14.1+codex.20260913150757` into a fresh isolated Codex home and invoked its actual bootstrap hooks. The installed runtime bytes matched the freshly built package.
- A synthetic legacy baseline of 12,000 and later legacy total of 12,500 coexisted with a native thread total of 9,000 and native turn total of 500. Stop returned in 0.136 seconds with `native_turn_counter`, `counter_source: native_request` and turn usage 500, instead of a false counter reset.
- After a native thread total of 9,500, native turn total of 1,000 and explicit completion, the pinned background worker published revision 2 with usage 1,000. A next-turn 9,999,000 counter was excluded. Original Stop JSON/HTML/Markdown bytes remained unchanged.
- All 377 Python tests passed, including real same-source declines, invalid latest native records, first-turn proof, cross-source fallback rejection and a native turn decrease across bounded snapshots while the thread total rises. The prior preview and reconciliation fixtures now model consistent native source continuity when testing a true reset or later usage.
- Ruff, repository/runtime validation, plugin manifest validation and the sensitive-data gate passed. Governor, Ledger and budget transcript source remain byte-identical to the preceding release; existing HALT, STEER, deny and report-failure tests passed. The synthetic ungoverned Stop emitted no new budget decision fields.
- This proves isolated installed-hook accounting and policy preservation; it is not a new native UI/trust observation or a billing-accuracy guarantee. The maintainer's active installation was not changed by this validation.

## 2026-09-13: bounded completion reconciliation (0.14.0)

- A fresh isolated Codex home installed `0.14.0+codex.20260913144124`. Its actual installed bootstrap hooks returned Stop in 0.1117 seconds and the pinned worker revised synthetic turn usage from 200 to 500 after completion. The next turn was excluded; all Stop JSON/HTML/Markdown bytes and the Governor response were preserved. This is an installed-hook invocation, not proof of new hook trust in the maintainer’s active Task.
- Final runtime SHA-256: `85be9a7647824817ceaa3974927de264175d43be68eb7e0ca6ca04ebd279e783`.

- Ported the report-only completion worker and exact-turn completion snapshot from Codex Usage Reports. Governor, Ledger and budget transcript source are unchanged; the Stop adapter preserves their original result before scheduling reporting work.
- Synthetic regression starts with a 200-token Stop delta, writes a late 500-token native turn counter and explicit completion, then verifies revision 2. A subsequent 9,999,000-token counter and later model context cannot enter that completed turn's report.
- Original Stop JSON, HTML and Markdown stay immutable. The timing index selects the separate completion revision; edited files, symlinks and pre-existing revision targets are preserved.
- Worker tests exercise missing completion, counter reset, disabled reporting, duplicate delivery, foreign sources, launch failures, bounded process completion and private selector handling. Adapter regressions verify that worker failure cannot call Governor or change HALT, STEER, block or deny results.
- All 368 Python tests passed, including 18 completion-worker and five budget-adapter regressions. Ruff, repository/runtime validation, `git diff --check` and the worktree sensitive-data gate passed (zero findings). The signal regression uses a real subprocess alarm; the collector's ordinary exception handler cannot swallow the deadline.
- A real source-hook subprocess returned from Stop before delayed completion; its detached child observed the late record and published revision 2. This is a synthetic local process test, not a new native Codex lifecycle or billing-accuracy claim.
- The mobile A/B experiment separately observed a new reference rendering B/250 while the original A/100 card stayed unchanged after source replacement. The plugin keeps inline snapshots immutable and does not promise Task-reentry refresh.

## 2026-09-13: remote report text visibility (0.13.4)

- Changed only the report presentation to use paired browser system colors and scoped typography, removing its dependency on host foreground tokens.
- Verified template parity with Codex Usage Reports 0.1.1 except for the scoped root identifier. That project's fragment CI covers four locales, two widths, two themes, three host color configurations, and Chromium/WebKit (96 cases).
- Rendered this package's own synthetic card and ran 24 additional Chromium/WebKit cases across two widths, two themes, and three host configurations. Collapsed/expanded text contrast, horizontal overflow, and keyboard disclosures passed.
- All 330 Python tests, Ruff, repository validation, and plugin validation passed locally. The reporting counters and governance behavior were not changed.
- This is browser evidence; actual iPhone remote app read-back remains unverified. Existing Tasks may keep their pinned runtime, and existing cards do not refresh. Begin a new Task after updating.


## Missing first-turn report recovery — 2026-09-13 Asia/Taipei

Installed `0.13.3+codex.20260913104501`. All 330 tests passed, plus Ruff,
repository/plugin validation, reproducible runtime verification and the worktree
sensitive-data gate. New regressions exercise the Governor interface with no
prompt event: both tool boundaries, original first/later-turn baselines, unknown
counters, native turn counters, duplicate/concurrent deliveries, terminal and
foreign starts, invalid timestamps, bounded scans, disabled/subagent exclusion,
threshold timing and preservation of budget decisions/context.

The first CI attempt exposed a pre-existing cold-ledger WAL setup race when the
test started eight fresh Governors before any SessionStart (`database is locked`
at `PRAGMA journal_mode=WAL`, not duplicate report instructions). The concurrency
fixture now matches the live missing-prompt lifecycle: SessionStart initializes
the shared budget ledger, then eight tool hooks race with no report timing row.
This does not change or claim to fix simultaneous first-ever ledger bootstrap;
the original fail-closed behavior remains in that separate failure condition.

Three real first-turn canaries on candidate `0.13.3+codex.20260913103738`
deliberately omitted `UserPromptSubmit` only in
their isolated process configuration. Codex CLI `0.154.0` recovered through
`PreToolUse` and, with that hook also omitted, `PostToolUse`. The desktop-bundled
`0.154.0-alpha.6.2` engine separately recovered through `PreToolUse`. Each executed
one `pwd` plus one preview, persisted exactly one report instruction and one
inline reference in its final answer, and produced a Stop receipt whose recovered
start and usage matched the native records. Each used three model requests
(ordinary tool round trip, preview round trip, final), not zero-token rendering.
An earlier test override did not omit the prompt hook and is excluded from these
recovery results. No saved hook was disabled and no curation schedule was edited.

These are live engine/CLI lifecycle tests with controlled missing-hook injection,
not a replay of the original scheduler, proof of its missing-hook cause, or native
desktop paint verification. A run without any eligible hook remains unsupported.
Persisted final-answer read-back found the reference in the final (not merely
commentary), four closed disclosures, and an existing Task-owned HTML file.
The installed deterministic hook/preview fixture also rejected an external path,
recovered the original first-turn counter, deduplicated subsequent hooks, and
confirmed that Stop did not overwrite the inline snapshot.

All 11 hooks read back enabled/trusted with zero issues. Source/cache identities
matched and all 32 prior cache versions were preserved. Report settings and
unrelated configuration were unchanged. Runtime SHA-256:
`9b7897e58475420c955844491b546107ad353fcad50d177b09925142cd027710`.
The final build additionally leaves the original hook-start model unknown on
recovery: a later tool's current model is not historical start-model evidence.
That metadata-only correction has regression and installed-runtime coverage;
the recovery lifecycle and native per-turn settings reader are unchanged.
New Tasks load this fix; existing Tasks retain pinned runtimes. Previously sent
cards and assistant messages are not rewritten.

## Desktop-readable preview paths — 2026-09-13 Asia/Taipei

Installed `0.13.2+codex.20260913101056`. All 320 tests passed, plus Ruff,
repository/plugin validation and reproducible runtime verification. New path
regressions reject external state folders, sibling-prefix matches, another Task's
visualization root, the wrong date, traversal and symlinks before quota/child
collection. The destination is checked again immediately before writing.

Read-only inspection of desktop `26.908.40834` identified a stricter visualization
read policy than full filesystem access. An isolated execution of its unmodified
path/read method, using schema-valid inputs and a local filesystem adapter,
reproduced rejection of the reported external path and read the byte-identical
snapshot from the proper Task visualization root. This is not a live desktop
RPC or paint test. The recovered snapshot passed four browser cases (736/320px,
light/dark), with a border, four closed disclosures, visible primary metrics and
weekly quota, keyboard expansion/collapse, no overflow and no script errors.
Its original partial/missing measurements were not recalculated or filled in.

The installed hooks and pinned preview completed a synthetic start/preview/Stop
round trip without a model: the invalid directory returned no reference or file,
the canonical directory produced one card, and Stop preserved its bytes. Quota
was deliberately unavailable in this isolated fixture. All 11 hooks read back
enabled/trusted with zero issues; source/cache identities and 30 retained old
versions matched. Report settings and unrelated configuration were unchanged.
Runtime SHA-256:
`a5b564a38388b11d7be258feba33c82e7f60e722a957959b9de77eea123c4e6b`.
Existing Tasks keep pinned code; new Tasks load the fix. Previously sent references
are not rewritten. No schedule, curation content, or native App guard was changed.

## Collapsible inline card sections — 2026-09-13 Asia/Taipei

Installed `0.13.1+codex.20260913005626`. All 316 tests passed, plus Ruff and
repository/plugin validators. Regression checks cover four independent, closed
native disclosures with Task/turn metrics outside them, localized summary labels,
missing quota, and unchanged expanded Stop HTML/Markdown. No accounting,
collection, language-catalog, report-switch or hook-policy logic changed.
The closed quota summary exposes only an unambiguous native main-Codex weekly
remaining percentage and previous-card movement/status. Regressions exclude
additional/ambiguous windows and retain fractional, reset, expired, unchanged
and unavailable observations without inventing weekly windows from plan names.

All 36 synthetic browser cases passed: nine languages, light/dark, 736px/320px,
four initially closed sections, visible primary metrics, hidden detail bodies,
independent mouse toggles, Enter/Space keyboard toggles, expanded content, no
horizontal overflow or script errors, and weekly percentage/difference visible
while the quota table is closed. Traditional Chinese collapsed desktop and
German expanded narrow screenshots were visually reviewed. Browser wrapper
evidence is not a claim of native desktop paint; existing immutable cards are
not rewritten. This layout-only change did not require extra model canaries.

All 11 hooks read back enabled/trusted with zero issues. Source/cache identities
matched, all 29 retained old cache trees were preserved, and report settings plus
configuration outside reviewed hook trust hashes were unchanged. Runtime SHA-256:
`4e48e3dc27a52229d57527ce2f04705138f3cda7b356a878587fc067a105fa95`.
New Tasks load the updated card; previously started Tasks keep pinned runtimes.

## Account quota in the per-turn card — 2026-09-13 Asia/Taipei

Installed `0.13.0+codex.20260913003157`. All 313 tests passed, plus Ruff,
repository/plugin validators, reproducible runtime verification and redacted
sensitive-data worktree/history scans. Added regressions cover fractional
remaining-percentage-point differences, unchanged display, reset/deadline and
plan/account changes, missing immediately previous captures, unrelated Tasks,
malformed observations, bounded storage and quota-only RPC protocol requests.
Plus and Pro fixtures use source-provided durations, not fixed plan/window maps.

Independent read-back passed the accounting and privacy boundaries. An extra
eight-worker concurrency check plus a repeated call made exactly one source
read; a failing reader did not suppress Token metrics or trigger a Stop read.
Quota-sourced plan fallback remains usable for comparison only with matching
native account and bucket-plan evidence; it is not displayed as a detected
account plan. No raw account identifiers, emails or provider errors are stored.

A fresh real Codex CLI Task ran two short turns. Each emitted exactly one
preview command, one inline reference, two model requests and one Stop receipt.
The native account plan, main window and separately identified additional
windows reached the card. The first capture established a baseline; the next
main-window observation was unchanged, while changed additional-window reset
timestamps prevented subtraction. The second capture's previous timestamp
exactly matched the first. Stop reused the saved quota display without a new
read, while its independent token counters matched native turn/Task counters.
Between-turn model/effort switching and the absence of a Fast field still passed.
No workloads were run to force a quota-percentage threshold change.

All nine automatic-report catalogs now have 99 matching keys. The bordered
layout passed 36 browser cases: nine languages, light/dark, 736px/320px, blocked
network, no errors or horizontal overflow, three distinct quota rows and working
details. Traditional Chinese desktop and German narrow screenshots were visually
inspected. Browser fixtures are synthetic; CLI reference/counter evidence is not
native desktop paint verification or evidence that immutable cards refresh at Stop.

All 11 hooks read back enabled/trusted with zero issues. Source and installed
trees matched; 27 retained pre-edit cache trees matched their hashes. Settings
outside reviewed hook trust and optional test workspace trust, plus the report
switch, remained unchanged. Runtime SHA-256:
`eb5c3a574e75345c07417dbc63b56bd8a0ea81e3a010e7df8961616dce27290b`.
Existing Tasks retain pinned code; new Tasks load the updated preview capture.
Account snapshots remain shared observations, not per-Task quota billing or a
token-to-subscription conversion. Displayed precision, delayed writes and resets
not observable between captures remain explicit limitations.

## Per-turn settings and Task/turn metrics — 2026-09-13 Asia/Taipei

Installed `0.13.0+codex.20260913001011`. All 293 tests passed, plus Ruff,
repository/plugin validators, reproducible runtime check and sensitive-data
worktree/history scans. Regression cases cover exact-turn model/effort pairs,
returning to an earlier pair, applied settings, reasoning-only updates,
conflicting aliases, reversed timestamps, bounded histories, segmented Task
versus turn counters, reset/recovery and incomplete baseline/end snapshots.
Independent read-back found the incomplete-baseline edge, which now has a
dedicated regression. A native turn counter remains usable independently of
that baseline when its own attribution and counter checks pass.

A real fresh Codex CLI Task ran twice, changing from `gpt-5.6-sol` / `medium`
to `gpt-6-astra` / `low` on resume. Each turn used exactly one preview command,
one inline reference, two model requests and one separate Stop receipt. The
rendered settings and Stop settings matched the respective turn, not the first
Task settings. The first card showed Task 23,155 / turn +23,155; its Stop total
was 46,498. The second card showed Task 75,780 / turn +29,282; Stop showed
Task 105,250 / turn 58,752. Each numeric value matched the corresponding native
counter, and 46,498 + 58,752 = 105,250. These include Task/startup context and
are not incremental report costs or billing measurements.

An earlier canary exposed a timing race: the second preview read the previous
turn's last counter before the new request counter was written. Re-reading that
same observation now produces pending usage rather than zero; synthetic tests
cover this state and preserve genuine newly observed zero differences. No wait,
polling loop, extra preview call or model continuation was added. The final live
canary had both first-request counters available. Stop still cannot update an
already rendered immutable pre-final card.

All nine automatic-report catalogs have 74 matching keys. The new bordered
layout passed 36 browser cases: nine languages, light/dark, 736px/320px, blocked
network, no errors or horizontal overflow, working details, ordered settings
and no Fast field. Traditional Chinese desktop and German narrow screenshots
were visually inspected. These are synthetic browser layout checks plus real
CLI lifecycle evidence, not native desktop paint verification. Mid-turn setting
events are tested with synthetic records; the live test proves between-turn
switching, not that every client persists every in-turn reasoning change.

All 11 hooks read back enabled/trusted, with zero warnings/errors. Source and
installed trees matched; all 25 pre-edit cache versions matched their retained
hashes. Configuration outside reviewed hook trust hashes and optional test
workspace trust, plus the report switch, remained unchanged. Runtime SHA-256:
`819e7f08a6379ae6c520319f79af44d344d8dbce4ddc332e28748c095a94bc8e`.
New Tasks load this runtime; existing Tasks and saved cards retain their pinned
versions. Task and turn primary metrics are parent-only, with observed child
usage kept separately labeled.

## First-request counter visible before the preview returns — 2026-09-13 Asia/Taipei

The next short-turn incident still showed the pending-write state. Scoped native
event read-back found an earlier `token_usage_record` with explicit request,
turn and thread counters; the old reader only accepted the later post-tool
`token_count`. The fix validates attribution and counter consistency and selects
the newest native cumulative snapshot without summing the two sources.

279 tests passed, plus Ruff, repository/plugin validators and the sensitive-data
worktree gate. New cases cover first-request availability, duplicate snapshots,
lagging/event counters, exact scopes, malformed/missing/oversized fields, counter
resets, bounded tails and immutable pre-final versus separate Stop receipts.
An independent code read-back and all 38 automatic-report tests also passed.

Installed `0.13.0+codex.20260912233654`; all 11 plugin hooks read back enabled and
trusted with no warnings/errors. One real fresh Codex CLI turn took 20.238 seconds
and made exactly one preview command, emitting one inline reference and one Stop
receipt. The card contained 23,852 observed tokens, matching the first native
request counter, rather than the pending state. Stop recorded 47,908 tokens:
47,554 input (30,464 cached) and 354 output (0 reasoning), matching the final native
counter. The normal answer followed the tool response: two model requests total,
no report continuation/retry. These totals include startup/task context; they
are not incremental report cost or billing measurements. The 626-byte injected
instruction contained no HTML. Border, Traditional Chinese and the report switch
were preserved; child scope was `none`.

Read-only inspection of the installed desktop renderer found that inline visuals
use cached HTML snapshots, not a filesystem watcher. A same-path Stop overwrite
would not refresh an already mounted card, so the experimental file-finalization
approach was discarded and is not shipped. The result remains a pre-final
snapshot, not a live final bill. Native desktop UI automation was unavailable;
the real CLI lifecycle and file contents are verified, not a new desktop paint.

All 24 pre-edit cache versions matched their retained hashes, and source and
installed plugin trees matched. Configuration outside reviewed hook trust hashes
and optional test workspace trust, plus the report switch, remained unchanged.
Runtime SHA-256:
`51ba3428e6e54b3fb92142b0f24630946feef93360075b749c6594ec278caac4`.
Existing Tasks keep their pinned runtime and saved cards; new Tasks load the fix.

## First-turn settlement and bounded inline flow — 2026-09-13 Asia/Taipei

272 tests passed, plus Ruff, repository/plugin validators and the sensitive-data
worktree gate. Regression cases cover proof-backed original first turns, inherited
history, forks, malformed/incomplete records, later turns and counter resets.
The nine automatic-card catalogs now each have 68 matching keys, including the
explicit first-usage-write pending state. Existing border and switch behavior
remain unchanged; unknown counters are not converted to zero.

A scoped read-only replay of the original fresh-turn incident recovered 65,121
observed tokens from the valid first-turn ending counter. For the separate
historical child-scope incident, 28 children with terminal evidence before the
window were excluded; one child remained partial/unknown because its bounded
large-source scan lacked lifecycle evidence. A child created after that window
was skipped. This does not assert that the unknown child was still running or
that native stopping failed. Synthetic tests preserve active/reused children,
unknown metadata and strict request-window deduplication.

Installed `0.13.0+codex.20260912231053`, reviewed the changed hashes, and read back
all 11 plugin hooks as enabled/trusted without hook errors. A real fresh Codex
CLI turn completed in 18.213 seconds with exactly one command (the pre-final
preview), one inline reference in the normal answer, and one Stop receipt.
The native injected instruction was 620 bytes and contained no HTML body. There
was no report continuation or retry. The preview truthfully awaited its first
usage write; the independent Stop receipt reported `verified_first_turn_counter`
with 46,582 total tokens: 46,050 input (29,056 cached) and 532 output (144 reasoning).
These totals matched that native test turn, include startup context, and are not
incremental report cost. Child scope was `none`, not an unknown zero. The saved
card retained its border, Traditional Chinese locale and immutable snapshot.
CLI reference emission is verified; this is not a new desktop paint test.

An initial install found a previously cached intermediate copy at the same
cachebuster and correctly rejected the changed identity, quarantining it and
preserving the old copy. A fresh official cachebuster followed by immediate
build/install succeeded. All 22 versions backed up before edits were restored
after cache pruning and matched their captured hashes; final source/cache trees
also matched. Configuration outside the reviewed trust hashes and optional test
workspace trust, plus the report switch, was unchanged. Runtime SHA-256:
`eefc167f81631e7b2c0bb2aed6bff80e8482c2b1f4062f816fe5c48a4d999996`.
Existing Tasks keep their pinned hooks; new Tasks load this fixed runtime.

## Human-output localization and repository data guard — 2026-09-13 Asia/Taipei

265 tests passed, plus Ruff and repository/plugin validators. The four bundled
catalog domains each contain all nine supported languages, with matching keys
and placeholder names/specifications: 66 automatic-card keys, 112 manual-report
keys, 102 CLI/workflow keys and 81 observation-summary keys per language.
Only the nine small automatic-card catalogs enter the hook zipapp. Human
renderers preserve numeric source data and original native/model identifiers.
Pure JSON routes do not discover locale or load catalogs; mixed routes localize
only an actually emitted human artifact or terminal summary.

Nine synthetic manual reports passed browser checks at both 736px and 320px
(18 cases), with the real CSP enabled and network requests blocked. The selected
window/Task filters worked, JavaScript reported no errors, and the document did
not overflow horizontally. A synthetic Task name containing HTML punctuation
and a literal `{rows}` placeholder remained unchanged. German and Japanese
screenshots were visually inspected. These fixtures are not actual user usage
and were kept outside the repository. This is not a new native UI lifecycle test.

Installed `0.13.0+codex.20260912222414` using the retention updater and reviewed
the changed hook hashes through the native app-server. All 11 plugin hooks read
back enabled/trusted with no hook warnings or errors. Source and installed
cache identities matched, including all 36 catalogs in the full plugin and only
nine in the hook archive. Deterministic installed-CLI checks covered all nine
languages, canonical model-rate JSON and localized confirmations for JSON-file
exports. The real host report menu selected `zh-Hant`; synthetic Codex homes
supplied the other language settings without changing the real preference.
No new model request was made for this installation check. All configuration
except the reviewed plugin trust hashes, plus the report switch, stayed unchanged.

Read-back also detected missing old caches. The updater's entry backup already
contained only the new version; the cause of that earlier loss was not established.
Twenty previous versions were restored and matched the captured cache hashes.
The immediately preceding version had no matching retained copy: all 48 tracked
plugin files were reconstructed and individually verified against commit
`0d9422fa86d4e069d7eec43db7af36e3e7e3f7f6`, and its known pinned runtime was
prewarmed. Its reconstructed tree did not match the earlier captured cache hash,
so byte-identical restoration of that cache is not claimed. A new retain-only
backup then verified all 22 current/previous version paths. The new runtime SHA-256
is `c1182cdf1e14e36dcf94fe68beee258a8b557524fb4abdca0fb74d6bc1978c40`.

The deterministic sensitive-data scanner and independent redacted Gitleaks
8.30.1 audits found no findings in the current worktree or 23 reachable commits
before this change. The gate also reads staged blobs and bounded zipapp members,
including historical versions. Its 16 tests cover index/worktree divergence,
removed historical credentials, nested archives, corrupt/oversized inputs,
credential-looking filenames and redacted failures. An independent adversarial
read-back passed 14 acceptance checks, including a safe placeholder followed by
a second secret on the same line and fail-closed unreadable Git/archive inputs.

Repository-local pre-commit and pre-push hooks were enabled after checking that
no custom hook configuration would be replaced. CI now runs an independent
index/full-history gate. GitHub's native secret scanning and push protection
were already enabled and had zero open alerts at read-back; no remote security
setting, real credential, or Git history was changed. Author/public attribution
remains allowed and examples use synthetic data. This is evidence for the checked
rules and scope, not proof that semantic names or binary media can never contain
private information; manual review remains required.

## Automatic report language — 2026-09-13 Asia/Taipei

Verified the installed Codex App's setting adapter, without changing preferences:
`localeOverride` has default null, configuration storage and the key
`desktop.localeOverride` in `<codexHome>/config.toml`. The native `locale-info`
provider returns Electron `app.getLocale()` and `app.getSystemLocale()`; runtime
flags can affect selection between them. Hooks do not expose this effective
UI value. This machine had no override, and the exact macOS `AppleLanguages`
read returned `zh-Hant-TW`, while terminal locale was `C.UTF-8`. The resolver
therefore selected `zh-Hant` with source `macos_system_language`. Auto fallback
limitations and unsupported-language English fallback are documented in
[AUTO_REPORTS.md](AUTO_REPORTS.md#report-language), not hidden behind a claim of
exact parity on every client/host.

228 tests passed, plus Ruff and repository/plugin validators. All nine bundled
catalogs have the same 66 keys and matching placeholders. Tests cover regional
normalization, number separators, escaping, preserved native names/usage,
unsupported choices, bounded/no-follow config reads, unchanged preferences,
dynamic rereads, pending-language changes, immutable snapshots and safe failure.
An independent read-back found that the initial Python 3.10 fallback declined
valid multiline instructions before the setting. The repaired quote-aware
scanner passed the 3.10.11 targeted suite, including fake sections inside both
multiline string forms, unfinished strings and non-root dotted keys. The final
runtime was rebuilt and byte-verified after that fix.

Nine fixture-only language variants were rendered at 736px and 320px in light
and dark (36 cases). Every case retained its correct `lang`, a 1px outer border,
no horizontal overflow, child row and working details expansion. German mobile
dark and Japanese desktop light screenshots were visually read back. These are
layout fixtures, not claimed current usage or a native UI language-switch test.

One actual freshly installed Codex CLI turn completed in 16.082 seconds, using
the unchanged desktop/system language preferences. Its normal answer contained
one inline reference to an existing Traditional Chinese card, with one Stop
receipt recording `locale=zh-Hant` / `locale_source=macos_system_language`.
No report failure or report-driven extra turn occurred. Native reported test
usage was 46,302 input (29,312 cached) and 464 output (109 reasoning) tokens;
this includes startup context and is not incremental localization cost. The
reporter itself calls no translation model or network service. The fresh parent
still lacks an initial counter baseline, so its usage correctly remains unknown.

Installed `0.13.0+codex.20260912214237` with the official cachebuster and retention
updater. Source/cache and all retained old-cache identities matched, including
all nine catalogs inside the pinned archive. All 11 plugin hooks and the existing
Railway hook read back enabled/trusted without hook warnings/errors. Only the
11 reviewed trust hashes and the native test workspace trust entry changed;
desktop preferences and the report switch were unchanged. No observer schedule
or budget was enabled. Runtime SHA-256:
`67b26b3fcb15ea6592ec2a9567ee9845eb7ff154331f6b44f9e094bc19a38be1`.

## Deterministic child receipts and inline subtotal — 2026-09-13 Asia/Taipei

`SubagentStop` now saves already-persisted, explicitly child-owned per-request
usage. The parent's existing one pre-final preview reconciles those receipts
with a bounded read of the native descendant set, deduplicates response hashes,
and sums only observations inside the parent turn window. Copied parent records
and child lifetime counters are not added. Rendering and collection call no
model; the normal preview tool round trip still uses tokens. Neither capture nor
reconciliation requests continuation, waits for a child, or changes governance.

219 tests passed, plus Ruff, repository, plugin and changed-skill validators.
Coverage includes real-module capture/preview/Stop integration, explicit identity,
window boundaries, replay, reused agents, parent fork copies, late records,
conflicts, source shrink, scan limits, missing data, report-off preservation,
privacy, escaping, immutable cards and preserved HALT decisions. Independent
read-back reviewed the collection and report integration; the final overlapping
header correction was covered by a new regression and the installed test below.

Two actual installed Codex CLI runs each created exactly one child that answered
an arithmetic question. Each parent completed one turn with one normal-answer
inline reference to an existing card and one Stop receipt. Numeric storage tagged
one request `source=hook` in each run: this proves the child Stop captured usage
before the later parent preview, rather than only relying on preview fallback.
The first run captured 30,049 child tokens, but exposed a conservative false
`partial` marker when a redundant 128 KiB header ended mid-record even though the
tail contained the entire file. That artificial-cut handling was corrected.

The final installed run completed in 22.444 seconds. Its child receipt and card
agreed on 23,783 tokens: 23,738 input (5,888 cached) plus 45 output (38 reasoning).
There was one observed child, one unique request, no pending/missing child and
no selection limit; the scan read 223,822 bytes. Native reported turn usage was
92,744 input (75,136 cached) and 566 output tokens; this includes test/startup
context and is not incremental reporter cost. No report-hook failure or
report-driven extra turn occurred. The pre-existing chronicle unstable-feature
warning remained. The fresh parent's initial counter baseline was unavailable,
so the card correctly showed a known child subtotal and an unknown parent,
not a fabricated complete combined total. Synthetic integration separately
verified 500 parent + 200 child = 700 without double-counting cached/reasoning.

The actual final-test fragment was checked in the official visualize wrapper at
736px and 320px, light and dark: all four cases retained the 1px outer border,
had no horizontal overflow, displayed the child row and expanded details.
Desktop-light and mobile-dark screenshots were visually read back. This checks
layout, not an unobserved claim that the final desktop answer has already painted.

Installed `0.13.0+codex.20260912211751` with the official cachebuster and retention
updater. Source/cache and all retained prior-cache identities matched. All 11
plugin hooks and the unrelated Railway hook read back enabled/trusted with no
hook warnings/errors. Config changes were only the 11 reviewed hook trust hashes
and the CLI-created trust entry for the isolated test directory; saved automatic
report preferences were byte-identical. No budget or recurring observer was
enabled. Runtime SHA-256:
`e6a7a2d610c3180ab1a56eb0256262f5dc9c553c6befe54724f493af60a070ed`.

The longstanding desktop Task still has no current active report-start baseline;
it is not relabelled or repaired with invented values. A fresh Task is the runtime
pickup boundary. The native child Stop is an observation opportunity, not proof
that every final token has flushed. Missing/unreadable/truncated evidence remains
unknown/partial; the pre-final card is immutable and Stop settlement stays separate.

## Bordered card and child-scope clarification — 2026-09-13 Asia/Taipei

The user's desktop screenshot confirms that the preceding v0.13 inline fragment
painted in the actual final answer. This follow-up adds a theme-aware 1px outer
border, 16px corners and responsive padding, and labels the total as parent-agent
tokens. Child aggregation and hook lifecycle semantics are unchanged.

204 tests passed, plus Ruff and repository/plugin validators. The official
visualize wrapper was checked at 736px and 320px in both light and dark themes:
all four cases had a computed 1px border, no horizontal overflow and a working
details expansion. Desktop-light and mobile-dark screenshots were visually read
back. The preview displayed for this turn reuses the preceding immutable
snapshot's values/time with only the new styling and scope labels; it is not a
new usage measurement. This older desktop Task had no active start baseline for
the current turn, and the preview command correctly returned `no_active_start`.

A bounded read-only check of two direct child agents found a persisted
`task_complete` and readable cumulative token data in each. This supports reading
saved child data after completion, not a universal claim about event reliability.
The automatic reporter explicitly excludes children; the separate governed-budget
handler consumes `SubagentStop`. No stop mechanism or child aggregation was changed.

Installed `0.13.0+codex.20260912203442` using the official cachebuster and retention
updater. Source/cache identity and retained prior-cache identities matched. All
11 plugin hooks and the unrelated Railway hook read back enabled/trusted. Only
the 11 plugin hook trust hashes changed in config; saved report preferences were
byte-identical. The archive differs from the preceding installed build only in
the card template and package version member. No new model canary was needed for
this presentation-only change. Runtime SHA-256:
`27dfab9ac356db863214de5951dfbedfba64f71886dc3cb7df80cacf3f1b6c34`.

## Inline pre-final usage card — 2026-09-13 Asia/Taipei, v0.13.0

The reported desktop failure was reproduced from local evidence: the preceding
root turn had a `reported` timing row and a named Markdown receipt, but its final
answer screenshot had no usage report. `systemMessage` is a warning/event-stream
message, not a final-answer attachment. The new start hook gives one preview-tool
instruction; Python renders a fixed fragment and returns only the native visualize
reference. The model places it in the normal answer. Stop settlement stays separate.

204 tests passed, plus Ruff, repository, plugin and changed-skill validators.
Coverage includes switch preservation, pending/no-clobber receipt replacement,
governance-context merging, exact turn/source identity, subagent exclusion,
unknown counters/Fast, escaped names, private output, symlink refusal, unchanged
timing state and immutable pre-final fragments. The trusted archive bundles its
HTML template; the loader exposes only its digest for the preview command path.

One actual installed Codex CLI turn, prompted only to acknowledge completion,
finished in 14.78 seconds. It emitted one `command_execution`, one final inline
visualize reference to an existing fragment, one `turn.completed`, and one Stop
receipt. There was no report-driven continuation or hook failure. The two
`agent_message` items were normal progress/final output, not two completed turns.
The unrelated existing chronicle unstable-feature warning remained. Total test
usage was 46,150 input (6,528 cached) and 409 output tokens; this includes all native
startup context and is **not** a measurement of incremental report cost. Rendering
itself makes zero model calls, but the normal preview tool round trip uses tokens
and can add inference compared with an otherwise tool-free answer.

The current desktop Task also produced a real named preview from its existing
start baseline. In a local browser rendering of the official visualize wrapper,
736px/320px and light/dark layouts had no horizontal overflow; expanding details
increased the measured height in all four cases. The light desktop screenshot was
visually read back. This validates fragment layout, not a claimed desktop paint
before the final answer is sent; the final response supplies the actual reference.

Isolated cachebuster installation and stable v0.13.0 installation succeeded.
Installed source and retained v0.3.0–v0.12.1 caches matched their identities.
Saved report preferences were unchanged. Config changes were the 11 reviewed
plugin hook trust hashes plus the CLI-created trust entry for the isolated test
workspace; no model, budget, Railway hook or recurring-observation setting changed.
All plugin hooks and the unrelated Railway hook read back enabled/trusted.
Runtime SHA-256: `db5cc2a7930e94be9c8a66c44e58fc4de5e90b23fe279855a4cf7263a22ef24a`.

A follow-up cost-wording correction correctly triggered same-version cache
replacement protection. The updater retained/restored the original v0.13.0
cache and quarantined the substituted copy. The official cachebuster helper
then installed `0.13.0+codex.20260912202926` without replacing the old version.
The final source/cache identity and settings were rechecked. Its archive differs
from the model-tested archive only in `__init__.py` version metadata, with final
SHA-256 `be587f6ed1867d51ae3c375e4f385bb5e5734eedd12380ed2cf69e53f298c928`.

Automatic inline presentation requires the supported visualize surface and model
compliance with the short instruction. Exact-format/off requests take precedence;
failure skips without retry. It is not a deterministic native UI injection, and
does not rewrite old answers or live-refresh a snapshot after Stop. New Tasks are
the supported pickup boundary for the updated pinned hook runtime.

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
