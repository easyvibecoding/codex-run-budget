# Documentation

[Project README](../README.md) · [Changelog](../CHANGELOG.md) · [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md)

Codex Run Budget has one shared budget ledger and several independent reporting
and observation tools. Choose the guide for the action you want; a report or
observation does not automatically start or change a budget.

## Use the plugin

| Task | Guide |
| --- | --- |
| Start, inspect, halt, resume, or disable a shared budget | [Quick start](../README.md#quick-start) and [design](DESIGN.md) |
| Control and interpret parent/subagent turn cards and completion revisions | [Automatic receipts](AUTO_REPORTS.md) |
| Select Task, agent, tree, or time-window reports | [Scoped reports](REPORTS.md) |
| Read native quota, saved snapshots, local Task context, rates, and scenarios | [Native meter](METER.md) and [mechanics](METER_MECHANICS.md) |
| Select language for human-facing output | [Localization](LOCALIZATION.md) |

## Observe a workflow

| Task | Guide |
| --- | --- |
| Resolve exact Tasks, capture a bounded change snapshot, and use a cursor | [On-demand workflow observations](WORKFLOW_OBSERVATIONS.md) |
| Read a bounded recent local Task cohort | [Recent-task survey](SURVEY.md) |
| Interpret turn endings and interruptions | [Lifecycle evidence](LIFECYCLE.md) |
| Inspect one project's additional `codex exec` sessions | [Project exec activity](EXEC_ACTIVITY.md) |
| Audit exact local transcript files | [Exact transcript audit](AUDIT.md) and [dated validation](AUDIT_VALIDATION.md) |

## Install, update, and maintain

| Task | Guide |
| --- | --- |
| Understand the Governor, ledger, transaction order, and hook boundaries | [Design](DESIGN.md) |
| Review admission recovery, leases, and schema migration | [Reliability hardening](HARDENING.md) |
| Keep existing Tasks and hook trust safe across package changes | [Upgrade safety](UPGRADE_SAFETY.md) |
| Inspect signed runtime activation, Task pins, controls, and rollback | [Signed updates](SIGNED_UPDATES.md) |
| Check installed package version and native hook trust | [Update notices](UPDATE_NOTICES.md) |
| Reproduce current checks and read dated installed evidence | [Validation](VALIDATION.md) |
| Read dated survey migration experiments | [Survey validation](SURVEY_VALIDATION.md) |
| Review whether a change in the paired Usage Reports project needs alignment | [Paired repository review](CROSS_REPO_REVIEW.md) |
| Configure experimental multi-pair Task Stop detection, switches, and receiving Task dispatch | [Paired review automation](PAIRED_REVIEW_AUTOMATION.md) |

The historical validation files describe their recorded versions and dates.
They do not prove the state of a current installation. Check the live checkout,
installed plugin, native hook trust, and active signed runtime separately.
