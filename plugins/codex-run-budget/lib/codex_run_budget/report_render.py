"""Offline Markdown and printable HTML views of the same report schema."""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return "未觀測" if value is None else str(value)


def _number(value: Any) -> str:
    return f"{value:,}" if type(value) in (int, float) else _text(value)


def _short(value: Any) -> str:
    return str(value)[:12] if value else "未識別"


def _task(report, thread_hash):
    return report.get("task_catalog", {}).get(thread_hash, {}).get(
        "display_name"
    ) or "未命名任務 · " + _short(thread_hash)


def _parent(report, thread_hash):
    row = report.get("task_catalog", {}).get(thread_hash, {})
    if row.get("lineage_status") == "conflicting_parent_sources":
        return "父系資料衝突，未歸屬"
    if row.get("parent_hash"):
        parent = row.get("parent_name") or _task(report, row["parent_hash"])
        return "直屬 " + parent + "；主 Task " + (row.get("root_name") or "未觀測")
    return "主代理" if row.get("root_hash") == thread_hash else "未觀測"


def _time(value: Any) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else "未觀測"
    )


def _config(row: dict[str, Any]) -> str:
    fast = row.get("fast_mode")
    label = "開" if fast is True else "關" if fast is False else "未知"
    status = row.get("context_status", {})
    return (
        f"{row['model']} · 思考 {_text(row.get('reasoning_effort'))} "
        f"[{status.get('reasoning_effort', 'missing')}] · Fast {label} "
        f"[{status.get('fast_mode', 'missing')}] · tier {_text(row.get('service_tier'))} "
        f"· plan {_text(row.get('plan_type'))} [{status.get('plan_type', 'missing')}]"
    )


def _coverage(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    selection = coverage["selection"]
    flags = []
    if report["scope"].get("tree_selection_limited"):
        flags.append("代理樹已達數量／深度上限，非完整後代用量")
    if coverage["selection_limited"]:
        flags.append("已達選檔／容量上限")
    if coverage["evidence_limited"]:
        flags.append("部分證據缺漏或有衝突")
    if coverage["ambiguous_time_requests_excluded"]:
        flags.append(f"排除 {coverage['ambiguous_time_requests_excluded']} 筆時間不明請求")
    if coverage["native_history_limit_reached"]:
        flags.append("原生快照僅取最新 1,000 筆")
    missing = report["scope"]["selected_tasks_without_observations"]
    if missing:
        flags.append("指定 Task 無請求觀測：" + ", ".join(_task(report, h) for h in missing))
    return f"{selection['selected_files']} 個本機紀錄頁；僅代表已觀測範圍，非全帳號完整帳單。" + (
        "／".join(flags) + "。" if flags else ""
    )


def _native_lines(report: dict[str, Any]) -> list[str]:
    latest = report["native_latest"]
    if latest is None:
        return ["沒有已保存的原生快照；額度與訂閱未觀測，不代表零。"]
    subscription = latest.get("subscription") or {}
    lines = [
        f"保存時間 {_time(latest['captured_at'])}；距報告截止 "
        f"{_number(round(latest['age_at_report_end_seconds']))} 秒（不是即時讀取）。",
        f"訂閱 {_text(subscription.get('plan_type'))}；"
        f"原生一般用量許可 {_text(latest.get('ordinary_usage_allowed'))}。",
    ]
    for bucket in latest["limits"]:
        for window in bucket["windows"]:
            lines.append(
                f"{bucket['limit_id']}／{window['duration_minutes']} 分鐘："
                f"已用 {_text(window['used_percent'])}% · "
                f"剩餘 {_text(window['remaining_percent'])}% · "
                f"重設 {_time(window['resets_at'])}。"
            )
        credits = bucket.get("credits") or {}
        if credits.get("balance") is not None:
            lines.append(
                f"{bucket['limit_id']} credits 餘額 {_text(credits['balance'])}；"
                "與訂閱內含額度分開。"
            )
    return lines


def _delta_lines(window: dict[str, Any]) -> list[str]:
    native = window["native_quota"]
    comparison = native["comparison"]
    if comparison is None:
        return [f"窗口內 {native['snapshot_count']} 筆原生快照，無足夠前後對照。"]
    lines = [
        f"帳號快照子區間 {native['observed_since']} → {native['observed_until']}；"
        "不是整個報告窗口，也不能分攤到 Task。"
    ]
    for row in comparison["windows"]:
        lines.append(
            f"{row['limit_id']}／{row['duration_minutes']} 分鐘："
            f"已用變化 {_text(row['used_percentage_points'])} 百分點 "
            f"({row['status']}; {', '.join(row['issues']) or 'same observed window'})"
        )
    return lines


def _md(value: Any) -> str:
    return (
        escape(_text(value), quote=False)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("*", "&#42;")
        .replace("_", "&#95;")
        .replace("\n", " ")
    )


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_md(v) for v in row) + " |" for row in rows),
        ]
    )


