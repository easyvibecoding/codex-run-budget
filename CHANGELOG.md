# Changelog

## 0.19.0

- Add an opt-in paired-project watcher that checks two remote `main` branches and queues an exact source range for a Codex App heartbeat to open a review Task in the opposite project.
- Keep exact SHA cursors and uncertain dispatches pending so unattended scans do not duplicate Tasks; require an explicit decision or retry to recover.
- Keep the coordinator outside hook execution and budget policy. It does not copy code or change either plugin's reporting and governance boundaries.

## 0.18.0

- Add per-window cache-read share and request counts to Task reports, with localized Markdown and HTML summaries.
- Count explicitly observed model, reasoning-effort, and service-tier changes between ordered adjacent requests in the same Task.
- Keep missing settings and timestamp ties unresolved; local observations do not diagnose server-side cache misses or estimate savings.

## 0.17.0

- Add fixed publisher-trust hooks with signed runtime and CLI updates, enabled by default.
- Verify RSA-3072/SHA-256 release signatures, runtime digests and bootstrap compatibility; reject replayed releases.
- Pin each Task to its starting runtime, retain the previous version, and provide status, on/off, update and rollback controls.
- Preserve native hook trust across routine updates; new entry definitions still need one user review.
- Keep the independent hook-trust reminder and all existing reporting/governance policies.

## 0.16.0

- Fix the repository retention updater to recognize and validate the separate
  reminder hook without changing trust or relaxing runtime identity checks.

- Add first-prompt update and native hook-trust notices with private deduplication,
  a bounded version cache, and separate unknown states.
- Keep a standalone reminder definition stable across main-runtime updates so it
  can explain CLI `codex` → `/hooks` reauthorization while changed hooks are skipped.
- Add `updates check` for manual read-back before hook trust; no auto-update,
  auto-trust, model calls, or policy changes.

## 0.15.0

- Add project-scoped exec activity lists, foreground change monitoring and an optional
  launcher with private start/exit receipts, including ephemeral runs.
- Add nonblocking, deduplicated hook notices at tool-return boundaries.
- Keep launcher attribution, native child lineage and usage scopes distinct;
  preserve unknown/partial observations and all existing budget decisions.


All notable changes to this project are documented here.

## 0.14.1 - 2026-09-13

- Separate native request/thread counters from legacy `token_count` events before reset detection. Different historical baselines no longer produce a false counter-reset result.
- Prefer a validated native counter for the selected turn even when a later legacy event uses a different total. Native turn usage remains available without subtracting incompatible sources; fallback subtraction requires matching sources.
- Preserve same-source counter regression, malformed native turn counters, source identity and completion-boundary checks. Store `counter_source` in preview, Stop and completion evidence; budget governance is unchanged.

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
