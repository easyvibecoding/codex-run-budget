# Paired repository review at Task Stop

Codex Run Budget can coordinate reviews between two **separate** Codex
projects. Its trusted `Stop` hook checks only Tasks from the configured Git
checkouts or their worktrees. The check is local and deterministic: it compares
each source's observed `refs/remotes/origin/main` with a private reviewed cursor.
When the source advances, it queues the exact SHA range and asks the already
running source Task to continue once. That Task uses Codex App's native tool to
open a read-only review Task in the **other** project and binds the two Tasks.
Later Stops in either bound Task send a concise summary to the same counterpart.
The receiving Task follows the
[shared contract](CROSS_REPO_REVIEW.md) and verifies the remote head before
settling the review.

This mechanism sees a push or fetch reflected in a configured checkout when a
Task from that repo reaches `Stop`. A remote-only update with no subsequent
paired Task is not noticed automatically. An unbound Task running without the
native Codex App `create_thread` tool leaves the event queued and reports it; it must
not substitute `codex exec`, which did not register as a visible project Task
in our local test. No code or budget policy is copied across projects.

## Configure two checkouts

Run from the Run Budget checkout, with both paths registered as distinct Codex
projects:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py pair \
  /path/to/codex-run-budget /path/to/codex-usage-reports
python3 plugins/codex-run-budget/scripts/paired_review.py status
```

`pair` takes the current remote `main` heads as baselines and does not create
retroactive Tasks. It writes private configuration, mirrors, cursors, and
review decisions under `~/.codex/run-budget`, never in either repository. The
Run Budget plugin's `Stop` hook must be enabled and trusted in Codex; its
publisher-signed runtime carries the logic without changing the hook command
or trust definition. If you move either checkout, update the private pair
configuration to the exact new Git roots before relying on the hook.

## Task dispatch and decision

On a changed source, the hook's one-time continuation instructs the source
Task to:

1. Read `prompt <source>` and reserve the exact SHA with
   `reserve <source> <head>`.
2. Use Codex App's native `create_thread` in the receiving project's Git
   worktree. The title is `Review counterpart changes: <source> <short SHA>`.
   If setup returns only `clientThreadId`, wait for a real `threadId`; verify
   the receiving repo and full source SHA before recording it. Do not open a
   second Task while creation is uncertain.
3. Run `dispatched <source> <head> <threadId>`. This binds the source and
   destination Task one-to-one, storing only hashed Task IDs. Pin the Task for
   sidebar visibility; unpinning currently
   removes it from the sidebar list.
4. Read the Task's evidenced `alignment-needed`, `no-alignment-needed`, or
   `blocked` conclusion. Run `resolve <source> <decision>` only for the first
   two. Keep blocked or unfinished work pending. If alignment is needed, the
   review Task names the destination changes and verification; implementation
   requires that Task's own authorization.

The local cursor advances only after an evidenced decision. Multiple commits
before resolution become the next bounded range. A `Stop` continuation is
one-shot per turn, and a reserved or dispatched range is not opened again.
The two projects keep independent data and controls; Usage Reports stays
report-only.

## Bound Task messages

After binding, a Task Stop reserves its turn and asks that Task to use Codex
App's native `send_message_to_thread` tool with a short factual summary. The
recipient is resolved from the native Task catalog using the stored hash; raw
Task IDs are not kept in the private state. After a confirmed send, run
`relay-sent <source-project> <source-threadId> <turnId>`. The counterpart's next
Stop is suppressed to prevent a message echo. A later independent turn can
send again. A new source `main` range is passed through the same bound Task,
not through a newly created Task. The receiving Task verifies the range and
reports its alignment decision back to the source Task.

The hook itself makes no network or model call. A bound Task's Stop may cause
one model continuation to send its summary, so this event-driven exchange
does use tokens when the Task actually stops. If sending is uncertain, the
reserved turn stays held; inspect the recipient before manual recovery.
If the message is confirmed absent, run
`relay-retry <source-project> <source-threadId> <turnId>` and let a later
independent turn relay again.

## Inspect and recover

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py status
python3 plugins/codex-run-budget/scripts/paired_review.py prompt codex-run-budget
```

A manual `scan` fetches both remote `main` branches into private mirrors and
queues changes even without a Task Stop. It does **not** wake a model or open a
Task; the next paired Task Stop can dispatch it to a new or already bound Task.
This is useful for
remote-only updates or after a network outage:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py scan
```

When a Task creation is uncertain, inspect Codex for an existing receiving
Task first. If no usable Task exists, explicitly allow retry and run a manual
scan, or let the next paired Task Stop detect the source again:

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py retry codex-run-budget
python3 plugins/codex-run-budget/scripts/paired_review.py scan
```

`retry` takes the **source** name and can cause a duplicate Task if an earlier
creation actually succeeded. Failed fetches and non-forward updates never
advance the cursor. Native Task catalog formats can change across Codex
versions; if an ID cannot be verified, keep the range pending.

This coordinator does not change hook trust settings. A full plugin package
update or hook definition change still requires normal Codex review.
