# Experimental paired Codex projects

Codex Run Budget can coordinate change reviews across **user-selected local
Codex projects**. Each pair is an independent edge: it has two exact project
roots, its own remote-`main` cursors, pending reviews, and one-to-one Task
bindings. A project can appear in several pairs, such as `web ↔ api` and
`api ↔ shared`. This can connect work on a larger system while the projects
remain separate in Codex; it does not create a parent project or a shared
budget across projects.

This feature is **experimental and opt-in**. A new named pair starts disabled,
and a fresh installation has the global experimental switch off. Enable both
the global switch and the desired pair. An existing single pair configured by
an earlier version remains enabled until its maintainer switches it off; its
private state and reviewed cursors are retained as the `default` pair.

## Configure the pair graph

The two paths must be distinct Git checkout roots registered as local Codex
projects. They need an `origin` with a `main` branch. Use the paths returned by
Codex's project list; aliases are resolved to the actual checkout. Run these
commands from a Run Budget checkout, or use `scripts/paired_review.py` inside
the installed plugin:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py pair --id web-api \
  /path/to/web /path/to/api
python3 plugins/codex-run-budget/scripts/paired_review.py pair --id api-shared \
  /path/to/api /path/to/shared
python3 plugins/codex-run-budget/scripts/paired_review.py pairs
python3 plugins/codex-run-budget/scripts/paired_review.py feature on
python3 plugins/codex-run-budget/scripts/paired_review.py enable web-api
python3 plugins/codex-run-budget/scripts/paired_review.py enable api-shared
```

`pair --id` baselines the two current remote `main` heads. It does not open a
Task or review earlier commits. Pair IDs are lowercase slugs and must be
unique; the same two roots cannot be registered twice in either order. The
plugin reads the local Codex project catalog at setup and stores no native
project IDs. If the project catalog is unavailable, registration stops without
changing existing pairs.

The configuration and state stay under `~/.codex/run-budget`. Named pairs use
`paired-review-pairs/<id>/`; the previous single pair keeps its existing files
at the root as `default`. Git mirrors are private to each pair. Project paths
and remotes are never committed to a repository.

## Switch or inspect the feature

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py feature status
python3 plugins/codex-run-budget/scripts/paired_review.py status
python3 plugins/codex-run-budget/scripts/paired_review.py --pair web-api status
python3 plugins/codex-run-budget/scripts/paired_review.py disable web-api
python3 plugins/codex-run-budget/scripts/paired_review.py feature off
```

`feature off` stops paired Stop decisions and scans for all pairs. `disable <id>`
stops only that edge. Neither command deletes configuration, pending
ranges, Task bindings, or cursors. Re-enable the pair and global switch to
resume from the retained state. Budget enforcement, ordinary reporting, and
the plugin's other hooks are unaffected. Run `pairs` to see which edges and
switches are active; do not infer the state from the presence of a config file.

## Task Stop behavior

The trusted `Stop` hook checks only the configured Git checkout or its
worktrees. It makes no network or model call. For a new cached remote-`main`
range, it asks the source Task to continue once and use Codex App's native
`create_thread` tool in the exact destination project. The source Task reads
the pair-specific prompt, reserves the range, records the receiving real
`threadId`, and pins the Task for sidebar visibility. The receiving Task
verifies the source remote and decides `alignment-needed`,
`no-alignment-needed`, or `blocked` from actual diffs and destination state.
Only an evidenced decision advances that pair's cursor.

The two Tasks are bound only within their pair. Their later Stops send short
summaries through the native `send_message_to_thread` tool to the same bound
counterpart. A relayed turn's Stop is suppressed so it does not echo back.
An uncertain create or send remains reserved and must be inspected before a
manual retry. When a source project belongs to several enabled pairs, a Stop
can present several independent pair instructions in one continuation; a Task
can therefore use tokens for each actual relay. There is no timer, heartbeat,
or background model polling.

Use `--pair <id>` before `prompt`, `reserve`, `dispatched`, `relay-sent`,
`relay-retry`, `resolve`, or `retry` to address one named edge. For example:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py --pair web-api prompt web
python3 plugins/codex-run-budget/scripts/paired_review.py --pair web-api scan
```

The existing `default` pair may omit `--pair default`. A receiving review Task
does not fan out into another new Task just because its project belongs to
another edge. User-started work in that project can trigger its other pairs.
No code is copied automatically and no budget policy crosses project roots.

## Remote-only changes and recovery

A push unseen by either configured checkout needs a later Task Stop or an
explicit `scan`. A manual scan fetches enabled pairs' remote `main` branches
into private mirrors and queues exact forward ranges. It does not start a
model or a Task:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py scan
python3 plugins/codex-run-budget/scripts/paired_review.py --pair web-api status
```

If creating a receiving Task is uncertain, inspect Codex for an existing
Task before `retry <source>`. If sending a relay is uncertain, inspect the
bound recipient before `relay-retry <source> <source-threadId> <turnId>`.
These commands can duplicate work if the first operation actually succeeded.
Failed fetches, non-forward updates, and blocked reviews do not advance a
cursor. Native Codex project and Task catalogs are experimental integration
surfaces; if an ID cannot be verified, keep the range pending.

This coordinator does not alter hook trust. A full plugin package or hook
definition change still needs the normal Codex review. The Run Budget and
Usage Reports repositories use the [specific review contract](CROSS_REPO_REVIEW.md)
as one example; other pairs follow their own `AGENTS.md` and project docs.
