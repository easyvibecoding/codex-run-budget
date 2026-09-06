# Reliability hardening (v0.3.0)

Scope: address review findings without adding user configuration. Keep the
existing control line and default policy values. Governor remains the policy
interface; the hook entry point supplies transport/error handling only.

## Invariants and decisions

- Unknown transcript usage never replaces a previous accounting value with zero.
  A readable new transcript without usage can start at zero with pending status.
  Read failures and regressions retain the high-water mark. Default fail-closed
  runs pause supported admission while data is unavailable; valid data recovers
  automatically. Counter decreases alone are not evidence of a new accounting epoch.
- Initialization and invalid-input faults produce event-appropriate decisions.
  Fixed hook event arguments allow safe failure even when JSON cannot be parsed;
  Stop must not request another model turn. Existing fail-open markers are honored
  when identifiable, and failures never echo input content or exception messages.
- Agent admission reserves capacity inside the same SQLite transaction as tool
  admission. Pending and active agents share the existing ceiling. SubagentStart
  consumes a pending slot once; reservations expire with the existing lease.
  Start events have no documented tool-call ID, so pool matching is conservative,
  not an exact parent-call attribution claim. Unexpected over-cap starts halt
  later supported work; hooks cannot undo an already-started agent.
- Changed output hashes reset a repeated-call streak. Explicit wait/poll tools
  are exempt only from repeat HALT, not other limits. Identical results still do
  not prove semantic non-progress; hidden state and alternating loops remain limits.
- Schema changes are additive with a versioned migration, online SQLite backup,
  rollback evidence, and no prompt/input/output text in new tables. Old tasks
  retain their installed code and do not acquire these fixes until restarted.

## Acceptance

Regression tests cover 100 → unavailable → 120 without double-counting, known
zero vs unknown, oversized/malformed transcripts, counter regression recovery,
bootstrap corruption, oversized/malformed hook JSON for all admission/stop
events, fail-open/closed behavior, concurrent delayed Agent starts, lifecycle
duplicates and lease recovery, output changes, polling, and v1 migration.

Run repository-required checks, plugin/skill validation as applicable, real
Codex exec through installed hooks, and exact-commit CI before release. Preserve
existing cache versions using scripts/update_plugin.py. Publish only verified
claims: no zero-overshoot, universal hosted-tool interception, billing accuracy,
automatic termination of existing processes, or model-level budget reservation.

## Local installed evidence — 2026-09-07

- Python unit suite: 44 tests passed; Ruff, repository, plugin, and skill
  validators passed.
- The official installer selected v0.3.0. The retention helper restored caches
  for v0.1.1, v0.2.0, and v0.2.1. The normal Codex `/hooks` review UI trusted
  the 11 changed hooks; no trust bypass flag or hand-written trust hash was used.
- The existing ledger upgraded from v1 to v2 automatically, produced an online
  backup, and returned `PRAGMA integrity_check = ok`. Its original run's status
  and spend and all five original event payloads matched the pre-upgrade snapshot.
- A fresh Codex CLI 0.153.2 task with `tokens=10k tools=2` ran exactly one `pwd`
  and returned `HARDENING_OK`. At Stop, the ledger held 52,072 observed tokens,
  one completed tool, zero in-flight calls, `usage_status=ok`, and HALT.
- Resuming that same task with a request for another `pwd` completed with zero
  input/output/reasoning tokens and no tool execution. No same-turn overshoot
  improvement is claimed: this test deliberately exceeded the 10k ceiling.

The concurrency and missing-data scenarios are deterministic isolated tests,
not claims of real hosted-tool interception or measured cost savings.

## Migration and rollback

Migration `002_hardening.sql` adds only health, reservation, and result-hash
tables. `PRAGMA user_version=2` is authoritative even when a retained v1 hook
rewrites the legacy metadata value. The automatic online backup is stored in
the ledger directory's `backups/ledger-v1-*.sqlite3`; it is validated before
migration. A failed migration prevents normal hook admission under fail-closed.

Prefer code rollback with the additive tables retained. A full data rollback
requires stopping all hook writers, saving the current ledger, and restoring
the selected validated backup through SQLite's backup API; never copy a live
WAL database over another live database. This loses events after the backup and
must not be used just to resume a halted run. Old cached hooks remain old code
and do not gain the hardening guarantees. Restart tasks to pick up v0.3.0.
