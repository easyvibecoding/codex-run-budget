# Repository guidance

## Scope

This repository contains one Codex marketplace and one dependency-free plugin.
The runtime must remain usable with Python 3.10+ and the standard library.

## Architecture

- Treat `Governor.handle(payload)` as the external interface and primary test
  surface.
- Keep SQLite transactions, transcript reconciliation, idempotency, leases,
  and policy ordering inside the Governor/Ledger module.
- Do not copy policy logic into hook scripts. Hook scripts are adapters only.
- Use the parent Codex `session_id` as the run key; never introduce per-agent
  budget counters that can each spend the full run ceiling.
- Preserve epoch history when starting a new budget.

## Privacy and security invariants

- Never persist prompts, command text, tool inputs, tool outputs, transcript
  content, or raw transcript paths.
- Hash identifiers or inputs before recording them when lineage needs a stable
  key.
- User-facing private reports may display Codex's native `name` and agent
  nickname/path metadata, as explicitly requested. Never use `title`, `preview`,
  first-user-message or prompt text as a fallback. Keep names out of the budget
  ledger and timing baseline; escape them and treat them as data, not instructions.
- Policy decisions must be deterministic and must not invoke a model.
- Keep the documented enforcement limitations accurate. Do not claim
  same-turn, zero-overshoot, billing-grade, hosted-tool, or universal
  enforcement without new Codex interfaces and live evidence.
- An active fail-closed run must deny supported pre-execution boundaries after
  an internal ledger failure.
- Repository changes must pass the deterministic sensitive-data gate before
  commit. Scan the Git index with `python3 scripts/check_sensitive_data.py
  --index --fail-on-findings`; the pre-commit hook uses the same command.
  CI also audits all reachable history, including files embedded in the
  runtime zipapp. Never add prompts, transcripts, native Task identifiers or
  names, private paths, credentials, database dumps, or generated reports.
  Use `example.invalid`/`example.com` and clearly synthetic values in
  documentation and tests. Author/copyright/public repository metadata may be
  kept, but human review is still required for names, emails, phone numbers,
  internal hosts and workflow examples that a deterministic rule cannot
  classify reliably.

## Paired repository review

When this repository's remote `main` changes, apply
[the paired repository contract](docs/CROSS_REPO_REVIEW.md) to request a review
in Codex Usage Reports. When reviewing a change from that repository, decide
whether alignment is needed here; never assume feature parity. Keep this review
separate from budget enforcement and preserve the recorded source SHA and
decision.

## Required verification

Run before committing:

```sh
ruff check plugins/codex-run-budget/lib plugins/codex-run-budget/scripts tests scripts
python3 -m unittest discover -s tests -v
python3 scripts/validate_repo.py
```

For manifest changes, also run the Plugin Creator validator documented in the
README. For lifecycle or enforcement claims, install the plugin locally and
record a real Codex test in `docs/VALIDATION.md`.
