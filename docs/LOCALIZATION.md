# Human-output localization

Language processing belongs at the human-output interface, not inside accounting,
storage, control policy or transport. The same saved data can be rendered in a
different language without changing its meaning or numeric values.

| Surface | Language behavior |
| --- | --- |
| Automatic cards and Stop Markdown/HTML | Localized, including incomplete-data notices |
| Manual Task/window Markdown/HTML | Localized headings, labels, controls and caveats |
| CLI help, user errors and summaries | Localized when shown to a person |
| Workflow observation reports and meter/survey summaries | Localized labels; original evidence codes retained |
| JSON, database rows, event/status codes, flags and command names | Stable machine representation, not translated |
| Model/reasoning identifiers and native Task/agent names | Original data, never translated or guessed |
| Agent control instructions, skill instructions, developer scripts and docs | One canonical version, no runtime translation |
| Static plugin metadata and hook status metadata | One canonical version, no locale-specific duplicate plugins |

Supported languages are English, Traditional/Simplified Chinese, Japanese,
Korean, German, French, Spanish and Portuguese. Unsupported locale selections
fall back to English. Regional codes normalize to these language catalogs;
this is not a claim of a separate translation for every regional variant.

Human CLI routes resolve the saved Codex language once per operation. The existing
read-only `desktop.localeOverride` resolver is shared with automatic reports;
Auto uses host-language signals, not conversation content. See
[automatic report language](AUTO_REPORTS.md#report-language) for the limits of
that fallback and immutable existing cards. No preference is changed.

The `ReportText` interface accepts an explicit locale and an allowlisted catalog
domain. Renderers do not change process-wide locale, invoke a translation model
or fetch translations. Shared display primitives have one owner; missing domain
keys fall back to bundled English. Machine routes must not construct renderers
just to discard their output in favor of JSON.

Pure structured-output routes skip language discovery and catalogs. Workflow
observations retain their existing mixed-output contract: a changed observation
can save a human-readable Markdown report even with `--json`. Language is resolved
only when that real human artifact is written; the structured result and its
report path remain available. An unchanged JSON observation or a metadata-only
target listing does not pay for a discarded report render.

Likewise, a manual report saved as JSON keeps canonical file contents while its
short terminal confirmation is localized for the reader. `--format json --full`
without an output file and JSON Task/agent listings remain pure data routes and
skip catalogs entirely.

Only the small automatic-card catalog ships in the hook archive. The CLI,
manual-report and observation catalogs stay in the full plugin and are loaded
on demand. Catalog key/placeholder parity is checked at build/CI time, not on
every hook call. This avoids translating or loading unrelated content during
budget enforcement.

## Contributing strings

Add complete sentences with named placeholders, not concatenated translated
fragments. Keep stable data out of translation keys, escape dynamic values in
HTML/Markdown, and verify input JSON is unchanged after rendering every locale.
Add the same keys and placeholders to all nine catalogs. Use clearly fictional
example names and data in tests and documentation; never copy a private report
or transcript into the repository to demonstrate a translation.
