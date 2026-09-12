---
name: usage-task
description: Produce a compact usage report for the current or one explicitly selected Codex Task. Use for per-task tokens, model usage, or a requested Task tree; never default to cross-task history.
---

# Single-Task usage

Use the plugin's deterministic command. Resolve `PLUGIN_ROOT` as the installed
plugin directory two levels above this skill directory; do not guess a cache version.

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" report task
```

This selects `CODEX_THREAD_ID`, one 24h window, at most 20 pages and 20 detail
groups. If current identity is unavailable, run `report tasks --limit 10`, show
the native names and let the user choose; never fall back to all Tasks. An exact
UUID or listed selector can be supplied with `--thread`. Do not identify a Task
from its title alone when names are duplicated.

Only when descendants are requested, use `report tree --thread SELECTOR`.
For ownership without usage, use the `usage-agents` skill instead. A different
window can be selected with `--windows 5h` or `--windows 7d`; do not expand it
automatically to multiple windows.

The default command saves a private Markdown artifact and prints only a short
summary/link. Return that link and the requested finding. Do not read the entire
artifact, run `--full`, export large JSON into model context or start a new
analysis turn merely to announce it. Read a specific detail only if requested.
Native names/agent aliases can be sensitive; do not publish them externally.
Token evidence is not account quota allocation or a settled bill.

Invocation: `/skills` → `usage-task`, or `$usage-task` in a request. This is a
skill command, not a newly registered native `/usage-task` parser command.
