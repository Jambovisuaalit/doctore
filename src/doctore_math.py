"""Canonical mathematical utilities for Doctore Sports Intelligence."""

from __future__ import annotations

from collections.abc import Sequence
import math


def _validate_probability(probability: float, name: str = "probability") -> None:
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ValueError(f"{name} must be finite and strictly between 0 and 1")


def _validate_decimal_odds(decimal_odds: float) -> None:
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        raise ValueError("decimal_odds must be finite and greater than 1.0")


def implied_probability(decimal_odds: float) -> float:
    """Return the raw implied probability including bookmaker margin."""
    _validate_decimal_odds(decimal_odds)
    return 1.0 / decimal_odds


def no_vig_probabilities(decimal_odds: Sequence[float]) -> list[float]:
    """Normalize a complete mutually exclusive market proportionally."""
    if len(decimal_odds) < 2:
        raise ValueError("at least two outcomes are required")
    raw = [implied_probability(price) for price in decimal_odds]
    total = sum(raw)
    if total <= 0.0:
        raise ValueError("market implied-probability sum must be positive")
    return [value / total for value in raw]


def market_margin(decimal_odds: Sequence[float]) -> float:
    """Return the overround. Positive values represent bookmaker margin."""
    if len(decimal_odds) < 2:
        raise ValueError("at least two outcomes are required")
    return sum(implied_probability(price) for price in decimal_odds) - 1.0


def expected_value(model_probability: float, decimal_odds: float) -> float:
    """Return expected profit per unit staked."""
    _validate_probability(model_probability, "model_probability")
    _validate_decimal_odds(decimal_odds)
    return model_probability * decimal_odds - 1.0


def minimum_odds_for_ev(model_probability: float, target_ev: float) -> float:
    """Return the minimum decimal price required for a target EV."""
    _validate_probability(model_probability, "model_probability")
    if not math.isfinite(target_ev) or target_ev < 0.0:
        raise ValueError("target_ev must be finite and non-negative")
    return (1.0 + target_ev) / model_probability


def minimum_probability_for_ev(decimal_odds: float, target_ev: float) -> float:
    """Return the minimum model probability required for a target EV."""
    _validate_decimal_odds(decimal_odds)
    if not math.isfinite(target_ev) or target_ev < 0.0:
        raise ValueError("target_ev must be finite and non-negative")
    probability = (1.0 + target_ev) / decimal_odds
    if probability >= 1.0:
        raise ValueError("target EV is unattainable at the supplied odds")
    return probability


def full_kelly_fraction(sizing_probability: float, decimal_odds: float) -> float:
    """Return non-negative full Kelly as a bankroll fraction."""
    _validate_probability(sizing_probability, "sizing_probability")
    _validate_decimal_odds(decimal_odds)
    raw = (sizing_probability * decimal_odds - 1.0) / (decimal_odds - 1.0)
    return max(0.0, raw)


def shrunk_probability(
    model_probability: float,
    market_no_vig_probability: float,
    shrinkage_factor: float,
) -> float:
    """Shrink model edge toward the market baseline for stake sizing."""
    _validate_probability(model_probability, "model_probability")
    _validate_probability(market_no_vig_probability, "market_no_vig_probability")
    if not math.isfinite(shrinkage_factor) or not 0.0 <= shrinkage_factor <= 1.0:
        raise ValueError("shrinkage_factor must be between 0 and 1")
    return market_no_vig_probability + shrinkage_factor * (
        model_probability - market_no_vig_probability
    )


def raw_clv_probability_points(odds_taken: float, closing_odds: float) -> float:
    """Return raw implied-probability CLV; positive means the taken price improved."""
    return implied_probability(closing_odds) - implied_probability(odds_taken)


def price_clv(odds_taken: float, closing_odds: float) -> float:
    """Return multiplicative price CLV; positive means odds taken exceeded close."""
    _validate_decimal_odds(odds_taken)
    _validate_decimal_odds(closing_odds)
    return odds_taken / closing_odds - 1.0
