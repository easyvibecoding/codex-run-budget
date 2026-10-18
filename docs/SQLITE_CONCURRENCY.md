# Concurrent hook selection and ledger initialization

## Root causes

The signed publisher previously took `BEGIN IMMEDIATE` for every selection,
including an existing Task pin, and held that writer lock while checking the
signature and reading/hashing the runtime archive. The connection waited only
100 ms. The per-hook `seed()` path also retained the same release and attempted
activation on every invocation. Contention happened before Governor admission;
serializing callers concealed it without repairing the publisher.

A separate first-open race was reproduced in `Ledger.__init__`: simultaneous
connections changing a new database from DELETE to WAL sometimes received
`SQLITE_BUSY` at `PRAGMA journal_mode=WAL` before schema migration. SQLite can
return this immediately during a lock upgrade despite the configured timeout.
Linux release CI also reproduced exhausted busy waits at cold retention writes
and `Ledger.sync_usage()` admission. Identical release metadata and unchanged
health/counters were still rewritten, creating unnecessary durable commits.
The additional repair removes these writes; policy and accounting remain atomic.

## Changes

- Existing Task pins use reads only. Each selection still verifies its signed
  manifest, bootstrap binding, runtime size and digest before executing bytes.
- Fresh selection verifies outside a transaction, then briefly locks to recheck
  the pin and active/previous identities before atomically persisting the pin or
  fallback. A competing pin wins; competing activation triggers revalidation.
  State churn is bounded to four attempts and then propagates an error.
- Seeding an already considered package does not rewrite the release or attempt
  activation. Selected runtime integrity is still checked by `select()`.
- Retaining identical verified release metadata is read-only. A conditional
  upsert also prevents a competing cold initializer from rewriting the winner.
- Identical ledger observations preserve counter/health rows without redundant
  writes. Their `updated_at` records the last value change; changed components,
  health failures/recovery and budget transitions are still persisted atomically.
- Publisher writes retain a bounded 500 ms busy timeout. This protects short
  writes; it is not the mechanism that makes pinned readers concurrent. The
  publisher remains in its existing DELETE journal mode.
- Ledger startup first reads the journal mode. Only the initial WAL transition
  retries BUSY, with backoff bounded by a one-second deadline. Other failures
  propagate. Initialization failures close their connections.
- SQLite failure messages expose fixed exception classes, never exception text.
  Ledger/publisher failures continue to deny supported admission hooks.

## Offline evidence

The tests use disposable databases, synthetic identities, generated test keys
and the real Governor/runtime. No installed hooks, live ledger, Task pins or
publisher credentials are changed.

Before the fix, four publisher regressions failed: pinned selection during a
writer, 24 simultaneous delayed archive reads, verification outside the writer
transaction, and the SQLite diagnostic label. The deterministic first-open WAL
regression also failed before the ledger change. All pass after the changes.

Coverage in `test_publisher_concurrency.py` and `test_ledger_initialization.py`:

- 24 independent Python hook processes released together: cold initialization,
  one shared pin, repeated reads, 24 distinct Tasks, and three concurrent runs.
- Pre/PostToolUse replay: each run retains exactly eight admitted/completed
  calls, zero remaining in-flight calls, and respectively 120/240/360 tokens.
  Raising one source to 1,001 tokens blocks that run under its 1,000-token limit
  while the other runs remain admitted.
- Process termination before and after pin/admission commit; retry retains
  exactly one pin/admission and does not double count cumulative usage.
- Concurrent activation, peer pinning, fallback races, bounded state churn,
  exhausted busy waits, connection cleanup, and fail-closed recovery.
- Ten rounds of 24 simultaneous ledger constructors, schema version and
  integrity checks, plus deterministic journal-transition/error tests.

A separate replay copied an existing diagnostic fixture and verified its
original signed archive without opening live databases. Three baseline bursts
succeeded 12/24, 11/24 and 12/24; the candidate succeeded 24/24 in all three.
Both implementations succeeded 24/24 sequentially. The original fixture's
checksums were unchanged. This is controlled reproduction, not recovery of a
historical exception that the old hook did not record.

An additional diagnostic restricted all 24 interpreters to one Linux CPU.
Even after removing redundant writes, 13 of 16 tests exhausted bounded busy
waits at necessary fresh-pin/admission/migration transactions. That deliberately
constrained experiment is not a passing result or a supported throughput
guarantee. It remains fail-closed; waits and hook timeouts are not expanded to
hide host saturation. The required repeated replay uses the normal CI runner,
matching the original multi-process concurrency scope without CPU affinity.

## Release and adoption

Version 0.19.13 rebuilds the deterministic artifacts and signs the release with
its existing publisher key. No public policy or trust root is changed. The
bootstrap contract changes, so compatible runtime auto-updates alone cannot
install this repair. Ordinary releases with an unchanged bootstrap continue to
use the existing one-time native grant and automatic signature verification.

The original source repair was first validated in a disposable test-signed
package: all 524 tests, Ruff and repository validation passed. That package was
never installed or published. The production candidate uses the existing
publisher signature and adds installer regressions for retaining prior
bootstraps and rejecting newly installed mismatched entries.

Install only while affected execution windows are idle. The supported updater
retains old artifacts and completes their integrity checks before prewarming
installed bytes. It does not import or activate an older retained bootstrap
through a new installer. New entries must still match the reviewed installer.
Use normal native hook review; do not modify trust records or hot-replace an
active plugin. Record a real Codex canary before claiming live recovery.

Verify which embedded hook each existing Task actually retains; this patch
cannot silently upgrade an old captured command. Preserve original pins,
refusals, usage, epochs and ceilings. Do not reset a budget or create a fresh
Task to erase an original refusal. See [signed updates](SIGNED_UPDATES.md).