def _window_summary(window: dict[str, Any]) -> list[Any]:
    usage = window["usage"] or {}
    scenario = window["credit_scenarios"]
    return [
        window["name"],
        len(window["tasks"]),
        _number(usage.get("unique_responses")),
        _number(usage.get("total_tokens")),
        _number(usage.get("cached_input_tokens")),
        _text(scenario["standard_scenario_credits"]),
        _text(scenario["fast_scenario_credits"]),
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Codex 用量報告",
        "",
        f"產生時間：{report['generated_at']} · 時區：{report['timezone']}",
        "",
        "範圍："
        + (
            "指定 Task（不自動包含子代理）"
            if report["scope"]["thread_hashes"]
            else "近期本機所有已觀測 Task"
        )
        + "。優先顯示 Codex 任務名稱／代理暱稱；缺漏不以提示詞補值。",
        "",
        _coverage(report),
        "",
        "## 時間窗口比較",
        "",
        "窗口採 [起點, 終點)，彼此重疊不可加總。沒有觀測不等於用量為零。",
        "",
        _md_table(
            [
                "窗口",
                "觀測 Task",
                "請求",
                "Token",
                "其中快取輸入",
                "Standard 情境 credits",
                "Fast 情境 credits",
            ],
            [_window_summary(w) for w in report["windows"]],
        ),
        "",
        "Credits 欄是同一批 Token 的費率情境估算，不是實際扣款或訂閱百分比。",
        "",
        "## 原生額度與訂閱（全帳號共享）",
        "",
        *(_md(v) for v in _native_lines(report)),
    ]
    for window in report["windows"]:
        lines += [
            "",
            f"## {window['name']} 明細",
            "",
            f"{window['since']} → {window['until']}",
            "",
            _md_table(
                [
                    "Task / 代理",
                    "所屬主 Task / 直屬代理",
                    "角色",
                    "請求",
                    "Token",
                    "未快取輸入",
                    "快取輸入",
                    "輸出",
                ],
                [
                    [
                        _task(report, r["thread_hash"]),
                        _parent(report, r["thread_hash"]),
                        r["role"],
                        _number(r["unique_responses"]),
                        _number(r["total_tokens"]),
                        _number(r["uncached_input_tokens"]),
                        _number(r["cached_input_tokens"]),
                        _number(r["output_tokens"]),
                    ]
                    for r in window["tasks"]
                ],
            ),
            "",
            "### 模型與當時設定",
            "",
            f"顯示 {len(window['contexts'])}／{window['context_detail_count']} 組，依 Token 排序。",
            "",
            _md_table(
                ["Task", "當時設定與證據狀態", "請求", "Token"],
                [
                    [
                        _task(report, r["thread_hash"]),
                        _config(r),
                        _number(r["unique_responses"]),
                        _number(r["total_tokens"]),
                    ]
                    for r in window["contexts"]
                ],
            ),
            "",
            "### 回合請求明細",
            "",
            f"顯示最新 {len(window['turns'])}／{window['turn_detail_count']} 組；"
            "未識別回合會合併成 unknown，並非已完成回合數。",
            "",
            _md_table(
                ["Task / 回合", "最後請求 UTC", "請求", "Token", "當時設定"],
                [
                    [
                        _task(report, r["thread_hash"]) + " / 回合 " + _short(r["turn_hash"]),
                        _time(r["last_observed_at"]),
                        _number(r["unique_responses"]),
                        _number(r["total_tokens"]),
                        " / ".join(_config(c) for c in r["contexts"]),
                    ]
                    for r in window["turns"]
                ],
            ),
            "",
            *(_md(v) for v in _delta_lines(window)),
        ]
    lines += [
        "",
        "## 證據與限制",
        "",
        "輸入已包含快取輸入；輸出已包含思考 Token，不要重複加總。歷史設定缺漏不以目前設定補值。",
        "情境估算可能排除未知模型或不支援的 Token 基礎；排除不代表免費。",
        "",
        _md_table(
            ["窗口", "可估價請求", "排除請求", "Fast 證據狀態"],
            [
                [
                    w["name"],
                    w["credit_scenarios"]["coverage"]["priced_requests"],
                    w["credit_scenarios"]["coverage"]["excluded_requests"],
                    str(w["metadata_coverage"]["fast_mode"]),
                ]
                for w in report["windows"]
            ],
        ),
        "",
        "費率查核日期：" + _md(report["pricing_reference"]["verified_on"]),
        "",
        "[官方 Codex 價格](https://learn.chatgpt.com/docs/pricing) · "
        "[Fast 模式](https://learn.chatgpt.com/docs/agent-configuration/speed)",
        "",
        "本報告不會改變預算、Hook、Task 狀態或額度；完整結構化證據可用 --format json 匯出。",
    ]
    return "\n".join(lines) + "\n"


