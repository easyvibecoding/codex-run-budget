"""Dated public credit scenarios, never billing or quota allocation.

The same fixed rate card drives documentation and counterfactual arithmetic.
No caller chooses a tariff from a plan enum, resolves historical Fast defaults,
or turns these numbers into an included-quota percentage.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from typing import Any

SPEED_SOURCE = "https://learn.chatgpt.com/docs/agent-configuration/speed"
PLAN_SOURCE = "https://learn.chatgpt.com/docs/pricing"
VERIFIED_ON = "2026-09-12"
REVIEW_AFTER_DAYS = 30
# Credits per million (non-cached input, cached input, output). Exact model IDs
# only: never assign a nearby model's rate to an unknown alias or Spark preview.
_RATES = {
    "gpt-6-astra": ("250", "25", "1250", "2.5"),
    "gpt-5.6-sol": ("100", "10", "500", "2.5"),
    "gpt-5.6-terra": ("50", "5", "300", "2.5"),
    "gpt-5.6-luna": ("5", "0.5", "30", "2.5"),
    "gpt-5.5": ("125", "12.5", "750", "2.5"),
    "gpt-5.4": ("62.5", "6.25", "375", "2"),
    "gpt-5.4-mini": ("18.75", "1.875", "113", None),
}


def pricing_context(*, as_of: date | None = None) -> dict[str, Any]:
    """Keep published mode/plan comparisons separate from measured consumption.

    No multiplier is assigned to a user's plan enum or historical requests.
    This is not a live price resolver. The review interval is a tool reminder,
    not an official validity period. It performs no network I/O.
    """
    return {
        "status": "dated_documentation_reference",
        "verified_on": VERIFIED_ON,
        "freshness": _freshness(as_of),
        "speed_source": SPEED_SOURCE,
        "plan_source": PLAN_SOURCE,
        "fast_credit_multipliers": [
            {"models": ["gpt-6-astra"], "multiplier": 2.5},
            {"models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"], "multiplier": 2.5},
            {"models": ["gpt-5.5"], "multiplier": 2.5},
            {"models": ["gpt-5.4"], "multiplier": 2},
        ],
        "published_pro_options": [
            {"label": "Pro 5x", "relative_to_plus": 5},
            {"label": "Pro 20x", "relative_to_plus": 20},
        ],
        "applies_to": "ChatGPT-credit Fast mode, when available for the selected model",
        "measured_charge": False,
        "token_rate_source": PLAN_SOURCE + "#token-rates",
        "token_rates": [
            {
                "model": model,
                "input_credits_per_million": rates[0],
                "cached_input_credits_per_million": rates[1],
                "output_credits_per_million": rates[2],
                "fast_multiplier": rates[3],
            }
            for model, rates in _RATES.items()
        ],
        "subscription_mechanism": {
            "included_quota_token_denominator": None,
            "shared_usage": ["Codex local", "Codex cloud", "ChatGPT Work"],
            "spark": "Separate research-preview quota; not Fast mode; no token rate here.",
            "credits": "Eligible credits can extend usage after included limits.",
            "message_ranges": "Illustrations, not fixed messages or tokens per quota window.",
            "active_turn": "May continue at a usage limit, subject to fair-use limits.",
            "workspace_controls": "Plan-dependent and separate from Platform API billing.",
        },
        "limitations": [
            "Reference verified on the stated date; rates and plan offerings can change.",
            "API Priority has separate pricing; it is not ChatGPT Fast-credit billing.",
            "Do not map a native plan enum to a Pro allowance option without direct evidence.",
            "Reasoning, model, context, caching and tools affect usage; no fixed effort rate.",
            "No historical request charge or quota percentage is calculated from this reference.",
            "The current rate card does not establish a historical tariff or account agreement.",
            "Legacy Enterprise and USD agreements may use different rate cards.",
            "Sol promotional pricing is documented at least through 2026-11-21; recheck sources.",
        ],
    }


def _freshness(as_of: date | None) -> dict[str, Any]:
    today = as_of or datetime.now(timezone.utc).date()
    age = (today - date.fromisoformat(VERIFIED_ON)).days
    return {
        "checked_as_of": today.isoformat(),
        "age_days": age,
        "status": "verification_after_as_of"
        if age < 0
        else "review_due"
        if age > REVIEW_AFTER_DAYS
        else "dated_reference",
        "review_after_days": REVIEW_AFTER_DAYS,
        "official_validity_period_known": False,
    }


def _tokens(row: dict[str, Any]) -> tuple[int, int, int] | None:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    if any(type(row.get(key)) is not int or not 0 <= row[key] <= 2**63 - 1 for key in keys):
        return None
    incoming, cached, outgoing, total = (row[key] for key in keys)
    if cached > incoming or total != incoming + outgoing:
        return None
    # There is no cache-write-specific rate established by this card. Do not
    # silently treat a different provider's cache-write usage as ordinary input.
    if type(row.get("cache_write_input_tokens", 0)) is not int:
        return None
    if row.get("cache_write_input_tokens", 0) != 0:
        return None
    reasoning = row.get("reasoning_output_tokens", 0)
    if type(reasoning) is not int or not 0 <= reasoning <= outgoing:
        return None
    return incoming - cached, cached, outgoing


def credit_scenarios(rows: list[dict[str, Any]], *, as_of: date | None = None) -> dict[str, Any]:
    """Reprice valid observed text tokens under a dated ChatGPT credit card.

    Standard/Fast columns use identical tokens, not a prediction that switching
    modes/models preserves work. This is always counterfactual, even when the
    transcript records a mode. Incomplete bases and unpriced models are excluded
    with coverage; absence is not a zero bill. Inputs are normalized audit rows.
    """
    results = []
    covered = 0
    excluded = 0
    standard_sum = Decimal(0)
    fast_sum = Decimal(0)
    all_fast_priced = True
    # Keep decimal arithmetic exact for bounded int64 token bases and sums.
    with localcontext() as context:
        context.prec = 50
        for row in rows:
            count = row.get("unique_responses")
            if type(count) is not int or not 0 < count <= 2**63 - 1:
                continue
            model = row.get("model")
            rates = _RATES.get(model) if isinstance(model, str) else None
            base = _tokens(row)
            status = "scenario_only"
            if rates is None:
                status = "model_rate_unavailable"
            elif base is None:
                status = "token_basis_unavailable"
            standard = fast = None
            if status == "scenario_only":
                assert rates is not None and base is not None
                amount = sum(
                    Decimal(tokens) * Decimal(rate) for tokens, rate in zip(base, rates[:3])
                ) / Decimal(1_000_000)
                standard = format(amount, "f")
                standard_sum += amount
                covered += count
                if rates[3] is not None:
                    fast_amount = amount * Decimal(rates[3])
                    fast = format(fast_amount, "f")
                    fast_sum += fast_amount
                else:
                    all_fast_priced = False
            else:
                excluded += count
            results.append(
                {
                    "thread_hash": row.get("thread_hash"),
                    "turn_hash": row.get("turn_hash"),
                    "model": model,
                    "reasoning_effort": row.get("reasoning_effort"),
                    "observed_fast_mode": row.get("fast_mode"),
                    "requests": count,
                    "status": status,
                    "standard_scenario_credits": standard,
                    "fast_scenario_credits": fast,
                }
            )
    return {
        "status": "counterfactual_partial" if covered else "unavailable",
        "unit": "ChatGPT credits, not USD or included-quota percentage",
        "reference": pricing_context(as_of=as_of),
        "billing_route_at_request": "not_established",
        "historical_rate_applicability": "not_established",
        "actual_charge_credits": None,
        "quota_percentage_points": None,
        "coverage": {"priced_requests": covered, "excluded_requests": excluded},
        "standard_scenario_credits": format(standard_sum, "f") if covered else None,
        "fast_scenario_credits": format(fast_sum, "f") if covered and all_fast_priced else None,
        "rows": results,
        "limitations": [
            "Counterfactual current-card text-token repricing, not measured or historical charges.",
            "Standard and Fast scenarios reuse the same priced token cohort; no mode is inferred.",
            "Excluded requests are not free; unknown Fast rates make the Fast total unknown.",
            "Input is split into uncached and cached input; reasoning is already inside output.",
            "No separate tool, image, retrieval, voice or agreement-specific charges are included.",
            "No USD conversion, Pro-tier inference, fixed effort factor or quota allocation.",
        ],
    }
