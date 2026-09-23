# Exact transcript audit

`audit` reads only the local JSONL files you select. It is an offline,
read-only diagnostic and does not require an active budget or modify the
Governor ledger. Use synthetic files in public examples:

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/synthetic-rollout.jsonl
```

Pass several paths to analyze one exact multi-page cohort. The report separates
per-response request usage from cumulative `token_count` snapshots; these
views must not be added together. It deduplicates response IDs and reports
counter decreases, missing or conflicting records, and unmatched tool events.
It also includes cached versus uncached input, the largest observed request,
tool/output sizes and spans, repeated input/result hashes, compactions, and
turn lifecycle evidence.

Repeated calls are investigation candidates. Polling, changed external state,
or required verification may justify them. Overlapping spans and waits are not
CPU time. Nested calls inside an exec wrapper are opaque. One transcript is not
the whole parent/child session tree; do not sum reports without verifying their
accounting scopes. Missing request records are unknown, not zero. No price or
savings is inferred.

The reader snapshots file size before parsing, caps each page at 256 MiB and an
audit at 4 GiB, and reports skipped oversized or incomplete records. A complete
final JSON record needs no trailing newline. Paths, prompts, tool arguments,
outputs, native response IDs, and custom names are omitted or hashed in output.
See [recent-task survey](SURVEY.md) for bounded discovery and
[dated audit validation](AUDIT_VALIDATION.md) for tested evidence.
