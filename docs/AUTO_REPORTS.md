# Automatic Task and subagent turn receipts

The user-switchable `auto-report` feature is deterministic Python, not a model task.
From v0.10.1, the default is enabled when no settings file exists. An explicit
`enabled: false` remains off after upgrades. Reading defaults never writes a
settings file or overwrites a user's choice. `auto-report enable` selects threshold 0:
every eligible parent Stop or subagent SubagentStop can generate one own-turn
receipt, even immediately after its start. Timing remains useful metadata but
is not a generation gate.

## Lifecycle and presentation

For a parent Task, `UserPromptSubmit` records a hashed Task/turn key and a bounded
token-counter baseline. For a subagent, `SubagentStart` uses that child's native
`agent_id` and active `turn_id` for its own key, while the shared `session_id`
remains the governance run key. The parent path checks its exact Task identity;
the child path also verifies its native root and direct parent. Similar names
or timestamps never establish ownership. The start creates a pending Markdown
file and returns one short `additionalContext` instruction to run one
deterministic pre-final preview tool
and put its native `visualize` reference at the end of the normal final answer.
The child's instruction identifies its own Task and tells the child to skip an
inherited parent preview instruction. The model is told
not to read/analyze the report, invent numbers, or add another turn. The tool
reads this exact Task and timing key, reconciles bounded descendant
usage records in this turn's observation window, and renders a bundled HTML
fragment into a task-owned writable visualization directory selected by the caller.
Prefer a visualization root explicitly supplied in writable roots; otherwise
use `work/` inside the Task's native working directory. The preview validates
that destination against the native Task's working directory or its own
`CODEX_HOME/visualizations/YYYY/MM/DD/<Task>/` root (UUIDv7 UTC date). After
verified native lineage, a child may also write under its root Task's native
visualization root when that is the supplied writable directory. Write access,
including full access, does not itself authorize the desktop to read a file.
Private state directories, unrelated Tasks' visualization roots, traversal and
symlinks are rejected before quota/child collection; no invalid reference is
returned and no retry or fallback write is attempted. Extra sandbox roots are
not accepted because this tool cannot verify the desktop's effective read policy.
The check is repeated before writing. Existing snapshots and saved assistant
messages are not rewritten; a previously broken reference needs a replacement
reference to the same snapshot in an accepted, writable location.
Its output is only status/reference, not the report body. The numeric card is a
pre-final snapshot, excluding subsequent work; it is not overwritten by Stop.
The bounded snapshot also accepts the native `thread_token_usage` counter in a
`token_usage_record`, which may be written before the post-tool `token_count`
event. It validates explicit Task/turn attribution, response identity, and
consistent request/turn/thread totals, then selects the newest cumulative
observation. It never adds the request amount to an event counter or treats a
request-only amount as a thread total. Missing or incompatible native fields
remain unavailable; the rollout schema is not a stable public contract.
If a verified fresh first turn has not persisted its first usage counter yet,
the card says it is awaiting the usage write. It does not display zero or request
another tool call. Stop independently settles whatever counters are then available.
On later turns, merely re-reading the same pre-start counter also remains pending,
not an observed zero. The Task total can still show the last saved Task counter.
Disabling reports or an incompatible
exact-output request takes precedence. The same persistent switch controls both
generation and this presentation instruction; an explicit off is not overridden.

From v0.13.3, a missing prompt-hook start can be recovered by the first eligible
`PreToolUse` or `PostToolUse`. The same Governor interface checks budget decisions
first, then atomically creates at most one timing row and one event-correct
context instruction. Existing rows (including terminal states) do not trigger
another transcript read, locale lookup, or instruction. Reporting never changes
tool permission, input or output, or requests a Stop continuation.

Parent tool-hook recovery requires the exact parent Task and active turn's
native `task_started`
record, with a valid timezone-aware timestamp, within the existing 8 MiB scan.
The baseline is reconstructed at that record, not from the first tool's already
spent tokens. Earlier counters or verified fresh-first-turn evidence may establish
the baseline; an explicit native turn counter can still supply usage without it.
Missing counters stay unknown. Timing and child coverage use the recovered native
start, and the private Stop receipt records `start_event` and `start_recovered`.
Malformed, foreign, completed, future, before-current-boot or out-of-scan starts
are not recovered. The report switch is rechecked. Subagent starts use their
own `SubagentStart` hook; an absent child start is not inferred from an unrelated
parent or tool event.

