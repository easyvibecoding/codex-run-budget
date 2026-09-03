# Contributing

Contributions are welcome. Please keep the project dependency-free at runtime
and preserve the privacy rule: ledger records may contain identifiers, hashes,
counts, and policy decisions, but never prompt, command, tool-input, tool-output,
or transcript content.

Before opening a pull request, run:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate_repo.py
```

Behavior changes need tests at the Governor interface. Schema changes need an
idempotent migration and a compatibility test using the previous schema.
