# Subscription mechanics and implementation evidence

Verified against official OpenAI documentation and the installed Codex CLI
0.154.0 protocol on 2026-09-12. This is a client-side evidence map, not a claim
to know the proprietary billing backend or an account's negotiated agreement.

## Four distinct quantities

| Quantity | Authority | What the plugin does |
| --- | --- | --- |
| Included usage percentage | Native account quota bucket/window | Record used/remaining values; compare only matching account, plan and reset |
| Available credits / spend controls | Native credit and control fields | Display independently from included usage permission |
| Task credit estimate | Optional backend `threadUsage` | Preserve model, speed, effort, tokens and estimated credits when available |
| Public-card scenario | Dated published rates plus local token observations | Reprice an explicit token cohort; never label it as any of the above |

Local messages, cloud tasks and ChatGPT Work can share usage. Published message
ranges depend on the work and are not exact message caps or token denominators.
Credits may extend eligible usage after included allowance is reached. API-key
usage follows Platform API pricing; some Enterprise agreements use legacy or USD
rate cards. A native `pro` enum alone does not resolve the exact allowance option.
[Official pricing](https://learn.chatgpt.com/docs/pricing)

Fast is a higher-credit speed mode for supported models; Spark is a distinct
preview model with a separate usage bucket. API Priority is not the ChatGPT Fast
credit tariff. Missing historical service tier, `default`, or `priority` is not
evidence that ChatGPT Fast was on or off.
[Official speed documentation](https://learn.chatgpt.com/docs/agent-configuration/speed)

Workspace spend controls depend on the workspace plan and do not govern Platform
API billing. Permission must come from the relevant authority, not a local
interpretation of credit balance or percentage.
[Official workspace controls](https://learn.chatgpt.com/docs/enterprise/usage-limits)

## Actual local execution path

1. `cli.py` routes `meter snapshot` to `meter_source.read_meter_sources`.
   The adapter launches `codex app-server --stdio`, initializes its protocol,
   then performs read-only `account/rateLimits/read`, `account/usage/read` and
   optional Task usage reads. Finally `account/read` uses `refreshToken:false`.
   The full conversation has one timeout and bounded stream size. Error text,
   credentials and reset details do not enter the normalized snapshot.
2. `meter.normalize_snapshot` allowlists native fields and hashes identities.
   The generated protocol distinguishes `ordinaryUsageAllowed`,
   `rateLimitReachedType`, `spendControlReached`, `credits` and `individualLimit`.
   The meter keeps them separate. Null means unknown; credit-only observations
   do not require a percentage window. Unknown limit-reason strings are not saved.
3. `record_snapshot` appends to a separate `meter.sqlite3` transaction. Older
   schema-1/2 payloads remain readable; missing historical fields are not filled
   from the current account. `compare_snapshots` does not allocate quota deltas
   across models or Tasks.
4. `survey.py` and `audit.py` read bounded local transcripts. Request usage is
   deduplicated; cumulative `token_count` is not added to request-level totals.
   Settings are captured at the request position, with source/status. Thread and
   turn identity, effort and Fast stay associated with those observed requests.
5. `meter estimate` uses this same offline Task selection. `meter_policy.py`
   owns both the fixed public rate card and Decimal arithmetic. It splits input
   into uncached/cached portions and includes output once. Standard/Fast columns
   reprice the same tokens; they do not select a historical billing mode. Unknown
   rates or unsupported token bases are excluded visibly.

The [official app-server guide](https://learn.chatgpt.com/docs/app-server) documents
the account reads. Optional fields and thread-usage estimates also require the
installed version's generated protocol and an actual successful account response;
a schema alone does not prove that a particular account supplies the data.

## Interpretation safeguards added in v0.8.0

- Public input/cached/output rates can explain why equal Total Tokens have
  different scenario costs. They cannot establish the included-quota denominator.
- A zero-credit balance may coexist with available subscription allowance.
- An active turn can continue after a limit, subject to fair use; this does not
  prove a new turn is admitted. Hook-based local governance is a separate guardrail.
- Backend cached plus net-new input must agree with total input before the meter
  displays a credits-per-million ratio.
- A reference older than 30 days is marked for review. That is a tool reminder,
  not a guarantee of tariff stability for the first 30 days or historical coverage.

The implementation neither changes Fast/effort/model settings nor buys credits,
sends workspace notifications, consumes resets, starts budgets or polls in the
background. No additional model workload is used to calibrate a quota tariff.

Commands and formula: [METER.md](METER.md). Validation: [VALIDATION.md](VALIDATION.md).
