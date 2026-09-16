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

The separate first-prompt update checker fetches only this plugin's public
GitHub manifest, with a six-hour cache. No Task ID, project path, prompt, or usage
is sent. Its embedded command does not execute newly installed plugin code and
never changes native hook trust. Set `CODEX_PLUGIN_UPDATE_NOTICES=0` to disable
automatic checks. See [update notices](docs/UPDATE_NOTICES.md) for scope and limits.

## Repository secret and private-data gate

The repository includes a deterministic, standard-library scanner at
`scripts/check_sensitive_data.py`. It checks provider credential formats,
private-key armor, authenticated database URLs, private absolute paths,
high-signal Task/session identifiers, private network addresses, and private
contact/workflow fields in generated report or dump artifacts. It also opens
the bounded `runtime/hook.pyz` archive and scans its members. It does not treat
`token_count`, model/configuration keys, content hashes, public author or
copyright metadata, or `example.invalid`/`example.com` fixtures as secrets.
Human review remains necessary for semantic ownership and names.

Run these checks from the repository root:

```sh
python3 scripts/check_sensitive_data.py --worktree --fail-on-findings
python3 scripts/check_sensitive_data.py --index --fail-on-findings
python3 scripts/check_sensitive_data.py --history --fail-on-findings
```

The repository `.githooks/pre-commit` hook checks staged blobs, so a staged
file cannot be bypassed by leaving a different safe version in the worktree.
`.githooks/pre-push` and CI audit reachable history; CI uses a full checkout.
Enable the hooks locally with `git config core.hooksPath .githooks`. The gate
is defense in depth: `.gitignore` only reduces accidental adds and is not an
allowlist. Generated reports and dumps stay local and ignored. Scanner output
is redacted to relative path, line, rule, category, and a short SHA-256
fingerprint. If a real credential is ever found, revoke it at the issuer and
preserve the finding location; deleting the file does not remove it from Git
history.

Author identity, copyright, and public repository homepage content may be
committed when the author owns it. Any other real email, phone, host, account
identifier, Task name/ID, prompt, transcript, or workflow sample must be
removed or replaced with a clearly synthetic example before staging. The
scanner cannot reliably determine ownership or whether a name is sensitive;
reviewers must make that decision without pasting the original value into
issues, logs, or reports.

For documentation, use explicit synthetic values, for example:

```json
{
  "task_name": "Example Task",
  "account_email": "user@example.invalid",
  "api_key": "<EXAMPLE_API_KEY_NOT_A_SECRET>"
}
```

This illustrates redaction, not plugin configuration or real observed usage.
An `example` comment or filename does not exempt a real credential. Do not use
plausible provider-token prefixes for examples; recognized key formats remain
blocked. Binary media and the sensitivity of natural-language names require
manual review. Local Git hooks can be bypassed, and CI runs after a push; retain
the repository's native GitHub secret scanning and push protection as another
layer. None of these checks is a guarantee that every kind of private information
can be identified automatically.
