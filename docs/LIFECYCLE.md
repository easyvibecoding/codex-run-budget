# Turn lifecycle evidence

Recent task histories contain interrupted turns followed by new turns,
multi-page replays, and context compaction. Raw start/stop counts cannot tell
these cases apart. This extension adds a read-only lifecycle view to the
existing bounded audit; it does not add enforcement or task orchestration.

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py survey --days 2 --lifecycle
python3 plugins/codex-run-budget/scripts/run_budget.py survey --days 2 --json
```

The normal summary includes lifecycle totals. `--lifecycle` shows up to 20
hashed rows: conflicting/missing endings first, then aborted turns, then
completed turns, with compaction count and recency as secondary ordering.
This is an evidence shortlist, not an alarm or cost ranking. JSON contains
all observed rows under `audit.lifecycle`; exact-file `audit` has the same
`lifecycle` field. Existing audit v2 fields remain available.

## Meaning of the evidence

| Field or state | Established fact | Not established |
| --- | --- | --- |
| `completed` | A matching native `task_complete` was observed | The user's requested outcome passed independent verification |
| `aborted` | A matching native `turn_aborted` was observed | A crash, model defect, or abandoned task |
| `no_terminal_observed` | The selected snapshot has no matching ending | The task is currently running, stuck, or safe to kill |
| `conflicted` | Lifecycle evidence is contradictory | Which terminal event should be trusted |
| `later_turn_observed` | Another turn subsequently started in the same thread | Same-work continuation, repair, or successful recovery |
| `compactions` | Observed compaction events after deduplication | Lost work, wasted tokens, or permission to skip rereading |

Codex's documented [app-server lifecycle](https://learn.chatgpt.com/docs/app-server#lifecycle-overview)
emits `turn/completed` after normal finish or interruption. The final status
matters; an event named "completed" is not by itself a success signal.
The local transcript adapter recognizes native `task_started`, `task_complete`,
and `turn_aborted`; it never treats a wait result or an assistant's final text
as a terminal lifecycle event.

Rows are keyed by actual thread and turn identity, not the parent-shared
`session_id`. Identifiers are hashed before aggregation. The parser keeps no
prompt, final message, compaction summary, history, raw reason, or tool content.
The same bounded reader and its file/record limits apply; no extra scan or
SQLite access is performed.

Start records before the selected window can supply context and are marked
`started_before_window`. Missing start records remain explicitly missing.
Records after the upper bound cannot supply a terminal state or later-turn
claim. A snapshot is not a live task-status source.

`duration_ms` uses a valid native duration when available, otherwise a usable
start/end event span; `duration_source` distinguishes the two. Missing or
conflicting timing remains unknown. These are wall-clock observations, not
CPU measurements, billable usage, or token savings. Compaction counts without
a valid thread/turn association stay in `unattributed_compactions`.

## Design and verification

`audit.py` remains the only file reader and raw-record adapter. A pure
`lifecycle.py` reducer owns deduplication, lifecycle interpretation, window
rules, and later-turn linkage. The CLI and tests cross the same audit interface.
Governance, hook admission, and the ledger are unchanged.

Regression coverage exercises real transcript shapes, page-order independence,
replay deduplication, separate parent/child identities, window clipping,
missing/invalid identifiers, contradictory endings, compaction attribution,
privacy, and bounded CLI output. Live evidence is recorded in
[VALIDATION.md](VALIDATION.md).
