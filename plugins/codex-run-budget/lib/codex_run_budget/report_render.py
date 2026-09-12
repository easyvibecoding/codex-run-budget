"""Offline Markdown and printable HTML views of the same report schema.

The report payload is deliberately language-neutral.  Only this rendering
boundary receives a :class:`ReportText`; identifiers, status codes, model
names and native Task metadata remain data and are never translated.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any


def _labels(*, locale: str | None = None, text=None):
    """Return a report-domain text adapter without mutating global locale.

    Direct library callers retain the historical Traditional Chinese default;
    the CLI passes a live ``human_text("reports")`` adapter explicitly.
    """
    if text is not None:
        return text
    from .report_i18n import ReportText

    return ReportText(locale or "zh-Hant", domain="reports")


def _text(value: Any, labels) -> str:
    return labels("not_observed") if value is None else str(value)


def _number(value: Any, labels) -> str:
    if value is None:
        return labels("not_observed")
    if type(value) in (int, float):
        return labels.number(value)
    return str(value)


def _short(value: Any, labels) -> str:
    return str(value)[:12] if value else labels("unidentified")


def _task(report, thread_hash, labels):
    row = report.get("task_catalog", {}).get(thread_hash, {})
    name = row.get("display_name")
    # ``unnamed``/``unavailable`` are deterministic placeholders.  A name
    # supplied by Codex or agent metadata is private user data and must remain
    # byte-for-byte intact; never rewrite it by looking for a localized word.
    if name and row.get("name_source") not in ("unnamed", "unavailable"):
        return str(name)
    return labels("unnamed_task_hash", hash=_short(thread_hash, labels))


def _parent(report, thread_hash, labels):
    row = report.get("task_catalog", {}).get(thread_hash, {})
    if row.get("lineage_status") == "conflicting_parent_sources":
        return labels("parent_conflict")
    if row.get("parent_hash"):
        parent = row.get("parent_name") or _task(report, row["parent_hash"], labels)
        root = row.get("root_name") or labels("not_observed")
        return labels("direct_parent", parent=parent, root=root)
    return (
        labels("parent_agent")
        if row.get("root_hash") == thread_hash
        else labels("not_observed")
    )


def _time(value: Any, labels) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat()
        if value is not None
        else labels("not_observed")
    )


def _config(row: dict[str, Any], labels) -> str:
    fast = row.get("fast_mode")
    fast_label = (
        labels("fast_on")
        if fast is True
        else labels("fast_off")
        if fast is False
        else labels("fast_unknown")
    )
    status = row.get("context_status", {})
    return labels(
        "config_context",
        model=_text(row.get("model"), labels),
        effort=_text(row.get("reasoning_effort"), labels),
        effort_status=status.get("reasoning_effort", "missing"),
        fast=fast_label,
        fast_status=status.get("fast_mode", "missing"),
        tier=_text(row.get("service_tier"), labels),
        plan=_text(row.get("plan_type"), labels),
        plan_status=status.get("plan_type", "missing"),
    )


def _coverage(report: dict[str, Any], labels) -> str:
    coverage = report["coverage"]
    selection = coverage["selection"]
    flags = []
    if report["scope"].get("tree_selection_limited"):
        flags.append(labels("coverage_tree_limited"))
    if coverage["selection_limited"]:
        flags.append(labels("coverage_selection_limited"))
    if coverage["evidence_limited"]:
        flags.append(labels("coverage_evidence_limited"))
    if coverage["ambiguous_time_requests_excluded"]:
        flags.append(
            labels(
                "coverage_ambiguous_time",
                count=_number(coverage["ambiguous_time_requests_excluded"], labels),
            )
        )
    if coverage["native_history_limit_reached"]:
        flags.append(labels("coverage_native_history_limit"))
    missing = report["scope"]["selected_tasks_without_observations"]
    if missing:
        flags.append(
            labels(
                "coverage_missing_tasks",
                tasks=", ".join(_task(report, h, labels) for h in missing),
            )
        )
    return labels(
        "coverage_summary",
        selected_files=_number(selection["selected_files"], labels),
    ) + ("／".join(flags) + "。" if flags else "")


def _native_lines(report: dict[str, Any], labels) -> list[str]:
    latest = report["native_latest"]
    if latest is None:
        return [labels("no_native_snapshot")]
    subscription = latest.get("subscription") or {}
    lines = [
        labels(
            "native_saved",
            time=_time(latest["captured_at"], labels),
            seconds=_number(round(latest["age_at_report_end_seconds"]), labels),
        ),
        labels(
            "native_subscription",
            plan=_text(subscription.get("plan_type"), labels),
            allowed=_text(latest.get("ordinary_usage_allowed"), labels),
        ),
    ]
    for bucket in latest["limits"]:
        for window in bucket["windows"]:
            lines.append(
                labels(
                    "native_window",
                    limit=bucket["limit_id"],
                    duration=window["duration_minutes"],
                    used=_text(window.get("used_percent"), labels),
                    remaining=_text(window.get("remaining_percent"), labels),
                    reset=_time(window.get("resets_at"), labels),
                )
            )
        credits = bucket.get("credits") or {}
        if credits.get("balance") is not None:
            lines.append(
                labels(
                    "native_credits",
                    limit=bucket["limit_id"],
                    balance=_text(credits.get("balance"), labels),
                )
            )
    return lines


def _delta_lines(window: dict[str, Any], labels) -> list[str]:
    native = window["native_quota"]
    comparison = native["comparison"]
    if comparison is None:
        return [
            labels(
                "delta_no_compare",
                count=_number(native["snapshot_count"], labels),
            )
        ]
    lines = [
        labels(
            "delta_scope",
            since=native["observed_since"],
            until=native["observed_until"],
        )
    ]
    for row in comparison["windows"]:
        lines.append(
            labels(
                "delta_window",
                limit=row["limit_id"],
                duration=row["duration_minutes"],
                points=_text(row.get("used_percentage_points"), labels),
                status=row["status"],
                issues=", ".join(row["issues"]) or labels("same_observed_window"),
            )
        )
    return lines


def _md(value: Any, labels) -> str:
    return (
        escape(_text(value, labels), quote=False)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("*", "&#42;")
        .replace("_", "&#95;")
        .replace("\n", " ")
    )


def _md_table(headers: list[str], rows: list[list[Any]], labels) -> str:
    return "\n".join(
        [
            "| " + " | ".join(_md(v, labels) for v in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *(
                "| " + " | ".join(_md(v, labels) for v in row) + " |"
                for row in rows
            ),
        ]
    )


def _window_summary(window: dict[str, Any], labels) -> list[Any]:
    usage = window["usage"] or {}
    scenario = window["credit_scenarios"]
    return [
        window["name"],
        _number(len(window["tasks"]), labels),
        _number(usage.get("unique_responses"), labels),
        _number(usage.get("total_tokens"), labels),
        _number(usage.get("cached_input_tokens"), labels),
        _text(scenario["standard_scenario_credits"], labels),
        _text(scenario["fast_scenario_credits"], labels),
    ]


def render_markdown(
    report: dict[str, Any],
    *,
    locale: str | None = None,
    text=None,
) -> str:
    labels = _labels(locale=locale, text=text)
    selected_scope = (
        labels("scope_selected")
        if report["scope"]["thread_hashes"]
        else labels("scope_all")
    )
    lines = [
        labels("markdown_title"),
        "",
        labels(
            "generated_at",
            value=report["generated_at"],
            timezone=report["timezone"],
        ),
        "",
        labels("scope_prefix") + selected_scope + labels("scope_suffix"),
        "",
        _coverage(report, labels),
        "",
        labels("windows_heading"),
        "",
        labels("windows_note"),
        "",
        _md_table(
            [
                labels("column_window"),
                labels("column_observed_tasks"),
                labels("column_requests"),
                labels("column_tokens"),
                labels("column_cached_input"),
                labels("column_standard_credits"),
                labels("column_fast_credits"),
            ],
            [_window_summary(w, labels) for w in report["windows"]],
            labels,
        ),
        "",
        labels("credits_note"),
        "",
        labels("native_heading"),
        "",
        *(_md(v, labels) for v in _native_lines(report, labels)),
    ]
    for window in report["windows"]:
        lines += [
            "",
            labels("window_details_heading", name=window["name"]),
            "",
            window["since"] + " → " + window["until"],
            "",
            _md_table(
                [
                    labels("column_task_agent"),
                    labels("column_parent"),
                    labels("column_role"),
                    labels("column_requests"),
                    labels("column_tokens"),
                    labels("column_uncached_input"),
                    labels("column_cached_input"),
                    labels("column_output"),
                ],
                [
                    [
                        _task(report, r["thread_hash"], labels),
                        _parent(report, r["thread_hash"], labels),
                        r["role"],
                        _number(r["unique_responses"], labels),
                        _number(r["total_tokens"], labels),
                        _number(r["uncached_input_tokens"], labels),
                        _number(r["cached_input_tokens"], labels),
                        _number(r["output_tokens"], labels),
                    ]
                    for r in window["tasks"]
                ],
                labels,
            ),
            "",
            labels("model_heading"),
            "",
            labels(
                "model_caption",
                shown=_number(len(window["contexts"]), labels),
                total=_number(window["context_detail_count"], labels),
            ),
            "",
            _md_table(
                [
                    labels("column_task"),
                    labels("column_context_status"),
                    labels("column_requests"),
                    labels("column_tokens"),
                ],
                [
                    [
                        _task(report, r["thread_hash"], labels),
                        _config(r, labels),
                        _number(r["unique_responses"], labels),
                        _number(r["total_tokens"], labels),
                    ]
                    for r in window["contexts"]
                ],
                labels,
            ),
            "",
            labels("turns_heading"),
            "",
            labels(
                "turns_caption",
                shown=_number(len(window["turns"]), labels),
                total=_number(window["turn_detail_count"], labels),
            ),
            "",
            _md_table(
                [
                    labels("column_turn"),
                    labels("column_last_request"),
                    labels("column_requests"),
                    labels("column_tokens"),
                    labels("column_context"),
                ],
                [
                    [
                        _task(report, r["thread_hash"], labels)
                        + " / "
                        + labels("turn_number", value=_short(r["turn_hash"], labels)),
                        _time(r["last_observed_at"], labels),
                        _number(r["unique_responses"], labels),
                        _number(r["total_tokens"], labels),
                        " / ".join(_config(c, labels) for c in r["contexts"]),
                    ]
                    for r in window["turns"]
                ],
                labels,
            ),
            "",
            *(_md(v, labels) for v in _delta_lines(window, labels)),
        ]
    lines += [
        "",
        labels("evidence_heading"),
        "",
        labels("evidence_intro"),
        labels("evidence_scenario"),
        "",
        _md_table(
            [
                labels("column_window"),
                labels("column_priced_requests"),
                labels("column_excluded_requests"),
                labels("column_fast_evidence"),
            ],
            [
                [
                    w["name"],
                    w["credit_scenarios"]["coverage"]["priced_requests"],
                    w["credit_scenarios"]["coverage"]["excluded_requests"],
                    str(w["metadata_coverage"]["fast_mode"]),
                ]
                for w in report["windows"]
            ],
            labels,
        ),
        "",
            labels(
                "pricing_date",
                date=_md(report["pricing_reference"]["verified_on"], labels),
            ),
        "",
        labels("official_links"),
        "",
        labels("no_mutation"),
    ]
    return "\n".join(lines) + "\n"


def _table(headers: list[str], rows: list[tuple[str | None, list[Any]]], labels) -> str:
    head = "".join(f'<th scope="col">{escape(_text(v, labels))}</th>' for v in headers)
    body = "".join(
        (f'<tr data-task="{escape(task, quote=True)}">' if task else "<tr>")
        + "".join(
            (
                '<td class="value">'
                if re.fullmatch(r"[0-9][0-9,.]*", _text(v, labels))
                else "<td>"
            )
            + escape(_text(v, labels))
            + "</td>"
            for v in values
        )
        + "</tr>"
        for task, values in rows
    )
    return (
        f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _html_heading(value: Any) -> str:
    """Adapt a shared Markdown heading label for an HTML heading element.

    The report catalog intentionally shares heading strings between Markdown
    and HTML (for example ``## Time-window comparison``).  Markdown consumes
    the marker, while HTML already supplies its own semantic heading element;
    rendering the marker literally would expose ``##`` to readers.
    """
    return re.sub(r"^\s*#{1,6}\s*", "", str(value))


def render_html(
    report: dict[str, Any],
    *,
    locale: str | None = None,
    text=None,
) -> str:
    labels = _labels(locale=locale, text=text)
    assets = Path(__file__).with_name("report_assets")
    script = (assets / "report.js").read_text(encoding="utf-8")
    style = (assets / "report.css").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    selected_scope = (
        labels("scope_selected")
        if report["scope"]["thread_hashes"]
        else labels("scope_all")
    )
    generated = labels(
        "generated_at",
        value=report["generated_at"],
        timezone=report["timezone"],
    )
    scope = labels("scope_prefix") + selected_scope + labels("scope_suffix")
    status_template = labels(
        "status_template", window="{window}", task="{task}", rows="{rows}"
    )
    windows_heading = _html_heading(labels("windows_heading"))
    pieces = [
        "<!doctype html>"
        f'<html lang="{escape(labels.locale, quote=True)}">'
        "<head><meta charset=\"utf-8\">",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        f"script-src &#39;sha256-{digest}&#39;; style-src &#39;unsafe-inline&#39;; "
        'base-uri &#39;none&#39;; form-action &#39;none&#39;">',
        f"<title>{escape(labels('html_title'))}</title><style>{style}</style></head>",
        f'<body><main id="report-root" '
        f'data-status-template="{escape(status_template, quote=True)}" '
        f'data-status-empty="{escape(labels("status_empty"), quote=True)}">',
        f'<header><p class="eyebrow">{escape(labels("eyebrow"))}</p>'
        f'<h1>{escape(labels("html_heading"))}</h1>',
        f"<p>{escape(generated)}</p></header>",
        f'<p class="scope">{escape(scope)}</p>',
        f'<p class="notice">{escape(_coverage(report, labels))}</p>',
        f'<section aria-labelledby="comparison"><h2 id="comparison">{escape(windows_heading)}</h2>',
        f"<p>{escape(labels('html_windows_note'))}</p>",
        f'<div class="legend"><span>{escape(labels("legend_uncached"))}</span>'
        f'<span>{escape(labels("legend_cached"))}</span>'
        f'<span>{escape(labels("legend_output"))}</span></div>',
    ]
    maximum = max(
        ((w["usage"] or {}).get("total_tokens", 0) for w in report["windows"]),
        default=0,
    )
    for window in report["windows"]:
        usage = window["usage"] or {}
        segments = "".join(
            f'<span class="segment s{i}" style="width:'
            f'{usage.get(key, 0) / maximum * 100 if maximum else 0:.6f}%"></span>'
            for i, key in enumerate(
                ("uncached_input_tokens", "cached_input_tokens", "output_tokens")
            )
        )
        label = labels(
            "bar_aria",
            name=window["name"],
            tokens=_number(usage.get("total_tokens"), labels),
        )
        pieces.append(
            f'<div class="bar-row"><span>{escape(window["name"])}</span>'
            f'<div class="track" role="img" aria-label="{escape(label, quote=True)}">'
            f"{segments}</div>"
            f'<span class="numeric">'
            f'{escape(_number(usage.get("total_tokens"), labels))}</span></div>'
        )
    pieces += [
        _table(
            [
                labels("column_window"),
                labels("column_task"),
                labels("column_requests"),
                labels("column_tokens"),
                labels("column_cached_input"),
                labels("column_standard_credits"),
                labels("column_fast_credits"),
            ],
            [(None, _window_summary(w, labels)) for w in report["windows"]],
            labels,
        ),
        f'<p class="caption">{escape(labels("credits_note"))}</p></section>',
        f'<section><h2>{escape(_html_heading(labels("native_heading")))}</h2>'
        f'<p class="eyebrow">{escape(labels("native_subheading"))}</p>',
        *(f"<p>{escape(v)}</p>" for v in _native_lines(report, labels)),
        f'</section><section><h2>{escape(labels("task_details_heading"))}</h2>'
        '<div class="controls">',
        f'<label>{escape(labels("window_picker"))}<select id="window-picker">',
        *(
            f'<option value="{i}">{escape(w["name"])}</option>'
            for i, w in enumerate(report["windows"])
        ),
        f'</select></label><label>{escape(labels("task_picker"))}<select id="task-picker">',
        f'<option value="">{escape(labels("all_tasks"))}</option>',
    ]
    tasks = sorted({row["thread_hash"] for w in report["windows"] for row in w["tasks"]})
    pieces += [
        f'<option value="{escape(task, quote=True)}">{escape(_task(report, task, labels))}</option>'
        for task in tasks
    ]
    pieces += [
        f'</select></label><button id="print-report" type="button">'
        f'{escape(labels("print_button"))}</button>',
        "</div>",
        '<p id="selection-status" role="status" aria-live="polite"></p>',
        f'<noscript>{escape(labels("noscript"))}</noscript>',
    ]
    for i, window in enumerate(report["windows"]):
        article_heading = labels(
            "window_article_heading",
            name=window["name"],
            since=window["since"],
            until=window["until"],
        )
        model_caption = labels(
            "html_model_caption",
            shown=len(window["contexts"]),
            total=window["context_detail_count"],
        )
        turns_caption = labels(
            "html_turns_caption",
            shown=len(window["turns"]),
            total=window["turn_detail_count"],
        )
        scenario_coverage = labels(
            "scenario_coverage",
            priced=window["credit_scenarios"]["coverage"]["priced_requests"],
            excluded=window["credit_scenarios"]["coverage"]["excluded_requests"],
        )
        pieces += [
            f'<article data-window="{i}"><h3>{escape(article_heading)}</h3>',
            _table(
                [
                    labels("column_task_agent"),
                    labels("column_parent"),
                    labels("column_role"),
                    labels("column_requests"),
                    labels("column_tokens"),
                    labels("column_uncached_input"),
                    labels("column_cached_input"),
                    labels("column_output"),
                ],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"], labels),
                            _parent(report, r["thread_hash"], labels),
                            r["role"],
                            _number(r["unique_responses"], labels),
                            _number(r["total_tokens"], labels),
                            _number(r["uncached_input_tokens"], labels),
                            _number(r["cached_input_tokens"], labels),
                            _number(r["output_tokens"], labels),
                        ],
                    )
                    for r in window["tasks"]
                ],
                labels,
            ),
            f'<h3>{escape(_html_heading(labels("model_heading")))}</h3>',
            f'<p>{escape(model_caption)} '
            f'{escape(labels("html_model_note"))}</p>',
            _table(
                [
                    labels("column_task"),
                    labels("column_context_status"),
                    labels("column_requests"),
                    labels("column_tokens"),
                ],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"], labels),
                            _config(r, labels),
                            _number(r["unique_responses"], labels),
                            _number(r["total_tokens"], labels),
                        ],
                    )
                    for r in window["contexts"]
                ],
                labels,
            ),
            f'<details><summary>{escape(labels("turns_summary"))}</summary>',
            f'<p>{escape(turns_caption)}</p>',
            _table(
                [
                    labels("column_turn"),
                    labels("column_last_request"),
                    labels("column_requests"),
                    labels("column_tokens"),
                    labels("column_context"),
                ],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"], labels)
                            + " / "
                            + labels("turn_number", value=_short(r["turn_hash"], labels)),
                            _time(r["last_observed_at"], labels),
                            _number(r["unique_responses"], labels),
                            _number(r["total_tokens"], labels),
                            " / ".join(_config(c, labels) for c in r["contexts"]),
                        ],
                    )
                    for r in window["turns"]
                ],
                labels,
            ),
            "</details>",
            *(f'<p class="caption">{escape(v)}</p>' for v in _delta_lines(window, labels)),
            f'<p class="caption">{escape(scenario_coverage)}</p>',
            "</article>",
        ]
    pricing_label = labels(
        "pricing_date",
        date=_text(report["pricing_reference"]["verified_on"], labels),
    )
    pieces += [
        f'</section><footer><h2>{escape(_html_heading(labels("evidence_heading")))}</h2>',
        f'<p>{escape(labels("html_evidence_intro"))}</p>',
        f'<p>{escape(labels("html_sensitive_note"))}</p>',
        f'<p>{escape(pricing_label)} · '
        '<a href="https://learn.chatgpt.com/docs/pricing">'
        f'{escape(labels("official_price"))}</a> · '
        f'<a href="https://learn.chatgpt.com/docs/agent-configuration/speed">{escape(labels("fast_link"))}</a></p>',
        f'</footer></main><script>{script}</script></body></html>',
    ]
    return "\n".join(pieces) + "\n"
