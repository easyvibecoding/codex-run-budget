---
name: usage-window
description: Report Codex usage for one requested time window and an explicit Task scope. Use for 5h, daily or weekly comparisons; do not default to full cross-task history or multiple windows.
---

# Scoped time-window usage

Resolve `PLUGIN_ROOT` as the installed plugin directory two levels above this
skill directory. Select one requested window; if unspecified, use 24h for the
current Task and state that scope:

```sh
python3 "$PLUGIN_ROOT/scripts/run_budget.py" report window --windows 24h
```

This uses the current `CODEX_THREAD_ID`. `--thread UUID_OR_LISTED_SELECTOR`
selects another Task. Missing/ambiguous scope must not silently become all Tasks.
Only for an explicit cross-Task request, add `--all-tasks` and an explicit
`--windows` or `--since`. Never add it for an ordinary "analyze my usage" request.
Set `--timezone` to the user's timezone for today/week/month. Windows overlap
and cannot be added; never assign account-wide quota changes to one Task/model.

Default caps: 20 transcript pages, 20 detail groups; missing/limited coverage is
not zero. Raise caps or select multiple windows only when requested. The command
saves the artifact and prints a short summary/link; return those without loading
full HTML/JSON into context. `--full` is an explicit diagnostic escape hatch, not
the normal workflow. Saved native quota is not refreshed by this command.

Invocation: `/skills` → `usage-window`, or `$usage-window`; no new native
`/usage-window` parser command is claimed.
