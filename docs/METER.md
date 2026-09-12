# Native Codex quota meter

`meter` reads the signed-in Codex app-server. It does not make a model request,
consume a reset credit, change a budget, or poll in the background. Unlike the
offline survey, a snapshot uses the account connection and saves normalized
observations locally unless `--no-save` is supplied.

```sh
# Current percentage, without writing meter history:
python3 plugins/codex-run-budget/scripts/run_budget.py meter --no-save

# Record a baseline, do ordinary work, then record the ending:
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
python3 plugins/codex-run-budget/scripts/run_budget.py meter report

# Inspect saved snapshots or compare with an earlier ID:
python3 plugins/codex-run-budget/scripts/run_budget.py meter history
python3 plugins/codex-run-budget/scripts/run_budget.py meter report --baseline 1 --json
```

`--thread <UUID>` requests backend-estimated thread usage; repeat it for up to
eight threads. A backend that supplies `threadUsage.groups` exposes model,
reasoning effort, speed, input/cached/new-input/output/total tokens, and estimated
credits. The meter calculates **estimated credits per million total tokens**
from those native fields, not a price list. Conflicting token subtotals suppress
the ratio. Groups remain per thread; the meter does not sum potentially
overlapping parent/descendant billing into an account total.
Unknown/custom model identifiers are hashed, consistent with the local audit.

## Keep the three measurements separate

| Measurement | Meaning | Does not establish |
| --- | --- | --- |
| Native used/remaining percentage | Account quota bucket at observation time | A task-specific or model-specific charge |
| Local model request tokens | Bounded, deduplicated completion-time observations in the selected interval | All account activity, settled billing, or model quota share |
| Backend-estimated thread credits | Native estimated usage for the requested thread/model when available | Included-quota percentage or final settled charge |

The app-server documents [account quota and token activity reads](https://learn.chatgpt.com/docs/app-server#api-overview-1).
The locally generated Codex 0.154.0 protocol includes optional `threadUsage`
with `estimatedUsageCreditsMicros`; availability depends on the billing route.
For the live account tested on 2026-09-12, two real thread requests returned
`threadUsage: null`. The meter displays **unavailable**, not zero or an invented
conversion coefficient. Account-wide daily/lifetime tokens remain separate
from the interval report and its quota windows.

`rateLimitsByLimitId` takes precedence over the legacy single-bucket view.
Window names come from `windowDurationMins`: `primary` can be weekly, not just
five-hour. Missing windows/fields remain unknown. Remaining percentage is
`100 - usedPercent`, clamped to 0–100; the original reported used value remains
available. A null permission or spend-control field is not inferred from a
percentage or reset time.

## Comparing snapshots

Two saved observations are required. `report` defaults to the last two, while
`--baseline N` selects an earlier ID among the last 1,000 stored observations.
The comparison requires matching account hashes, quota bucket, slot, duration,
reset and known plan. A quota decrease, correction, missing bucket, crossed reset,
or unordered capture returns a reason and **no charge delta**. A valid increase
is measured in **percentage points**, not relative percent.

An unchanged integer percentage is below displayed resolution, not proof of
free usage. Different local models remain separate rows; their quota allocation
is always unknown without an authoritative mapping. Local Token share is not
used to split account quota. Concurrent tasks, other devices, different quota
buckets, rounding and backend reporting delay defeat that inference, even if
only one local model was observed. Reads are not atomic; capture start/end
times are retained to make sampling duration visible.

The local report selects request completion timestamps in `(baseline, latest]`.
It reuses the existing bounded survey and audit, retains their diagnostics,
and does not add cumulative `token_count` snapshots to request-level totals.
Input already includes cached input; output already includes reasoning output.
`--directory` selects a sessions root; `--limit` bounds transcript pages
(default 200, maximum 1,000). Human output shows at most 20 model rows; JSON
contains the full bounded cohort. A missing local row is not usage zero.

## Storage, failure and isolation

Snapshots live in `meter.sqlite3` under the normal run-budget data directory
(`--data-dir` overrides it). They contain hashed account/thread identities,
numeric usage and restricted labels, never raw IDs, prompts, tool text,
transcript paths, auth credentials, reset-credit details or server error text.
The meter database is separate from the enforcement ledger. Appends use a
transaction, reject user-controlled symlink paths, and never silently prune
history; the 10,000-snapshot cap requires the operator to preserve/archive
history before more recording. `history`/`report` do not create storage.

The app-server connection has a total deadline (default 30 seconds), an 8 MiB
stream limit, bounded process cleanup and safe error codes. Partial source
success is retained. Unsupported/unavailable quota produces unknown data and
snapshot exit code 2; it never changes enforcement or triggers a login/reset.
`--codex-binary` selects a known local Codex executable when needed. No new API
key or UI automation is required.

Validation evidence is maintained in [VALIDATION.md](VALIDATION.md).
