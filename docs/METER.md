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

# Cross-task history without a saved baseline or a network request:
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --days 1
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --thread <UUID> --json
# Filter local tasks in a quota interval; quota itself is still account-wide:
python3 plugins/codex-run-budget/scripts/run_budget.py meter report --thread <UUID>
# Dated official mode/plan reference, not measured charges:
python3 plugins/codex-run-budget/scripts/run_budget.py meter rates
# Reprice local text tokens under the dated card: NOT historical charges:
python3 plugins/codex-run-budget/scripts/run_budget.py meter estimate --days 1
```

`--thread <UUID>` requests backend-estimated thread usage; repeat it for up to
eight threads. A backend that supplies `threadUsage.groups` exposes model,
reasoning effort, speed, input/cached/new-input/output/total tokens, and estimated
credits. The meter calculates **estimated credits per million total tokens**
from those native fields, not a price list. Conflicting token subtotals suppress
the ratio. Groups remain per thread; the meter does not sum potentially
overlapping parent/descendant billing into an account total.
Unknown/custom model identifiers are hashed, consistent with the local audit.
Unrecognized quota bucket IDs and display labels are also hashed before storage.

## Cross-task configuration history

`tasks` scans the bounded local cohort (seven days and 200 pages by default).
Repeat `--thread` to select exact Task UUIDs, not parent session IDs. It keeps
Task, turn, model, role, reasoning effort, service tier and Fast state together
with their request tokens. Human output shows 20 rows; JSON includes the full
bounded selection and per-field source/status. Missing selected Tasks are not
zero-usage Tasks. Parent/subagent identities stay separate; no Task is restarted.

Historical context is captured at each request's physical transcript position.
Later settings do not fill earlier requests, and today's config is never used
to reconstruct historical Fast or reasoning settings. Explicit `fast` records
Fast=true, `normal`/`standard` records false. A missing value, `default`, or API
`priority` does not prove ChatGPT Fast is on or off. Duplicate response evidence
is deduplicated; conflicting metadata stays unresolved. Context may be a
requested configuration, not proof of backend execution or settled billing.

The local cohort tested on 2026-09-12 contains turn-level model and effort.
Some pages omit service tier; others record only `default`. Neither proves
historical Fast on/off, so those Fast values remain **unknown**.
When official thread usage provides speed/effort, the meter displays that
separate backend estimate; it does not retrofit that group onto specific local
requests. No prompt, command or unstructured log text is mined to guess Fast.

## Subscription and consumption context

Snapshots additionally read `account/read` with `refreshToken:false`, keeping
only the allowlisted billing route and plan enum. Quota-bucket plans remain
separate evidence; disagreement is a conflict. A missing account endpoint can
fall back to a clearly-labelled bucket-plan observation. Native plan enums do
not establish the exact Pro allowance option, so `tier_multiplier` remains null.
Old snapshots remain readable and are never backfilled with today's plan.

Historical local plan rows use a preceding same-page `token_count` plan snapshot,
labelled `nearby_observation`; that is not the billed plan of a specific request.
An observed account/plan/billing-route change invalidates quota comparisons.

The dated `rates` reference was verified on 2026-09-12:

- [Fast mode](https://learn.chatgpt.com/docs/agent-configuration/speed): where supported,
  ChatGPT-credit Fast consumes 2.5x for Astra/5.6/5.5 and 2x for 5.4.
- [Plan context](https://learn.chatgpt.com/docs/pricing): Pro has 5x and 20x allowance
  options relative to Plus. These are published options, not detected account tiers.

The reference is not a live price resolver and may age. API Priority has separate
pricing; reasoning has no fixed multiplier in this meter. No published factor is
multiplied by local tokens to invent a Task charge or quota percentage.

## Keep the three measurements separate

| Measurement | Meaning | Does not establish |
| --- | --- | --- |
| Native used/remaining percentage | Account quota bucket at observation time | A task-specific or model-specific charge |
| Local model request tokens | Bounded, deduplicated completion-time observations in the selected interval | All account activity, settled billing, or model quota share |
| Backend-estimated thread credits | Native estimated usage for the requested thread/model when available | Included-quota percentage or final settled charge |

`meter estimate` adds a fourth, explicitly **counterfactual** measurement. It
uses a dated public ChatGPT text-token rate card, not an account billing record.
The Standard formula is:

```text
credits = ((input - cached_input) × input_rate
           + cached_input × cached_rate + output × output_rate) / 1,000,000
```

The Fast scenario applies only the documented model-specific Fast factor to the
same priced token basis. The two columns are scenarios, not a statistical range
or evidence that switching modes preserves output/work. Recorded Fast/effort is
shown alongside them without selecting an actual charge. Reasoning tokens are
already in output; there is no effort multiplier. Unknown model rates and
unsupported cache-write bases are excluded with request coverage. A missing
Fast rate makes the combined Fast scenario unavailable, not zero. Tools, images,
voice, retrieval-specific charges and account agreements are not reconstructed.

The reference includes its source, verification date, and a 30-day review
reminder. That interval is this tool's maintenance heuristic, not an official
validity period; applying today's card to older tokens does not establish a
historical rate. API, legacy Enterprise and USD agreements may differ. No
credits-to-dollars or credits-to-included-quota conversion is exposed.

## Subscription mechanics and native controls

The [official pricing documentation](https://learn.chatgpt.com/docs/pricing)
distinguishes shared included usage from credits that can extend eligible usage.
Local, cloud and ChatGPT Work activity can share allowance; published message
ranges are illustrations, not fixed message/token ceilings. Spark has its own
preview bucket and is not a Fast toggle. An active turn may continue after a
limit is reached, subject to fair use; that is not proof a new turn is allowed.

The generated Codex CLI 0.154.0 protocol distinguishes `ordinaryUsageAllowed`,
`rateLimitReachedType`, `credits`, `individualLimit` and `spendControlReached`.
The snapshot preserves and displays these independently. Known backend limit
reasons are allowlisted; missing/new enum values remain unknown. A credit-only
snapshot can be available without a percentage window. Neither a 0-credit
balance nor a displayed 100% window establishes general access by itself.
No notification, top-up, reset or configuration-write RPC is called.

See [app-server fields](https://learn.chatgpt.com/docs/app-server) and
[workspace spend controls](https://learn.chatgpt.com/docs/enterprise/usage-limits).
Workspace controls are plan-dependent and do not govern Platform API billing.

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
