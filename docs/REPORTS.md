# Multi-window Task reports

`report` is a read-only report builder, separate from `meter report` (the latter
compares saved native snapshots). It works for tasks without an enabled budget.
Python 3.10+ and the standard library are sufficient; IANA calendar zones use
the host's timezone database.

```sh
# No-scan menu; metadata-only names and ownership.
python3 plugins/codex-run-budget/scripts/run_budget.py report
python3 plugins/codex-run-budget/scripts/run_budget.py report tasks --limit 10
python3 plugins/codex-run-budget/scripts/run_budget.py report agents

# Current Task only; artifact saved, compact summary/link returned.
python3 plugins/codex-run-budget/scripts/run_budget.py report task \
  --windows 24h --timezone Asia/Taipei \
  --format html --output usage.html

# Explicit descendant usage (unlike metadata-only report agents).
python3 plugins/codex-run-budget/scripts/run_budget.py report tree \
  --thread '<task-id>' --windows 24h

# Explicit cross-Task historical interval; never an implicit default.
python3 plugins/codex-run-budget/scripts/run_budget.py report window --all-tasks \
  --since 2026-09-11T00:00:00+08:00 --until 2026-09-12T00:00:00+08:00
```

## Scope-first invocation and names (v0.11)

Codex's supported [slash entry point is `/skills`](https://learn.chatgpt.com/docs/developer-commands#use-skills-with-skills).
Select `usage-task`, `usage-agents`, or `usage-window`; `$skill-name` also invokes
the corresponding skill. These three small instructions do not load a full
report or every analysis mode. No native `/usage-task` parser is claimed.

Bare `report` is a menu with no Task or transcript reads. `report task/window`
defaults to `CODEX_THREAD_ID`; missing identity errors instead of expanding.
`--thread` accepts an exact UUID or unambiguous 12–64 character hash selector
from `report tasks`. A cross-Task window requires both `--all-tasks` and an
explicit time range. Library callers must also provide exact `thread_ids` or
explicit `all_tasks=True`. Exact scope filters run before file selection and
audit; ordinary Codex UUID filenames exclude unrelated bodies without opening
them. Alternate filenames may require only a 128 KiB metadata header.

Private reports use native `threads.name`, agent nickname and logical agent path
from Codex's read-only `state_5.sqlite`, never the prompt-like `title`, preview or
first-user-message columns. These are observed current names, not a historical
name reconstruction. Display names are not unique identities; hashes still join
the evidence. Missing names remain unnamed, without model-generated guesses.

Agent ownership follows `source.subagent.thread_spawn.parent_thread_id`, not
similar titles or timestamps. Immediate parent and root Task are separate.
Trees default to 20 entries (at most 64 for usage); traversal has a depth cap of
12 and reports truncation/cycles. Catalog reads have a 0.8-second query deadline
and bounded strings; the local schema is not a public contract, so unavailable
or conflicting metadata remains explicit. The catalog does not modify Codex.
Names can reveal work topics: keep exports private and review before sharing.

`report task` is one native Task, including when the selected Task is a
subagent. `report tree --thread PARENT` is the explicit parent-plus-descendant
view. The subagent's own card or Task report and the parent's descendant subtotal
can contain the same observed requests; do not add those displayed totals to
each other. Automatic parent-turn cards use only their bounded turn observation
window, whereas a manual tree report uses its selected time window. Missing
lineage, truncated discovery, or unavailable counters stay partial or unknown.
Automatic child and ancestor cards show a matching short hashed `@selector` for
visual correspondence. The selector itself is not proof of parent ownership.

## Window and evidence semantics

- Default: one `24h` window. Positive integer `Nh` and `Nd` rolling windows use
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
- Each window now includes `cache_observation` in JSON. `read_share_percent` is
  observed cached input divided by observed input; zero input gives `null`.
  `observed_setting_changes` counts model, reasoning-effort, and service-tier
  changes only between time-ordered adjacent requests in the same Task with
  explicit observed settings. Timestamp ties and missing settings are not
  classified. These changes are investigation signals, not official cache-miss
  diagnoses. A zero cached-input request is not by itself a cache miss. Cache
  writes are deliberately omitted from this observation because local native
  write counts may be unavailable even when their field exists.
- CLI discovery is bounded to the newest 20 matching local pages, up to 4 GiB,
  using existing survey limits. `--limit` supports 1–1000. This can make a
  30-day and 7-day cohort identical: it does not prove there was no older usage.
  Coverage carries discovery skips and audit evidence issues. Missing observations
  are null, never an inferred zero bill.
- Group by Task, model, contemporaneous reasoning/Fast/service tier/plan, and
  turn. Context statuses and sources remain in JSON; no current configuration
  fills historical gaps. Turn rows are observed request groups, not proof of
  running, completed or aborted work. Missing turn IDs remain unidentified.
- Context details show the highest-token groups; turn details show the latest
  groups. Each is limited by `--detail-limit` (CLI default 20, range 1–2000).
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
already exist for an explicit output path. Without `--output`, a new private
artifact is created under the budget data directory's `reports/`. Stdout is only
a bounded summary and file link. `--full` explicitly prints the entire artifact
instead; skills must not do this or read the saved full artifact by default.
The renderer escapes untrusted values; standalone HTML has a restrictive CSP,
no network dependency and no remote telemetry. Reports retain only allowlisted
numeric/context observations, native display names/aliases and hashed identities,
not prompt/title/preview fallback or raw transcript paths. Keep reports private because they
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

## Repository data hygiene

Generated Markdown/HTML/JSON reports are private artifacts and must not be
checked into the repository. Keep them under the local budget data directory
or an ignored `outputs/` directory, and review any export before sharing. Do
not commit prompts, transcript or tool content, native Task names/IDs, private
paths, account identifiers, credentials, database dumps, or real workflow
samples. Documentation and tests use `example.invalid`/`example.com` and
constructed values instead. Author and copyright metadata may remain in the
public files; names and contact details still need a human ownership review.

The dependency-free gate scans the exact staged index and refuses findings:

```sh
python3 scripts/check_sensitive_data.py --index --fail-on-findings
```

`git config core.hooksPath .githooks` enables the repository pre-commit and
pre-push checks. CI fetches full history and audits every reachable blob,
including members of `runtime/hook.pyz`; scanner output contains only a
relative location, line, rule, category and SHA-256 fingerprint, never the
matched value. A history finding is an explicit audit result, not permission
to erase or rewrite history; revoke any credential through its issuer.

## Historical v0.9 validation — 2026-09-13 (Asia/Taipei)

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
