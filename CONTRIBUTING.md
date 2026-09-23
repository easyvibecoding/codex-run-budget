# Contributing

Contributions are welcome. Please keep the project dependency-free at runtime
and preserve the privacy rule: ledger records may contain identifiers, hashes,
counts, and policy decisions, but never prompt, command, tool-input, tool-output,
or transcript content.

Before opening a pull request, run:

```sh
ruff check plugins/codex-run-budget/lib plugins/codex-run-budget/scripts tests scripts
python3 -m unittest discover -s tests -v
python3 scripts/validate_repo.py
python3 scripts/check_sensitive_data.py --index --fail-on-findings
```

Behavior changes need tests at the Governor interface. Schema changes need an
idempotent migration and a compatibility test using the previous schema.
Use synthetic examples in documentation and tests. Keep the
[README](README.md) and [documentation index](docs/README.md) aligned with the
implemented command surface; dated validation claims need exact test and
installed-Codex evidence. A plugin manifest change also needs the Plugin
Creator validator described in [repository guidance](AGENTS.md).
