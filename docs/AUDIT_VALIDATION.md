# Transcript audit validation — 2026-09-06

The new CLI was run against two existing local task transcripts. Raw files,
task IDs, prompts, commands, tool output and local paths are not published.
Labels A/B identify this evidence sample only. Files were read without modifying
their contents or the governance ledger.

| Observation | A | B |
| --- | ---: | ---: |
| Snapshot bytes | 80,196,481 | 7,078,226 |
| Records | 13,617 | 2,382 |
| Unique request response IDs | 1,854 | 304 |
| Sum of observed request total tokens | 250,894,844 | 40,573,654 |
| Cached input tokens in those requests | 247,516,928 | 39,904,000 |
| Uncached input tokens in those requests | 2,942,647 | 602,364 |
| Latest cumulative token snapshot | 232,878,914 | 23,669,081 |
| Cumulative decreases | 1 | 1 |
| Recorded outer tool calls | 1,850 | 300 |
| Repeated canonical inputs after first occurrence | 114 | 12 |
| Repetitions crossing a compaction | 42 | 1 |
| Compactions | 12 | 1 |
| Tool output UTF-8 bytes | 26,521,917 | 878,487 |

The request sums and final cumulative snapshots disagree. The report exposes
both views and the decreases; it does not claim either is invoice usage or that
the decreases necessarily result from compaction. Each sample has one observed
request thread ID. Neither sample establishes complete child-agent coverage.
A has one unmatched output, which is visible in diagnostics.

These observations motivated request-level accounting diagnostics, cache
separation, output-volume visibility, and post-compaction repetition signals.
They do not demonstrate wasted work or measured token savings. Polling and
required read-back can legitimately repeat calls. The existing live enforcement
receipt in VALIDATION.md remains specific to v0.1.1; this release changes offline
diagnostics, not hook enforcement.

Automated tests exercise request deduplication, independent cumulative totals,
cache/reasoning accounting, invalid/conflicting/partial records, canonical input
comparison, compaction, call timing, duplicate call/output delivery, privacy,
and a real CLI subprocess that must not create a ledger directory.
