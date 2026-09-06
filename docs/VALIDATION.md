# Validation evidence

## Reliability hardening — 2026-09-07, v0.3.0

The 44-test suite, validators, existing-ledger migration, installed hook review,
and real two-turn HALT validation are recorded in
[HARDENING.md](HARDENING.md#local-installed-evidence--2026-09-07).
The first turn recorded 52,072 observed tokens against 10k; the next turn used
zero model tokens and executed no tool. This preserves the next-boundary
guarantee, not a same-turn cap.

## Upgrade recovery and restart — 2026-09-06, v0.2.1

Incident: directly installing v0.2.0 removed the v0.1.1 cache while an existing
task still referenced its absolute hook path. PreToolUse and Stop then failed
before the Python hook could run. The operator disabled this plugin's hooks.

Recovery and observed validation:

- Restored the original v0.1.1 plugin tree from commit `c4b9a89`, comparing all
  11 tracked files against Git. No stub or alternate policy replaced old hooks.
- Re-enabled only this plugin's 11 previously disabled hook entries; preserved
  their trust hashes and verified all other configuration was unchanged.
- Ran `python3 scripts/update_plugin.py` to install v0.2.1. The actual installer
  removed old caches; the helper restored v0.1.1 and v0.2.0 before returning.
- Invoked PreToolUse and Stop through each of the three installed versions with
  isolated ungoverned state. All six invocations exited 0.
- Ran a fresh `codex exec --skip-git-repo-check --json` with read-only sandbox,
  the normal saved hook settings, and a `run-budget:status` prompt asking for one
  `pwd` call followed by `HOOK_RESTART_OK`. No hook trust bypass was used.
- The shell call succeeded, the expected final text arrived, and the process
  exited 0. Reported usage: 51,911 input, 25,728 cached input, 71 output tokens.
  No missing-hook error recurred. Unrelated existing feature/icon warnings were
  present. No budget was started, so this is a lifecycle recovery smoke test,
  not a new token-HALT measurement.

The helper mitigates the observed cache deletion; it does not change Codex's
cache manager or eliminate the install/restore interval. Other tasks should be
idle during updates. Backups remain available if installation is interrupted.
Hooks are enabled; this test did not restart the desktop app or other tasks.

## Automated suite

The dependency-free test suite covers transcript reconciliation, shared parent
and subagent accounting, token HALT, STEER thresholds, repeated-call HALT,
tool-output replacement, fail-closed behavior, privacy, and concurrent SQLite
admission.

```sh
python3 -m unittest discover -s tests -v
ruff check plugins/codex-run-budget/lib plugins/codex-run-budget/scripts tests scripts
python3 scripts/validate_repo.py
```

## Installed Codex test — 2026-09-03

Environment: Codex CLI on macOS, plugin installed from the repository's local
marketplace, hooks explicitly trusted for the test invocation.

Procedure:

1. Start a persisted Codex task with `tokens=10k`, `tools=2`.
2. Ask Codex to run one `pwd` command and return `OK`.
3. Inspect the local lineage ledger.
4. Resume the same task and ask for another command.

Observed result:

- The initial model request and one Bash call completed.
- Codex persisted the `token_count` total at turn completion, not before the
  Bash call. The Stop hook reconciled 47,507 observed tokens and changed the
  run to HALT against the 10,000-token ceiling.
- The next user turn was rejected by `UserPromptSubmit` before a model request:
  Codex reported zero input, output, and reasoning tokens, and no Bash call ran.
- The ledger contained `run_started`, `tool_admitted`, `tool_completed`,
  `usage_observed`, and `halt` events in that order.

This validates the advertised next-boundary circuit breaker and disproves a
stronger same-turn or zero-overshoot guarantee. The README reflects that
observed limitation.
