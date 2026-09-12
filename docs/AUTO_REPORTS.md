# Automatic user-turn receipts

The user-switchable `auto-report` feature is deterministic Python, not a model task.
From v0.10.1, the default is enabled when no settings file exists. An explicit
`enabled: false` remains off after upgrades. Reading defaults never writes a
settings file or overwrites a user's choice. `auto-report enable` selects threshold 0:
every eligible main-user-turn Stop can generate one receipt, even immediately
after its start. Timing remains useful metadata but is not a generation gate.

## Lifecycle and presentation

`UserPromptSubmit` records a hashed session/turn key and a bounded token-counter
baseline. From v0.13 it also creates a pending Markdown file and returns one short
`additionalContext` instruction to run one deterministic pre-final preview tool
and put its native `visualize` reference at the end of the normal final answer.
The model is told not to read/analyze the report, invent numbers, or add another
turn. The tool reads this exact Task and timing key, reconciles bounded descendant
usage records in this turn's observation window, and renders a bundled HTML
fragment into a task-owned writable visualization directory selected by the caller.
Its output is only status/reference, not the report body. The numeric card is a
pre-final snapshot, excluding subsequent work; it is not overwritten by Stop.
Disabling reports or an incompatible
exact-output request takes precedence. The same persistent switch controls both
generation and this presentation instruction; an explicit off is not overridden.

`Stop` claims that key before generating private Markdown, HTML and
JSON files under the budget data directory's `auto-reports/`. Files are mode
0600 and use opaque names; no prompt, transcript text or raw transcript path is
persisted. The Stop output contains only an informational `systemMessage`.
Existing budget decisions, context and enforcement fields are preserved.
HTML and JSON are written exclusively before atomically replacing only this
turn's exact pending Markdown. Completed or user-edited files are not overwritten.
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
Markdown is the native-file-viewer entry
point; HTML is an offline static alternative, not a promised automatic preview.

A Stop is a user-turn boundary, not semantic completion of a long-running Task.
Another hook can continue the turn after the first receipt. `stop_hook_active`
is recorded, not used to generate another receipt. Interrupted/session-ended
turns, denied user prompts, subagent hooks, and Stops without a recorded start
do not generate full turn reports. Child numeric capture is separate. Duplicate
deliveries cannot overwrite report files. A crash
after claiming leaves an incomplete attempt without automatic retries; partial
files are retained, and only fully written outputs are announced.

## Evidence and cost

### Deterministic child receipts and pre-final reconciliation

`SubagentStop` now saves available allowlisted usage evidence to a separate private
child store, even without an active governed budget. It never adds a child footer,
asks the child to self-report, returns a continuation decision, or starts a model
request. The same report switch controls this capture. The existing budget
governor still handles its own shared-budget accounting independently.

The parent's pre-final preview and Stop receipt select only descendants linked
by native parent metadata. They combine saved child evidence with a bounded fresh
read, select native `token_usage_record` timestamps in `[parent start, capture)`,
and deduplicate response identities. Explicit child thread/turn attribution is
required: a forked child transcript can also contain copied parent metadata and
history, so child lifetime counters and inherited records are not added.

This is observation-window attribution, not proof the parent caused every request
in that interval. Reused children contribute only records in this window. Names
and parent labels come from current native metadata in the private report, never
from prompts or the numeric child store. Unrelated Task transcripts are not read.

The official [SubagentStop contract](https://learn.chatgpt.com/docs/hooks#subagentstop)
permits a missing transcript path and a continuation decision. Capture can precede
final persistence; the one pre-final reread reconciles records that arrived later.
It cannot force native counters to flush or guarantee every child's final tokens.
Missing sources, limited scans, pending agents and conflicts remain visible as
partial/unknown. No background polling, blocking wait, agent interruption or retry
turn is added. A completed child does not need to remain running to be counted.

### Counter interpretation

- Parent usage is the difference of cumulative counters at the two observed
  boundaries, not an aggregation of individual requests. Missing baselines,
  changed/truncated sources, negative deltas and inconsistent subsets stay
  unknown. A brand-new Task often has no starting counter. Child usage instead
  uses deduplicated request records, not cumulative differences; missing request
  evidence is unknown. The card separates parent, child and known subtotal, and
  labels incomplete coverage rather than treating it as a complete total.
- Stop may precede final token persistence. Even a zero delta does not mean
  the work was free. A reset between boundaries may be unobservable.
- Input includes cached input; output includes reasoning. Subsets are not added
  again. Model/Fast/reasoning values are exact-turn tail observations, not token
  allocation. Absent/ambiguous Fast remains unknown, never inferred from the
  current global preference or model name.
- Only the current Task and bounded exact descendants are read. No unrelated
  cross-Task history scan, native quota query, pricing lookup, network request, model request or
  continuation is performed by receipt generation. Only the short start-time
  preview instruction and compact command result enter model context; the report
  body does not. The preview adds bounded exact-Task-tree reads, not a history scan.
  Use the manual
  `report` or `meter` commands for richer, separately requested analysis.
- Each start/Stop reads at most a 128 KiB header and an 8 MiB tail. At most 16
  exact-turn setting observations are retained. SQLite's write wait is 0.4
  seconds; the existing synchronous hook timeout remains 3 seconds. This bounds
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
a pending Stop receipt. Turning it on cannot recreate a start that happened
while reporting was off; future user turns establish their own baselines.
Users may ask Codex to turn automatic per-turn reports on/off; the skill runs
these same commands and reads back `status`. Such a conversational configuration
request uses a normal model turn; subsequent report generation itself does not.
This is a local configuration switch, not an added native app Settings widget.
Official plugin guidance routes
[Codex-local preferences to config files](https://developers.openai.com/plugins/guides/submit-claude-plugin#replace-claude-userconfig).

After an upgrade, review/trust changed hooks and use a new Task to pick up the
new pinned runtime. Existing Tasks retain their previously loaded hook code.
