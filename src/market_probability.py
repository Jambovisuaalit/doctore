"""Public canonical market-implied probability calculations."""
from __future__ import annotations

from typing import Any, Mapping
import math


def calculate_market_probabilities(market: Mapping[str, Any]) -> dict[str, float]:
    """Return selected raw implied probability, proportional no-vig fair probability, market sum and overround.

    The selected outcome must occur exactly once and its outcome price must match
    ``market['decimal_odds']``. The function is deterministic and has no I/O.
    """
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        raise ValueError("market outcomes must contain at least two prices")
    selection = market.get("selection")
    selected = [item for item in outcomes if item.get("selection") == selection]
    if len(selected) != 1:
        raise ValueError("market selection must occur exactly once")
    selected_odds = market.get("decimal_odds")
    if not isinstance(selected_odds, (int, float)) or isinstance(selected_odds, bool) or selected_odds <= 1:
        raise ValueError("selected decimal odds must be greater than 1")
    if not math.isclose(float(selected[0].get("decimal_odds")), float(selected_odds), rel_tol=0, abs_tol=1e-12):
        raise ValueError("selected outcome odds mismatch")
    implied: list[float] = []
    for item in outcomes:
        odds = item.get("decimal_odds")
        if not isinstance(odds, (int, float)) or isinstance(odds, bool) or odds <= 1:
            raise ValueError("all decimal odds must be greater than 1")
        implied.append(1 / float(odds))
    market_sum = sum(implied)
    raw = 1 / float(selected_odds)
    return {
        "raw_implied_probability": raw,
        "no_vig_probability": raw / market_sum,
        "market_sum": market_sum,
        "overround": market_sum - 1,
    }
