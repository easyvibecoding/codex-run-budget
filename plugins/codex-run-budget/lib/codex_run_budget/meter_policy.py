"""Dated public pricing context, never a billing or quota allocation engine."""

from __future__ import annotations

from typing import Any

SPEED_SOURCE = "https://learn.chatgpt.com/docs/agent-configuration/speed"
PLAN_SOURCE = "https://learn.chatgpt.com/docs/pricing"
VERIFIED_ON = "2026-09-12"


def pricing_context() -> dict[str, Any]:
    """Keep published mode/plan comparisons separate from measured consumption.

    No multiplier is assigned to a user's plan enum or historical requests.
    This intentionally is not a price resolver and performs no network I/O.
    """
    return {
        "status": "dated_documentation_reference",
        "verified_on": VERIFIED_ON,
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
        "limitations": [
            "Reference verified on the stated date; rates and plan offerings can change.",
            "API Priority has separate pricing; it is not ChatGPT Fast-credit billing.",
            "Do not map a native plan enum to a Pro allowance option without direct evidence.",
            "Reasoning, model, context, caching and tools affect usage; no fixed effort rate.",
            "No historical request charge or quota percentage is calculated from this reference.",
        ],
    }
