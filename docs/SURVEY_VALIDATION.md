# v0.4.1 validation evidence

Observed locally on 2026-09-11 (Asia/Taipei). The task cohort is private; only
aggregate counts and validation methods are published here. These are observed
records, not billing totals or an account-wide complete inventory.

## Frozen recent-task cohort

The product audit was run over the same 194 source-path hashes selected before
implementation, with event timestamps from 2026-09-06 16:00:00 UTC through
2026-09-10 20:26:01 UTC. File-size and per-record limits stayed enabled. Native
record schema and independent aggregate probes supplied a cross-check.

- Metadata identified 186 threads: 20 parent threads and 166 subagents, including
  seven threads with multiple pages. Shared session IDs were not used as caller
  identity.
- There were 27,037 unique per-response usage records. Of these, 4,068 lacked
  matching model context in the selected cohort: every such record identified
  a different thread from the containing page, and no matching context was
  present. They remain `unknown`, not attributed to the containing thread.
- Request totals were 3,549,849,720 tokens, including 3,460,585,472 cached-input
  tokens. Repeated request context contributes to these totals. They are not
  unique context size, billed tokens, subscription utilization, or savings.
- There were 2,010 repeated-input calls: 1,328 with changed result hashes,
  681 with unchanged results, and one unknown. Equality does not prove wasted
  work, and a changed result does not prove useful progress.
- Eighteen records exceeded the 8 MiB record limit. Missing context, unmatched
  results, and invalid records remain diagnostic limitations.

## Wait-setting comparison

After the independently observed configuration-update timestamp
2026-09-09 07:50:07 UTC, the frozen cohort contained 341 `wait_agent` calls:
249 explicit timeouts, 86 explicit event returns, and six unknown outcomes.

| Root cohort | Calls | Explicit timeouts | Timeouts observed under 60 seconds |
| --- | ---: | ---: | ---: |
| One root created before the settings update | 277 | 239 | 238 |
| Four roots created after the settings update | 64 | 10 | 0 |

The new roots mostly requested 900,000 or 1,500,000 ms. All 238 short timeouts
were in the older tree. This supports separating old/new task trees when
evaluating configuration rollout. It does not prove causality or quantify
token savings. Event returns do not necessarily mean agent completion. No wait
configuration or budget policy was changed by this survey.

## Cache-eviction canary

A fresh isolated Codex CLI 0.154.0 home installed v0.4.1 from the local
marketplace and reviewed/enabled its eleven hooks. The same canary also passed
with the desktop app's bundled Codex 0.153.4. Only this fixture received
the test policy `tokens=1m tools=1`; the operator's task policy was untouched.

The controller moved only the fixture's versioned plugin-cache directory after
the first successful `pwd`. The second requested command was refused. The real
Codex turn ended with `turn.completed`, process exit status zero, and exactly
one successful command. The cache was restored in a `finally` block.

Ledger read-back confirmed `status=halted`, `tool_calls=1`,
`max_tool_calls=1`, `halt_reason=tool-call ceiling reached (1)`,
`usage_status=ok`, no usage issues, and one durable runtime. This verifies
initialized SHA-pinned commands surviving cache eviction while enforcement
remains active, not arbitrary disk-loss recovery or old-command migration.

All 75 unit/integration tests, Ruff, repository, plugin, and skill validators
passed locally. Automated tests exercise missing/corrupt runtime handling, pinned
version isolation, migration resources from verified memory, source limits,
thread/model attribution, conflict reporting, and updater recovery. CI checks
the release on Python 3.10–3.13; each release's commit status is authoritative.

## Local migration read-back

The retention-aware updater completed both a timestamped local iteration and
the final v0.4.1 install. Exact v0.3.0 code was restored from its published commit
for legacy pathname commands. Prior 0.3.0/0.4.0 caches remain available, and the
temporary iteration was moved to an external recovery directory. The installed
v0.4.1 package matched the source byte-for-byte, excluding generated pycache.
The SHA-pinned runtime was prepared outside the cache before enabling hooks.

After authorized restoration through Codex's version-checked config interface,
hooks/list reported all eleven Run Budget hooks enabled/trusted from v0.4.1 and
the one previously trusted unrelated hook enabled. Warnings and errors were
empty. The updater itself never writes these trust/enable settings.
