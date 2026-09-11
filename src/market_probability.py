"""Public canonical market-implied probability calculations."""
from __future__ import annotations

from typing import Any, Mapping
import math


_SOCCER_REGULATION_RULE = "soccer_90min_including_stoppage_no_extra_time_v1"
_BASEBALL_ACTION_RULE = "action_including_extra_innings"
_BASEBALL_FULL_GAME_RULE = "full_game_including_extra_innings"
_BASKETBALL_FULL_GAME_RULE = "full_game_including_overtime"


def _half_line(value: Any) -> bool:
    """Return true only for finite x.5 lines where an integer-score push is impossible."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    if not math.isfinite(number):
        return False
    doubled = number * 2
    return math.isclose(doubled, round(doubled), abs_tol=1e-9) and abs(round(doubled)) % 2 == 1


def _require_outcome_count(market: Mapping[str, Any], count: int, label: str) -> None:
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != count:
        raise ValueError(f"payoff semantics unsupported: {label} requires exactly {count} outcomes")


def _require_over_under(market: Mapping[str, Any]) -> None:
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        raise ValueError("payoff semantics unsupported: total requires exactly two outcomes")
    names = {str(item.get("selection") or "").casefold() for item in outcomes}
    if names != {"over", "under"}:
        raise ValueError("payoff semantics unsupported: total outcomes must be over/under")


def _validate_canonical_payoff_semantics(market: Mapping[str, Any]) -> None:
    """Fail closed when the binary/no-vig economics cannot represent settlement payoffs.

    The current decision core models one win probability and one decimal price. It
    therefore cannot price explicit push, half-win/half-loss, or material void
    states. This gate applies only to canonical Doctore market snapshots; the
    public helper remains usable for generic price-vector research.
    """
    if market.get("schema_version") != "doctore.market-snapshot.v1":
        return

    sport = market.get("sport")
    market_type = market.get("market_type")
    line = market.get("line")
    settlement = market.get("settlement_rules")

    if sport == "MLB":
        if market_type == "moneyline" and line is None and settlement == _BASEBALL_ACTION_RULE:
            _require_outcome_count(market, 2, "MLB moneyline")
            return
        if market_type in {"run_line", "total"} and _half_line(line) and settlement == _BASEBALL_FULL_GAME_RULE:
            if market_type == "total":
                _require_over_under(market)
            else:
                _require_outcome_count(market, 2, "MLB run line")
            return
        raise ValueError("payoff semantics unsupported: MLB market has push or unverified payoff states")

    if sport in {"KBO", "NPB"}:
        if market_type == "moneyline":
            raise ValueError("payoff semantics unsupported: KBO/NPB tie probability is not modeled")
        if market_type in {"run_line", "total"} and _half_line(line) and settlement == _BASEBALL_FULL_GAME_RULE:
            if market_type == "total":
                _require_over_under(market)
            else:
                _require_outcome_count(market, 2, f"{sport} run line")
            return
        raise ValueError(f"payoff semantics unsupported: {sport} market has push or unverified payoff states")

    if sport in {"NBA", "WNBA"}:
        if market_type == "moneyline" and line is None and settlement == _BASKETBALL_FULL_GAME_RULE:
            _require_outcome_count(market, 2, f"{sport} moneyline")
            return
        if market_type in {"spread", "total"} and _half_line(line) and settlement == _BASKETBALL_FULL_GAME_RULE:
            if market_type == "total":
                _require_over_under(market)
            else:
                _require_outcome_count(market, 2, f"{sport} spread")
            return
        raise ValueError(f"payoff semantics unsupported: {sport} market has push or unverified payoff states")

    if sport == "SOCCER":
        if market_type == "1x2" and line is None and settlement == _SOCCER_REGULATION_RULE:
            _require_outcome_count(market, 3, "soccer 1X2")
            selections = {str(item.get("selection") or "").casefold() for item in market["outcomes"]}
            if "draw" not in selections:
                raise ValueError("payoff semantics unsupported: soccer 1X2 requires a draw outcome")
            return
        if market_type == "total" and _half_line(line) and settlement == _SOCCER_REGULATION_RULE:
            _require_over_under(market)
            return
        raise ValueError("payoff semantics unsupported: soccer push/Asian/handicap payoff is not modeled")

    if sport == "TENNIS":
        raise ValueError("payoff semantics unsupported: tennis retirement/void probability is not modeled")

    raise ValueError(f"payoff semantics unsupported: {sport or 'unknown sport'} is not approved for binary economics")


def calculate_market_probabilities(market: Mapping[str, Any]) -> dict[str, float]:
    """Return selected raw implied probability, proportional no-vig fair probability, market sum and overround.

    The selected outcome must occur exactly once and its outcome price must match
    ``market['decimal_odds']``. Canonical Doctore snapshots additionally must have
    payoff semantics representable by the current binary economics model. The
    function is deterministic and has no I/O.
    """
    _validate_canonical_payoff_semantics(market)

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