This uses the documented
[PreToolUse](https://learn.chatgpt.com/docs/hooks#pretooluse) and
[PostToolUse](https://learn.chatgpt.com/docs/hooks#posttooluse) context outputs.
It covers an omitted prompt hook when a supported tool hook does run; it does
not establish why any particular scheduler omitted a hook. A turn with neither
a prompt start nor an eligible tool event cannot be guaranteed a card. Missing
or disabled hooks, unavailable runtime and model noncompliance remain host limits.

The parent's `Stop` or child's `SubagentStop` claims its own key before
generating private Markdown, HTML and JSON files under the budget data
directory's `auto-reports/`. Files are mode
0600 and use opaque names; no prompt, transcript text or raw transcript path is
persisted. A child's `Stop`, when delivered, can settle the same child key
idempotently. The settling hook may return only an informational `systemMessage`.
Existing budget decisions, context and enforcement fields are preserved.
HTML and JSON are written exclusively before atomically replacing only this
turn's exact pending Markdown. Stop publication does not overwrite completed or
user-edited files.
The optional Markdown fallback exists before the answer and explicitly says
pending. Interrupted, disabled, short or failed turns may leave it pending.

From v0.11, the receipt heading uses an exact, bounded read of Codex's native
Task `name` when available. It never reads the prompt-like `title`, preview or
first-message fields and never calls a model to invent a name. The catalog read
is read-only, has a 0.8-second query deadline and at most 12 parent hops; missing
or changed schemas retain the unnamed fallback. Display metadata is stored only
in private report artifacts, not the timing baseline or governance ledger. Names
may be sensitive and are current-at-report-time, not historical names.

This follows the [official Stop interface](https://learn.chatgpt.com/docs/hooks#stop)
and [common output contract](https://learn.chatgpt.com/docs/hooks#common-output-fields).
Codex decides how it displays that UI message and whether it linkifies the path.
No supported hook output was found for rewriting the assistant's final answer
or automatically opening an artifact. `systemMessage` alone was insufficient:
the v0.12.1 desktop answer omitted the link despite a real completed receipt.
The v0.13 bridge uses the documented
[UserPromptSubmit context interface](https://learn.chatgpt.com/docs/hooks#userpromptsubmit)
to request an inline card in the normal answer, not a Stop continuation or transcript
edit. Its instruction, one tool call/result and output reference have a token cost;
model compliance is not a deterministic native-footer guarantee. The visualize
surface must be available; no renderer, model or network is needed by the fixed
template itself. CLI validation can prove reference emission but not desktop paint.
The installed desktop renderer reads inline HTML into a cached snapshot rather
than watching its source file. Updating that file at Stop does not automatically
refresh an already displayed card, so this plugin does not promise a live final
receipt inside the pre-final card or modify the App to force one.
Markdown is the native-file-viewer entry
point; HTML is an offline static alternative, not a promised automatic preview.

A Stop or SubagentStop is a turn boundary, not semantic completion of a
long-running Task.
Another hook can continue the turn after the first receipt. `stop_hook_active`
is recorded, not used to generate another receipt. Interrupted/session-ended
turns, denied user prompts, and settling hooks without a recorded start
do not generate full turn reports. Child numeric capture is separate. Duplicate
deliveries cannot overwrite report files. A crash
after claiming leaves an incomplete attempt without automatic retries; partial
files are retained, and only fully written outputs are announced.

## Completion revision (parent v0.14; subagent v0.19.3)

After the normal Governor dispatch and an eligible reported parent or child
settlement, the hook adapter may launch one detached report-only child. The
worker never enters Governor,
changes a budget ledger/admission decision, invokes a model, refreshes quota or
requests a continuation. It performs at most eight bounded snapshot reads with
a 25-second process deadline, checks the report switch again before publishing,
and exits. A disabled switch, absent receipt, repeated Stop or failed launch does
not start another worker. No recurring monitor or scheduler is installed.

A matching native `task_complete` record is required. File quietness is not
completion evidence. The reader also requires matching Task/turn context or a
start inside the bounded prefix, rejects foreign or ambiguous ordering, and
truncates evidence at that completion record before interpreting counters and
model/effort observations. Subsequent turns cannot supply usage or settings.
The native format is observational and can change; unavailable completion,
missing counters, reset counters and bounded evidence remain provisional/partial.
This is completion of the selected turn, not proof the whole Task is done.

The completion revision keeps the original start-to-settlement elapsed time
and child window; it may include child numeric records persisted late for that
same window.
Quota remains the original timestamped pre-final account observation. The original
JSON/HTML/Markdown remain immutable. Separate `.reconciled.json`, `.reconciled.html`
and `.reconciled.md` files carry revision 2, check status and update time. No
original report path is overwritten; edits and symlinks remain untouched. The
timing index points to the new Markdown revision after successful publication.

Inline HTML is not overwritten. A mobile A/B experiment confirmed that a new
reference read the updated source but the original card retained A after the
source became B. Reentering the Task is not a reliable refresh API. Open the latest
report from `auto-report list`; neither the old card nor sent answer is promised
automatic in-place refresh. Hashed job state contains only its key, status,
attempt count and update time. Native selectors travel through the child's stdin
and are not persisted in job state or command-line arguments.

## Evidence and cost

### Report language

The inline card, pending page, Stop/SubagentStop Markdown/HTML and report messages share
bundled language catalogs. They prefer Codex's observed `[desktop].localeOverride`
in `CODEX_HOME/config.toml`, not the language of prompts or model output. No
Codex preference is changed. Every new output resolves language again; already
written snapshots are immutable. The pending file's original locale is recorded
so changing App language during a turn does not bypass no-clobber checks or
prevent legitimate settlement. Older receipts without locale metadata retain
their original Traditional Chinese interpretation.

Nine language catalogs are included: `en`, `zh-Hant`, `zh-Hans`, `ja`, `ko`, `de`,
`fr`, `es`, `pt`. Regional variants map to these language catalogs; Chinese
script tags take priority, with TW/HK/MO mapped to Traditional and CN/SG to
Simplified. Spanish and Portuguese regional variants share one catalog each
(Portuguese copy uses Brazilian usage). Unknown/unsupported choices use English,
not runtime model translation. This is not coverage of every Codex UI language.
Task names, agent nicknames, model identifiers, reasoning identifiers, ISO
timestamps and JSON status codes are retained; labels, durations and number
separators are localized. No accounting values or budget decisions change.

The desktop key was verified in the installed Codex App's settings adapter.
The App itself obtains `ideLocale`/`systemLocale` from Electron, and may select
between them under runtime flags; hooks do not provide that effective UI locale.
For Auto/missing settings, macOS reads only the App's `AppleLanguages` preference,
then the global `AppleLanguages` preference, ignoring terminal `C.UTF-8`.
Windows uses the user UI language; other systems use locale environment signals.
These fallbacks are host observations, not proof of a remote client's UI language
or exact parity with every Electron runtime flag. Manually selecting a supported
language in Codex is the strongest source. Private setting schemas may change.

Config reads are regular-file/no-follow and bounded to 256 KiB; raw settings are
never persisted or returned. Python 3.11+ uses `tomllib`. The dependency-free
Python 3.10 adapter accepts the ordinary `[desktop]` scalar or root dotted-key
form, skips quoted/multiline instruction text and conservatively declines
unsupported locale expressions. macOS preference reads each time out after 0.25
seconds. Failures use English or an available host-language fallback; they never
continue the model or weaken budget enforcement. Catalogs are shipped inside
the pinned runtime and need no network or additional model requests.

### Subagent's own receipt and parent reconciliation

The existing `SubagentStart` hook, when trusted, can establish the subagent's own
timing and preview context. `SubagentStop` settles that child's own private
receipt when its start and identity are verified. It also saves available
allowlisted usage evidence to a separate private child store, even without an
active governed budget. The child does not have to self-report, and the hooks
do not start a model request or request a continuation. The same report switch
controls both paths. The existing budget governor handles shared-budget
accounting independently; a child's report identity is not another budget.

`SubagentStart` receives the parent-shared `session_id`, the child's `agent_id`
and active `turn_id`, and the child's transcript path. The report uses the
child's native identity for its own card and validates its root and direct
parent against catalog and transcript metadata. `SubagentStop` uses the child
transcript supplied as `agent_transcript_path`; a child's `Stop`, if the host
delivers one, cannot publish a second receipt. The inline card is the child's
pre-final snapshot. The later child receipt and bounded completion revision
remain separate, immutable observations. Missing start, mismatched lineage,
absent counters, and scan limits cannot be silently filled from the parent.
Copied parent metadata or history in a child transcript is not the child's own
usage; the child report counts only evidence after its own start. If no native
child counter is established, usage stays unknown.

The timing baseline stores only hashes of the child's original root and direct
parent. Preview, Stop and completion reconciliation preserve the original report
role and require that original root
proof; an older child baseline without it stays unverified. A current catalog
lookup cannot fill in the missing historical root. Conflicting parent metadata
for the same child also invalidates saved request evidence, so a cached subtotal
cannot reappear after its source becomes unavailable. Metadata for different
Tasks in ordinary copied-parent history remains valid.

The parent's pre-final preview and Stop receipt select only descendants linked
by native parent metadata. They combine saved child evidence with a bounded fresh
read, select native `token_usage_record` timestamps in `[parent start, capture)`,
and deduplicate response identities. Explicit child thread/turn attribution is
required: a forked child transcript can also contain copied parent metadata and
history, so child lifetime counters and inherited records are not added.
The same short hashed `@selector` appears beside a child on its own card and
in an ancestor's child row, so the two views can be matched without persisting
a raw Task ID. The selector is a display aid; native parent metadata still
establishes ownership.
Child cards and receipts name their direct parent and label their own usage
separately from descendant subtotals; the root Task keeps its existing labels.

This is observation-window attribution, not proof the parent caused every request
in that interval. Reused children contribute only records in this window. Names
and parent labels come from current native metadata in the private report, never
from prompts or the numeric child store. Unrelated Task transcripts are not read.
The missing/pending denominator uses this same window: verified old children whose
native lifecycle ended before it, and children created after it, are excluded.
Active cross-window children, reused children and unknown or conflicting lifecycle
evidence remain in scope. File modification time is not treated as a Stop event.
Bounded selection or scan limits still prevent a complete-coverage claim.

The official [SubagentStart](https://learn.chatgpt.com/docs/hooks#subagentstart)
context reaches the child, while the
[SubagentStop contract](https://learn.chatgpt.com/docs/hooks#subagentstop)
permits a missing transcript path and a continuation decision. Capture can precede
final persistence; the one pre-final reread reconciles records that arrived later.
It cannot force native counters to flush or guarantee every child's final tokens.
Missing sources, limited scans, pending agents and conflicts remain visible as
partial/unknown. The completion revision adds only its bounded report-only check;
no agent interruption or model retry turn is added. A completed child does not need to remain running to be counted.

### Current-turn settings and layout

Each inline card keeps its own Task total and current turn's token increase visible.
Observed parent/child coverage, account quota, current-turn settings and token
details are four independent native `details` disclosures, closed by default.
Their summaries reuse the report locale; opening and closing require no scripts,
network requests or model calls. When exactly one native main-Codex 7-day window
is present, the closed quota summary also shows its remaining percentage and
previous-card movement/status. Other quota buckets are never substituted, and
resets or unavailable readings keep their existing labels. No weekly window is
inferred from the subscription plan. Stop/SubagentStop Markdown/HTML remains expanded for offline
reading. Existing immutable cards retain their original layout.

The bordered inline card pairs the selected Task's native total with this
turn's added tokens. Both primary values exclude descendants; the separately
labeled observed turn subtotal adds only descendant request evidence in the
current window. A subagent's own card and an ancestor's descendant subtotal
can show overlapping requests; do not add them together. Elapsed time is
secondary header metadata. Nine locales share the same responsive layout,
with stacked metrics on narrow screens.

Model and reasoning effort are displayed as chronological pairs from this turn,
not independent lists or the Task's initial settings. Adjacent identical pairs
collapse; returning to a previous pair remains visible. The bounded reader uses
`turn_context`, native `thread_settings_applied` events, and explicitly attributed
request settings when supplied. It also recognizes persisted reasoning-only
`configuration_update` items; these are not model-change events. The API documents
[reasoning changes within a conversation](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation),
but this is not a guarantee that every Codex client persists every change.

Missing settings never fall back to the first Task model or global preferences.
Conflicting aliases, reversed timestamps and bounded/incomplete records remain
unknown or partial. At most 16 observed pairs are retained; this is not a complete
request-by-request model allocation or proof that an unrecorded change did not
happen. Fast is omitted from automatic human-facing reports; manual sensing and
machine-readable compatibility fields are unchanged.

### Counter interpretation

From v0.14.1, native request/thread counters (`native_request`) and legacy
`token_count` event counters are separate evidence sources. They can represent
different historical baselines in the same native file. For example, a synthetic
legacy total of 12,000 followed by a valid native thread total of 9,000 and a
native turn total of 500 is not by itself a reset. The selected turn may report
500 directly from its native turn counter. It must not subtract 12,000 from
9,000, add both totals, or treat a later legacy event as a replacement native
baseline.

A matching native request/thread counter takes priority; event counters remain
fallback evidence. Reset detection compares observations within the selected source;
a decrease there or an invalid native turn counter still makes the result
unknown. Native turn decreases are also rejected across bounded snapshots, even
when the older native record has fallen outside the tail and the thread total rises.
Boundary subtraction across different `counter_source` values returns
`counter_source_changed`, unless an independently validated native turn counter
supplies the exact turn amount. Missing, malformed or incomplete evidence retains
its existing partial/unknown rules. Preview, Stop and completion revision evidence
record the selected `counter_source`; this affects reporting, not the Governor's
budget ledger or policy decisions.

- Parent turn usage prefers validated native `turn_token_usage` paired with the
  newest matching `thread_token_usage`. This matters when a long Task's current
  rollout segment begins with existing Task history: the Task counter is not a
  zero-based turn counter. Otherwise it uses the difference of cumulative counters
  at the two observed boundaries, not an aggregation of individual requests.
  A fresh original first
  turn may use its first cumulative counter only when the complete bounded
  prefix proves the matching start without inherited history or earlier model
  work, and the ending prefix has no other turn or observed counter reset.
  Forked, malformed, incomplete or tail-limited evidence cannot establish that
  exception. Other missing baselines,
  changed/truncated sources, observed resets (even if the counter rises again),
  negative deltas and inconsistent subsets stay
  unknown. A brand-new Task often has no persisted counter at preview time. Child usage instead
  uses deduplicated request records, not cumulative differences; missing request
  evidence is unknown. The card separates parent, child and known subtotal, and
  labels incomplete coverage rather than treating it as a complete total.
- Stop may precede final token persistence. Even a zero delta does not mean
  the work was free. A reset between boundaries may be unobservable.
- Input includes cached input; output includes reasoning. Subsets are not added
  again. Model/reasoning pairs are exact-turn observations, not token allocation.
- Token reconciliation reads only the current Task and bounded exact descendants.
  No unrelated cross-Task history scan, pricing lookup, model request or
  continuation is performed by receipt generation. The pre-final quota read is
  separate, described below. Only the short start-time
  preview instruction and compact command result enter model context; the report
  body does not. The preview adds bounded exact-Task-tree reads, not a history scan.
  Use the manual
  `report` or `meter` commands for richer, separately requested analysis.
- Each start/Stop reads at most a 128 KiB header and an 8 MiB tail. At most 16
  exact-turn setting observations are retained. SQLite initialization and start
  writes share a two-second wait deadline; the synchronous hook timeout remains
  three seconds. This bounds
  work but cannot guarantee success on an overloaded disk or host.
- Child reconciliation selects at most 32 descendants, reading at most a 128 KiB
  header and 1 MiB tail for each. The numeric store has a 0.25-second SQLite wait,
  at most 512 agent entries and 50,000 request entries; capacity refuses new
  entries without deleting retained evidence. Limits/missing evidence remain
  partial or unknown. This extra bounded work has CPU/disk cost, not model cost.
- The timing index accepts up to 10,000 turns. At capacity or on another error,
  it emits an informational failure rather than changing budget enforcement or
  requesting model retries. No automatic deletion is performed. Disabling
  retains the index and generated files.
- `model_requests_for_report: 0` means no extra model calls for generation, not
  zero CPU/disk cost, zero tokens for the preview call/reference, or free later analysis.

### Account quota beside token usage

The existing single preview command also captures native account rate limits
and account plan. It calls only `account/rateLimits/read` (without reset-credit
details) and non-refreshing `account/read`, after initialization. It does not
query account token history, thread billing, prices or credentials. The RPC
conversation has a two-second deadline plus bounded process cleanup; failure
leaves quota unknown without suppressing the token card. This adds a network
read and local processing, not another model tool turn. No quota call happens
in start/Stop hooks. Stop includes the saved pre-final quota snapshot with its
own capture time; it is not a fresh Stop-time account reading.

The parent or subagent card displays `100 - usedPercent`, clamped to 0–100, and
the difference in **remaining percentage points** from this same Task's
immediately preceding turn's
card. Negative differences mean the displayed allowance fell; they are not the
percentage of this Task's own usage. Account-wide usage includes the parent,
subagents, concurrent Tasks, other devices/features and reporting delay. A child
card does not allocate any part of this quota to that child. A displayed zero
difference
means unchanged at the source's reported precision, not free work, a precise
less-than-one-percent bound, or a token-to-percent conversion. Supplied fractional
percentages are preserved; no fractional spend is inferred from token counts.

Windows are named by native `windowDurationMins`, never by a fixed Plus/Pro
mapping or `primary = 5h` assumption. Main Codex and additional buckets remain
distinct. The native reported ChatGPT plan is displayed only when unambiguous;
Pro does not establish a detected 5x/20x tier. The
[official rate-limit schema](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)
defines duration, reset timestamp and used percentage. The
[plan guide](https://learn.chatgpt.com/docs/pricing#what-are-the-usage-limits-for-my-plan)
uses five-hour estimates for both Plus and Pro and directs users to actual
account limits; those estimates do not override the native observation.

A changed account, plan, bucket alias, window duration/reset timestamp, crossed
reset deadline, missing identity or unordered capture prevents subtraction.
If `account/read` is unavailable, comparison may still use matching account
identity and valid plan evidence from the quota response itself; the displayed
account plan remains unknown. Missing or conflicting quota plan evidence does
not permit that fallback.
An increased remainder without an observed reset is labeled correction/recovery,
not negative consumption. The new observation becomes the next baseline.
Unavailable/interrupted previous turns are not skipped to compare with an older
successful turn. A reset followed by consumption that exceeds the old used
percentage may still be unobservable if the backend leaves the same window
identity; therefore this is an observation difference, not billing-grade spend.

`auto-reports/quota.sqlite3` is private, separate from the budget ledger and the
manual meter. It stores allowlisted numbers, known plan enums and hashed account,
bucket and turn identities, never names, emails, prompts or response text.
Only up to eight quota buckets and 32 KiB per capture are retained, at most
10,000 turn rows. A persisted claim precedes the RPC, so duplicate/concurrent
previews and crashed captures do not retry it. The immediate previous turn is
looked up in the existing timing index, not across Task history. The same report
switch suppresses preview/capture when off; no background schedule is installed.

## Controls

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report enable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report status
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report list
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report disable
```

`--data-dir PATH` before the subcommand selects isolated storage. Settings live
in `auto-report.json`, separate from governance state. Configuration changes do
not start a budget, change native subscriptions or alter models. An optional
`--threshold-seconds 300` on `enable` selects strictly-over-five-minute receipts;
it is unnecessary for saving model-generation cost and is not the default.

The switch is checked at each relevant hook, so turning it off also suppresses
a pending parent or subagent receipt. Turning it on does not backfill completed
turns. An active parent turn can recover its native start at its next eligible
tool event; future turns otherwise establish their own baselines. Recovery never
changes the switch.
Users may ask Codex to turn automatic per-turn reports on/off; the skill runs
these same commands and reads back `status`. Such a conversational configuration
request uses a normal model turn; subsequent report generation itself does not.
This is a local configuration switch, not an added native app Settings widget.
Official plugin guidance routes
[Codex-local preferences to config files](https://developers.openai.com/plugins/guides/submit-claude-plugin#replace-claude-userconfig).

Run Budget already defines `SubagentStart` and `SubagentStop` hooks. A compatible
publisher-signed runtime update that leaves their hook definitions unchanged
preserves existing native trust; it does not grant a new hook permission.
New Tasks pick up the new pinned runtime, while existing Tasks retain their
previously loaded code. If a package update changes a hook definition, review
and trust that change through `/hooks` before starting a new Task.
