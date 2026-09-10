# Recent-task telemetry (v0.4)

## Why this extension

The governance ledger describes explicitly budgeted runs. It cannot explain
ordinary tasks that never started a budget. Recent Codex task histories also
contain multiple pages, multiple models, shared session IDs, and explicit
execution timing that the original single-file audit did not use.

The new `survey` command is an offline diagnostic, not another enforcement
mechanism. It discovers recent local pages with safe defaults and returns a
compact summary; `--json` exposes the source, thread, model, timing, and coverage
evidence. It never opens the ledger, changes configuration, trusts hooks,
starts a task, or calls a model or network service.

## Interface and evidence

`audit_transcript(path)` remains the single-file interface.
`audit_transcripts(paths, since=None, until=None)` performs multi-page analysis.
`survey_transcripts(directory=None, days=7, limit=200)` supplies bounded local
discovery and a time window. Tests and the CLI use the same interfaces.

- `session_meta.id` identifies an actual thread. `session_id` can be shared
  with its parent and must not collapse parent and child into one caller.
- Explicit thread and turn metadata determine model attribution. Unknown or
  conflicting attribution stays visible rather than inheriting a guessed model.
  Native call records without IDs use the preceding explicit metadata/context
  in the same page. A new thread metadata boundary resets the active turn.
- Per-response request usage is deduplicated across pages. Cumulative snapshots
  remain a separate check; they are not added to request totals or blindly
  added across parents and descendants. Decreases compare only the same source
  page stream. Multiple sources for one thread are explicitly diagnosed; their
  interleaved snapshots do not establish one continuous counter.
- Tool identity includes its namespace. Call/result identity is thread-scoped,
  while response IDs identify requests. Duplicate or conflicting records are
  diagnostics; missing identifiers do not become a shared `hash(None)` record.
- `item_completed` start/end timestamps supply observed execution spans where
  available. Original call-to-result spans remain distinguishable. Neither
  describes CPU time, and overlapping spans must not be added as wall-clock time.
- Only allowlisted `wait_agent` calls with explicit JSON `timed_out` values
  classify as timeout or event return. An event return is not necessarily a
  completed agent. Duration alone never establishes a timeout.
- Reused tool inputs are compared with previous result hashes. Changed,
  unchanged, and unknown results are separated without claiming semantic
  progress, wasted work, or permission to skip required verification.

## Scope and privacy

Default discovery considers at most 100,000 directory/file entries, selects up
to 200 recent regular JSONL pages, and does not follow descendant symlinks.
Audits cap each page at 256 MiB, the total snapshot at 4 GiB, and parsed records
at 500,000. File descriptors reject non-regular files and final symlinks and
check replacement/growth against the captured snapshot. Large records,
missing files, limits, incomplete work, and conflicts must remain visible.
The selected cohort is not an account-wide billing window or an exhaustive
task-tree inventory when some pages are missing or outside the window.

Only hashes, fixed labels, timestamps, numeric usage, and diagnostic enums
leave the parser. Standard model names use an exact allowlist; unknown custom
model names are hashed. Prompts, task titles, commands, arguments, outputs,
raw IDs, and filesystem paths are not included in reports.

## Interpretation

When comparing a configuration change, separate task trees created before and
after that change. Old tasks can continue to produce old behavior after the
configuration file is edited. Observed before/after differences do not, by
themselves, prove causality or quantify token savings.

High request-token totals include cached input repeatedly used in requests;
they are not unique context size, a monetary charge, or the account's usage
percentage. Waiting and repeated-result candidates support investigation,
not automatic HALT. The v0.3 governance policy remains unchanged.
