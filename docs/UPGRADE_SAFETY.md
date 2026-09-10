# Cache-independent hooks (v0.4.1)

## Failure and scope

An active task can retain a hook command naming a plugin-cache file. Replacing
or evicting that cache makes the command fail before its adapter can run. An
installer that restores the cache afterward still leaves an interruption window.
This is a lifecycle problem, not a reason to disable budget enforcement.

The fix applies to this plugin's new commands. It cannot change Codex's cache
lifecycle, protect unrelated plugins, or rewrite commands captured by old tasks.

## Runtime contract

The build script packages only the hook engine and SQL migration into a
deterministic, bounded archive. Audit/survey code does not enter the runtime.
Every hook command contains the bootstrap source and an exact SHA-256 identity;
the repository validator regenerates both artifacts and checks exact parity.

The bootstrap itself needs no cache file. It verifies a durable runtime under
`CODEX_RUN_BUDGET_HOME/runtimes` (default `~/.codex/run-budget/runtimes`). On first
use it may copy only a hash-matching archive from the installed plugin. Imports
and migration-resource reads use the already-verified bytes in memory, not a
second filesystem lookup that could execute replacement code.

Runtime files are immutable identities, never garbage-collected by the plugin.
A new release receives a different hash when hook-engine bytes change. An old
trusted command cannot silently select the latest cache version. Python and the
durable data directory must still be available; arbitrary disk loss is not a
promise this mechanism can cover.

If neither a valid durable runtime nor matching installed source exists,
PreToolUse returns a structured deny, UserPromptSubmit returns a block, and
other lifecycle hooks return `continue: false`, all with exit status zero.
In particular, Stop does not emit exit 2 or a retry decision. The failure path
does not modify ledger policy or mark an unknown run as successfully enforced.

## Updating and recovering

Use `python3 scripts/update_plugin.py` while tasks are idle during the one-time
migration. It keeps recovery copies outside the replaceable cache, invokes the
official installer, restores prior version directories, and prewarms validated
runtimes without executing plugin code. `--retain-only` creates a recovery copy
without installation. Neither mode changes trust or enabled state.

After reviewing the new hook commands, enable/trust them through Codex and start
a new task. Existing pre-v0.4.1 tasks must finish or restart because they still
hold the old pathname command. Do not remove retained caches while such tasks
remain active. Durable runtimes and backups are intentionally retained; manual
cleanup requires knowing that no active task references them.

## Verification

Automated tests execute the generated commands, remove their source cache,
exercise HALT, corrupt the durable copy, reject symlink targets, check old/new
hash isolation, and assert structured Stop failure when both copies are gone.
Updater tests cover installation failure and hostile replacement targets.
A separate real-Codex canary verifies one admitted command, cache eviction,
a refused second command under the tool ceiling, and normal turn completion.
See [the release evidence](SURVEY_VALIDATION.md) for the observed run.
