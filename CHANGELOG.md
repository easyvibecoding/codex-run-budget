# Changelog

All notable changes to this project are documented here.

## 0.2.0 - 2026-09-06

- Add a read-only `audit` command for existing Codex task/tool transcripts.
- Separate deduplicated request usage from cumulative snapshots; expose cache
  usage, cumulative decreases, accounting differences, and largest requests.
- Report tool output sizes, observed spans, repeated calls and post-compaction
  repetitions without exporting raw tool data or opening the governance ledger.
- Validate against recent real task records; retain existing enforcement limits.

## 0.1.1 - 2026-09-03

- Make the repository validator compatible with the declared Python 3.10 minimum.

## 0.1.0 - 2026-09-03

- Add a dependency-free Codex Plugin with lifecycle hooks and a run-budget skill.
- Add an atomic SQLite ledger shared by parent and descendant agents.
- Reconcile transcript token totals into privacy-preserving lineage events.
- Add deterministic token, tool, output, repeat, concurrency, and subagent policies.
- Add STEER guidance, HALT/resume/off controls, fail-closed markers, and an operator CLI.
- Add concurrency, privacy, protocol, and policy tests.