def _table(headers: list[str], rows: list[tuple[str | None, list[Any]]]) -> str:
    head = "".join(f'<th scope="col">{escape(v)}</th>' for v in headers)
    body = "".join(
        (f'<tr data-task="{escape(task, quote=True)}">' if task else "<tr>")
        + "".join(
            ('<td class="value">' if re.fullmatch(r"[0-9][0-9,.]*", _text(v)) else "<td>")
            + escape(_text(v))
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


def render_html(report: dict[str, Any]) -> str:
    assets = Path(__file__).with_name("report_assets")
    script = (assets / "report.js").read_text(encoding="utf-8")
    style = (assets / "report.css").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    pieces = [
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        f"script-src &#39;sha256-{digest}&#39;; style-src &#39;unsafe-inline&#39;; "
        'base-uri &#39;none&#39;; form-action &#39;none&#39;">',
        f"<title>Codex 用量報告</title><style>{style}</style></head><body><main>",
        '<header><p class="eyebrow">CODEX / OBSERVED USAGE</p><h1>用量，有跡可循。</h1>',
        f"<p>{escape(report['generated_at'])} · {escape(report['timezone'])}</p></header>",
        '<p class="scope">'
        + (
            "指定 Task · 不自動包含子代理"
            if report["scope"]["thread_hashes"]
            else "近期本機所有已觀測 Task"
        )
        + "</p>",
        f'<p class="notice">{escape(_coverage(report))}</p>',
        '<section aria-labelledby="comparison"><h2 id="comparison">時間窗口比較</h2>',
        "<p>依請求紀錄時間計量 · 重疊窗口不可加總 · 未觀測 ≠ 零用量</p>",
        '<div class="legend"><span>未快取輸入</span><span>快取輸入</span>'
        "<span>輸出（含思考）</span></div>",
    ]
    maximum = max(((w["usage"] or {}).get("total_tokens", 0) for w in report["windows"]), default=0)
    for window in report["windows"]:
        usage = window["usage"] or {}
        segments = "".join(
            f'<span class="segment s{i}" style="width:'
            f'{usage.get(key, 0) / maximum * 100 if maximum else 0:.6f}%"></span>'
            for i, key in enumerate(
                ("uncached_input_tokens", "cached_input_tokens", "output_tokens")
            )
        )
        label = f"{window['name']}: {_number(usage.get('total_tokens'))} Token"
        pieces.append(
            f'<div class="bar-row"><span>{escape(window["name"])}</span>'
            f'<div class="track" role="img" aria-label="{escape(label)}">{segments}</div>'
            f'<span class="numeric">{escape(_number(usage.get("total_tokens")))}</span></div>'
        )
    pieces += [
        _table(
            ["窗口", "Task", "請求", "Token", "快取輸入", "Standard credits*", "Fast credits*"],
            [(None, _window_summary(w)) for w in report["windows"]],
        ),
        '<p class="caption">* 同一批 Token 的費率情境，'
        "不是實際扣款或訂閱額度百分比。</p></section>",
        '<section><h2>原生額度與訂閱</h2><p class="eyebrow">全帳號共享 · 保存快照</p>',
        *(f"<p>{escape(v)}</p>" for v in _native_lines(report)),
        "</section>",
        '<section><h2>Task 與回合明細</h2><div class="controls">',
        '<label>時間窗口<select id="window-picker">',
        *(
            f'<option value="{i}">{escape(w["name"])}</option>'
            for i, w in enumerate(report["windows"])
        ),
        '</select></label><label>明細 Task（不改變上方彙總）<select id="task-picker">',
        '<option value="">全部</option>',
    ]
    tasks = sorted({row["thread_hash"] for w in report["windows"] for row in w["tasks"]})
    pieces += [
        f'<option value="{escape(task)}">{escape(_task(report, task))}</option>' for task in tasks
    ]
    pieces += [
        '</select></label><button id="print-report" type="button">列印 / 存為 PDF</button>',
        '</div><p id="selection-status" role="status" aria-live="polite"></p>',
        "<noscript>JavaScript 未啟用：以下依序顯示全部窗口，篩選器不生效。</noscript>",
    ]
    for i, window in enumerate(report["windows"]):
        pieces += [
            f'<article data-window="{i}"><h3>{escape(window["name"])} · '
            f"{escape(window['since'])} → {escape(window['until'])}</h3>",
            _table(
                [
                    "Task / 代理",
                    "所屬主 Task / 直屬代理",
                    "角色",
                    "請求",
                    "Token",
                    "未快取輸入",
                    "快取輸入",
                    "輸出",
                ],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"]),
                            _parent(report, r["thread_hash"]),
                            r["role"],
                            _number(r["unique_responses"]),
                            _number(r["total_tokens"]),
                            _number(r["uncached_input_tokens"]),
                            _number(r["cached_input_tokens"]),
                            _number(r["output_tokens"]),
                        ],
                    )
                    for r in window["tasks"]
                ],
            ),
            "<h3>模型與當時設定</h3>",
            f"<p>顯示 {len(window['contexts'])}／{window['context_detail_count']} 組"
            "（依 Token 排序）。"
            "未知 Fast 不是關閉；plan 是鄰近觀測，不是每筆請求的扣款方案。</p>",
            _table(
                ["Task", "當時設定 · 證據狀態", "請求", "Token"],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"]),
                            _config(r),
                            _number(r["unique_responses"]),
                            _number(r["total_tokens"]),
                        ],
                    )
                    for r in window["contexts"]
                ],
            ),
            "<details><summary>展開回合請求明細</summary>",
            f"<p>最新 {len(window['turns'])}／{window['turn_detail_count']} 組。"
            "未識別回合合併呈現；這不是完成回合數。</p>",
            _table(
                ["Task / 回合", "最後請求 UTC", "請求", "Token", "當時設定"],
                [
                    (
                        r["thread_hash"],
                        [
                            _task(report, r["thread_hash"]) + " / 回合 " + _short(r["turn_hash"]),
                            _time(r["last_observed_at"]),
                            _number(r["unique_responses"]),
                            _number(r["total_tokens"]),
                            " / ".join(_config(c) for c in r["contexts"]),
                        ],
                    )
                    for r in window["turns"]
                ],
            ),
            "</details>",
            *(f'<p class="caption">{escape(v)}</p>' for v in _delta_lines(window)),
            '<p class="caption">情境估算覆蓋 '
            f"{window['credit_scenarios']['coverage']['priced_requests']} 筆請求，"
            f"排除 {window['credit_scenarios']['coverage']['excluded_requests']} 筆。"
            "排除不代表免費。</p>",
            "</article>",
        ]
    pieces += [
        "</section><footer><h2>如何讀這份報告</h2>",
        "<p>輸入包含快取；輸出包含思考，不能重複加總。歷史設定不以目前設定補值。"
        "Token 份額不能用來分攤帳號額度；Standard / Fast 情境沒有證明當時的實際扣款。</p>",
        "<p>任務名稱與代理暱稱來自原生中繼資料，可能含敏感資訊，分享前請檢查。"
        "ID 已雜湊；不使用提示詞、預覽或對話內容補名。報告不連網、"
        "不變更預算、Hook、Task 狀態或額度。</p>",
        "<p>費率查核日期："
        + escape(_text(report["pricing_reference"]["verified_on"]))
        + ' · <a href="https://learn.chatgpt.com/docs/pricing">官方價格</a> · '
        '<a href="https://learn.chatgpt.com/docs/agent-configuration/speed">Fast 說明</a></p>',
        f"</footer></main><script>{script}</script></body></html>",
    ]
    return "\n".join(pieces) + "\n"
