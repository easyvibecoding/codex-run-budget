# Automatic user-turn receipts

The user-switchable `auto-report` feature is deterministic Python, not a model task.
From v0.10.1, the default is enabled when no settings file exists. An explicit
`enabled: false` remains off after upgrades. Reading defaults never writes a
settings file or overwrites a user's choice. `auto-report enable` selects threshold 0:
every eligible main-user-turn Stop can generate one receipt, even immediately
after its start. Timing remains useful metadata but is not a generation gate.

## Lifecycle and presentation

`UserPromptSubmit` records a hashed session/turn key and a bounded token-counter
baseline. `Stop` claims that key before generating private Markdown, HTML and
JSON files under the budget data directory's `auto-reports/`. Files are mode
0600 and use opaque names; no prompt, transcript text or raw transcript path is
persisted. The Stop output contains only an informational `systemMessage`.
Existing budget decisions and enforcement fields are preserved.

This follows the [official Stop interface](https://learn.chatgpt.com/docs/hooks#stop)
and [common output contract](https://learn.chatgpt.com/docs/hooks#common-output-fields).
Codex decides how it displays that UI message and whether it linkifies the path.
No supported hook output was found for rewriting the assistant's final answer
or automatically opening an artifact. Markdown is the native-file-viewer entry
point; HTML is an offline static alternative, not a promised automatic preview.

A Stop is a user-turn boundary, not semantic completion of a long-running Task.
Another hook can continue the turn after the first receipt. `stop_hook_active`
is recorded, not used to generate another receipt. Interrupted/session-ended
turns, denied user prompts, subagent hooks, and Stops without a recorded start
do not generate receipts. Duplicate deliveries cannot overwrite files. A crash
after claiming leaves an incomplete attempt without automatic retries; partial
files are retained, and only fully written outputs are announced.

## Evidence and cost

- Numeric usage is the difference of cumulative counters at the two observed
  boundaries, not an aggregation of individual requests. Missing baselines,
  changed/truncated sources, negative deltas and inconsistent subsets stay
  unknown. A brand-new Task often has no starting counter.
- Stop may precede final token persistence. Even a zero delta does not mean
  the work was free. A reset between boundaries may be unobservable.
- Input includes cached input; output includes reasoning. Subsets are not added
  again. Model/Fast/reasoning values are exact-turn tail observations, not token
  allocation. Absent/ambiguous Fast remains unknown, never inferred from the
  current global preference or model name.
- Only the current Task transcript is read. No descendant/cross-Task scan,
  native quota query, pricing lookup, network request, model request, context
  injection or continuation is performed by receipt generation. Use the manual
  `report` or `meter` commands for richer, separately requested analysis.
- Each start/Stop reads at most a 128 KiB header and an 8 MiB tail. At most 16
  exact-turn setting observations are retained. SQLite's write wait is 0.4
  seconds; the existing synchronous hook timeout remains 3 seconds. This bounds
  work but cannot guarantee success on an overloaded disk or host.
- The timing index accepts up to 10,000 turns. At capacity or on another error,
  it emits an informational failure rather than changing budget enforcement or
  requesting model retries. No automatic deletion is performed. Disabling
  retains the index and generated files.
- `model_requests_for_report: 0` means no extra model calls for generation, not
  zero CPU/disk cost or a promise that later model analysis costs no tokens.

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
