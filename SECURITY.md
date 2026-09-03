# Security policy

## Supported versions

Only the latest tagged release receives security fixes.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting for this repository. Do not
open a public issue containing an exploit, private transcript data, or local
filesystem paths.

## Data and trust model

The plugin runs local Python hook commands that Codex asks the user to review
and trust. It stores its SQLite ledger in `~/.codex/run-budget/` unless
`CODEX_RUN_BUDGET_HOME` is set.

The ledger stores session identifiers, numeric usage, event timestamps, and
SHA-256 hashes of transcript paths and tool inputs. It does not intentionally
store prompts, tool inputs, tool outputs, command text, or transcript content.

Hook enforcement is not a complete sandbox. Hosted tools and specialized tool
paths may bypass local tool hooks, and model calls are not directly intercepted
by the plugin. See the limitations section in the README before relying on it.
