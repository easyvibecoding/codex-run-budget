"""Read-only cache observations from already deduplicated native requests.

Settings changes are evidence about the request sequence, never a server-side
cache-miss diagnosis. Missing context and timestamp ties stay unclassified.
"""

from __future__ import annotations

from typing import Any

SETTINGS = ("model", "reasoning_effort", "service_tier")


def observe_cache(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize one exact report window without reading prompts or making calls."""
    input_tokens = sum(row["input_tokens"] for row in rows)
    cached_tokens = sum(row["cached_input_tokens"] for row in rows)
    result: dict[str, Any] = {
        "status": "observed" if rows else "no_observations",
        "requests": len(rows),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "read_share_percent": round(100 * cached_tokens / input_tokens, 2)
        if input_tokens else None,
        "requests_with_cache_read": sum(row["cached_input_tokens"] > 0 for row in rows),
        "requests_without_cache_read": sum(row["cached_input_tokens"] == 0 for row in rows),
        "adjacent_pairs": 0,
        "observed_setting_changes": {field: 0 for field in SETTINGS},
        "unresolved_setting_pairs": {field: 0 for field in SETTINGS},
        "interpretation": "local_observation_not_server_diagnostics",
    }
    previous: dict[str, dict[str, Any]] = {}
    ambiguous_at: dict[str, float] = {}
    for row in sorted(rows, key=lambda item: (item["observed_at"], item["thread_hash"])):
        thread = row["thread_hash"]
        if thread in ambiguous_at:
            if row["observed_at"] == ambiguous_at[thread]:
                continue
            ambiguous_at.pop(thread)
            previous[thread] = row
            continue
        prior = previous.get(thread)
        if prior is not None:
            # Equal timestamps do not establish request order. Do not compare
            # an ambiguous pair or bridge past it to a later request.
            if row["observed_at"] <= prior["observed_at"]:
                previous.pop(thread, None)
                ambiguous_at[thread] = row["observed_at"]
                continue
            result["adjacent_pairs"] += 1
            for field in SETTINGS:
                before = prior.get("context_status", {}).get(field)
                after = row.get("context_status", {}).get(field)
                if before != "observed" or after != "observed":
                    result["unresolved_setting_pairs"][field] += 1
                elif prior.get(field) != row.get(field):
                    result["observed_setting_changes"][field] += 1
        previous[thread] = row
    return result
