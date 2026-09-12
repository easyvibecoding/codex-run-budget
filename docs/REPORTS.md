# Multi-window Task reports

`report` is a read-only report builder, separate from `meter report` (the latter
compares saved native snapshots). It works for tasks without an enabled budget.
Python 3.10+ and the standard library are sufficient; IANA calendar zones use
the host's timezone database.

```sh
# Recent observed Tasks; private Markdown output suitable for Codex's file viewer.
python3 plugins/codex-run-budget/scripts/run_budget.py report \
  --timezone Asia/Taipei --output usage.md

# Interactive, offline HTML: window and detail-Task selectors; print/save as PDF.
python3 plugins/codex-run-budget/scripts/run_budget.py report \
  --windows 5h,24h,7d,30d,today,week,month --timezone Asia/Taipei \
  --format html --output usage.html

# Exact Task selection; repeat --thread for multiple Tasks, not automatic tree expansion.
python3 plugins/codex-run-budget/scripts/run_budget.py report \
  --thread 12345678-1234-1234-1234-123456789abc --windows 24h,7d --format json

# Historical interval; timestamp offsets are mandatory.
python3 plugins/codex-run-budget/scripts/run_budget.py report \
  --since 2026-09-11T00:00:00+08:00 --until 2026-09-12T00:00:00+08:00
```

## Window and evidence semantics

- Default: `5h,24h,7d,30d`. Positive integer `Nh` and `Nd` rolling windows use
  elapsed seconds. `today`, `week` (Monday start), and `month` use calendar
  boundaries in `--timezone`, including DST. Default timezone is UTC.
- Every window is `[since, until)`, ending at the same captured instant or an
  explicit `--until`. A custom `--since` selects one custom window by default;
  explicit `--windows` can add comparisons. Up to 12 windows and 365 elapsed
  days are supported. Overlapping windows are independent and must not be added.
- Discovery and parsing happen once per report. Each request belongs to its
  recorded usage timestamp; this is not a prorated model execution interval.
  Deduplicate response IDs before grouping. Disagreeing duplicate timestamps
  are excluded with a visible counter, including attribution-conflicted replays.
  Unplaceable-time counts describe selected pages, not an allocated time window.
- Discovery is bounded to the newest 200 matching local pages, up to 4 GiB,
  using existing survey limits. `--limit` supports 1–1000. This can make a
  30-day and 7-day cohort identical: it does not prove there was no older usage.
  Coverage carries discovery skips and audit evidence issues. Missing observations
  are null, never an inferred zero bill.
- Group by Task, model, contemporaneous reasoning/Fast/service tier/plan, and
  turn. Context statuses and sources remain in JSON; no current configuration
  fills historical gaps. Turn rows are observed request groups, not proof of
  running, completed or aborted work. Missing turn IDs remain unidentified.
- Context details show the highest-token groups; turn details show the latest
  groups. Each is limited by `--detail-limit` (default 200, range 1–2000).
  Counts and truncation flags are explicit; totals and credit scenario coverage
  are calculated before detail truncation. A Task filter in HTML affects only
  detail rows, not the top-level comparison. A truncated view can have no
  matching detail even when aggregate usage exists.
- Input includes cached input; output includes reasoning. Do not add these
  subsets twice. Standard/Fast credits reuse the same dated-card token cohort,
  not the historical mode, actual charges, USD or quota percentage.

## Native quota and subscription

The report only reads existing `meter.sqlite3` snapshots; it does not make
network requests or save new observations. Use `meter snapshot` separately when
a fresh capture is requested. The latest saved snapshot includes its timestamp
and age at report end; it is not labeled live. Historical reports exclude later
snapshots. Credit balance is distinct from included quota and usage permission.

Within each requested window, earliest/latest saved captures form an observed
subinterval, not a full-window estimate. Comparisons reject account, plan,
reset, route and window discontinuities, including intermediate observations.
No interpolation fills missing boundary captures, and no native percentage is
allocated to selected Tasks. History reads at most the latest 1,000 saved rows;
the cap is visible. A long-ago report may lack native history despite local
transcript observations.

## Output and native Codex presentation

Markdown, HTML and JSON share one report schema. `--output` creates a new file
with mode `0600`, refuses existing files and symlink paths, and caps exports at
16 MiB. Use a new output filename on each capture. Parent directories must
already exist. Without `--output`, the selected format goes to stdout.
The renderer escapes untrusted values; standalone HTML has a restrictive CSP,
no network dependency and no remote telemetry. Reports retain only allowlisted
numeric/context observations and hashed identities—not titles, prompts or raw
transcript paths. Keep exported reports private because aggregates can still
describe work patterns.

Codex's [official changelog](https://learn.chatgpt.com/docs/changelog) documents
rich Markdown/PDF sidebar previews (26.410), the artifact viewer (26.415), and
in-app browser support for local/file-backed pages (April 23, 2026). Open the
Markdown with the app's file-viewer action; open HTML in its browser when
supported, or a local browser. This is a generated report, not a replacement
or injected extension of Codex's built-in quota widget. Interactive conversation
visuals may be offered when the installed visualization capability is available;
they are not required for report generation.

HTML printing uses the selected window/Task details and keeps all-window
comparisons visible. Expand turn details before printing if they are wanted.
PDF saving uses the browser's print dialog, not a bundled PDF dependency.

The report never creates a budget, changes hooks/settings, resumes Tasks,
polls, resets quota, or submits extra model work.

## Validation — 2026-09-13 (Asia/Taipei)

- Full suite: 167 tests; Ruff and repository/plugin/skill validation passed.
  New report tests exercise single capture, half-open boundaries, DST/calendar
  weeks, exact Task scope, deduplicated and missing/conflicting timestamps,
  saved native subintervals and intermediate account discontinuities, detail
  truncation, unknown data, escaping, private/no-clobber output, and no ledger
  creation. Existing audit and governance tests remain in the full suite.
- Installed an isolated cachebusted 0.9.0 development build through Codex's
  installer, then generated a real Task-scoped report from local transcripts.
- Real all-Task capture selected 200 pages. Coverage was explicitly partial;
  its 7-day and 30-day totals matched because of selected-page coverage, not
  evidence that account usage was identical. No transcript contents were exported.
- Headless installed Chrome verified window/Task selectors, expanded turn
  details, CSP/no runtime errors, page overflow at 320/736/1200 px, light/dark
  presentation, and print visibility. Narrow tables scroll within their own
  container rather than breaking long numeric values across lines.
- Hook archive comparison against 0.8.0 changed only package version metadata;
  governor/ledger/enforcement code is unchanged. This report work makes no new
  lifecycle-enforcement or billing-grade claims.
