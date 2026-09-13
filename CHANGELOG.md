# Changelog

All notable changes to this project are documented here.

## 0.14.0 - 2026-09-13

- Add one bounded, report-only completion check after an eligible Stop: at most eight reads with a 25-second process deadline, no model calls or Governor events.
- Require the selected turn's explicit native completion boundary before publishing revision 2, excluding later-turn counters and preserving the original child window and quota observation.
- Preserve the original Stop JSON/HTML/Markdown and inline snapshot; point the report index to a separate completion revision. Reports show revision, completion status and update time.
- Reject foreign transcript identities at start and Stop, and retain unknown/partial accounting when completion, baseline, counter or child evidence is insufficient.
- Record the mobile A/B result: a newly emitted reference loaded revised contents, while the original inline card retained its prior snapshot. Task reentry is not a promised refresh route.

## 0.13.4 - 2026-09-13

- Fix inline report text disappearing when a remote host omits or misbinds its theme variables. Pair browser system foreground/background colors and scope text styles to each card.
- Preserve report accounting, governance, and pinned runtimes. Start a new Task after updating to load the new template; existing cards remain unchanged.
- Share the rendering fix with Codex Usage Reports 0.1.1. Browser regression covers Chromium/WebKit, mobile/desktop widths, both themes, and four locales; actual iPhone remote read-back remains unverified.

## 0.2.1 - 2026-09-06

- Add an update helper that snapshots installed plugin versions and restores
  removed versions after both successful and failed installs, preserving hook
  paths still used by older tasks.
- Document idle-task updates and persistent recovery copies; do not alter hook
  trust, enabled states, or governance policy during installation.
- Validate retained old/new hooks and a real Codex exec lifecycle after recovery.

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
