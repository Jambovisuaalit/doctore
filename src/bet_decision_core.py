"""Deterministic Doctore betting decision core."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import math

from jsonschema import Draft202012Validator, FormatChecker
from mlb_context import evaluate_mlb_context

ROOT = Path(__file__).resolve().parents[1]
FORMULA_VERSION = "doctore.bet-decision-core.v1"
SPORTS = {"MLB", "KBO", "NPB", "TENNIS", "SOCCER", "NBA", "WNBA", "NFL"}
SCHEMAS = {
    name: Draft202012Validator(
        json.loads((ROOT / path).read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    for name, path in {
        "model": "contracts/model-output.schema.json",
        "market": "contracts/market-snapshot.schema.json",
        "portfolio": "contracts/portfolio-state.schema.json",
        "policy": "contracts/risk-policy.schema.json",
        "decision": "contracts/decision-output.schema.json",
    }.items()
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def _safe_time(value: Any) -> str:
    try:
        _time(value)
        return value
    except (TypeError, ValueError):
        return "1970-01-01T00:00:00+00:00"


def _safe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _safe_num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 12)


def _errors(name: str, payload: Mapping[str, Any]) -> list[str]:
    items = sorted(
        SCHEMAS[name].iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return [
        f"{name}.{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in items
    ]


def _caps_none() -> dict[str, None]:
    return dict.fromkeys(
        ["kelly", "per_bet", "open", "daily", "league", "rolling_3d",
         "correlation", "available_balance"]
    )


def _base(model, market, portfolio, policy, evaluated_at, context):
    sport = market.get("sport") or model.get("sport")
    package = {
        "model": model, "market": market, "portfolio": portfolio,
        "policy": policy, "evaluated_at": evaluated_at,
        "context": context, "formula": FORMULA_VERSION,
    }
    return {
        "schema_version": "doctore.decision-output.v1",
        "decision_id": _hash(package),
        "evaluated_at": _safe_time(evaluated_at),
        "event_id": _safe_str(market.get("event_id") or model.get("event_id")),
        "market_id": _safe_str(market.get("market_id") or model.get("market_id")),
        "sport": sport if sport in SPORTS else None,
        "competition": _safe_str(market.get("competition") or model.get("competition")),
        "selection": _safe_str(market.get("selection") or model.get("selection")),
        "book": _safe_str(market.get("book")),
        "decimal_odds": _safe_num(market.get("decimal_odds")),
        "decision": "BLOCKED",
        "human_approval_required": True,
        "reason_codes": ["INPUT_SCHEMA_INVALID"],
        "diagnostics": [],
        "model": {
            "model_name": _safe_str(model.get("model_name")),
            "model_version": _safe_str(model.get("model_version")),
            "calibration_status": model.get("calibration_status")
            if model.get("calibration_status") in {"validated", "uncalibrated", "unknown"}
            else None,
            "probability_raw": _safe_num(model.get("probability_raw")),
            "probability_calibrated": _safe_num(model.get("probability_calibrated")),
            "probability_used_for_economics": None,
            "sizing_probability": None,
        },
        "market": dict.fromkeys(
            ["raw_implied_probability", "no_vig_probability", "market_sum", "overround"]
        ),
        "economics": dict.fromkeys([
            "break_even_probability", "ev", "edge_vs_break_even_pp",
            "edge_vs_market_pp", "break_even_odds", "minimum_qualifying_odds",
            "full_kelly",
        ]),
        "staking": {
            "currency": _safe_str(portfolio.get("currency")),
            "kelly_fraction": None, "provisional_stake": None,
            "final_stake": None, "stake_fraction": None,
            "binding_cap": None, "caps": _caps_none(),
        },
        "context": {
            "sport": sport if sport in SPORTS else None,
            "status": "NOT_APPLICABLE", "reason_codes": [],
        },
        "audit": {
            "model_output_sha256": _hash(model),
            "market_snapshot_sha256": _hash(market),
            "portfolio_state_sha256": _hash(portfolio),
            "risk_policy_sha256": _hash(policy),
            "sport_context_sha256": _hash(context) if context is not None else None,
            "formula_version": FORMULA_VERSION,
        },
    }


def _finish(output, decision, reasons, diagnostics=None):
    output["decision"] = decision
    output["reason_codes"] = list(dict.fromkeys(reasons)) or ["INPUT_SCHEMA_INVALID"]
    output["diagnostics"].extend(diagnostics or [])
    failures = _errors("decision", output)
    if failures:
        raise ValueError("invalid decision output: " + "; ".join(failures))
    return output


def _domain_errors(model, market):
    mismatches = []
    for key in (
        "event_id", "market_id", "sport", "competition", "market_type",
        "target_market", "period", "line", "settlement_rules", "selection",
    ):
        if model.get(key) != market.get(key):
            mismatches.append(key)
    domain = model.get("validation_domain", {})
    for key in (
        "sport", "competition", "market_type", "target_market",
        "period", "line", "settlement_rules",
    ):
        if domain.get(key) != market.get(key):
            mismatches.append(f"validation_domain.{key}")
    return list(dict.fromkeys(mismatches))


def _no_vig(market):
    selected = [
        item for item in market["outcomes"]
        if item["selection"] == market["selection"]
    ]
    if len(selected) != 1:
        raise ValueError("market selection must occur exactly once")
    if not math.isclose(
        selected[0]["decimal_odds"], market["decimal_odds"],
        rel_tol=0, abs_tol=1e-12,
    ):
        raise ValueError("selected outcome odds mismatch")
    implied = [1 / item["decimal_odds"] for item in market["outcomes"]]
    total = sum(implied)
    raw = 1 / market["decimal_odds"]
    return raw, raw / total, total, total - 1


def _floor(amount: float, increment: float) -> float:
    amount = Decimal(str(max(0, amount)))
    increment = Decimal(str(increment))
    units = (amount / increment).to_integral_value(rounding=ROUND_FLOOR)
    return float(units * increment)


def evaluate_bet_decision(
    *, model_output: Mapping[str, Any], market_snapshot: Mapping[str, Any],
    portfolio_state: Mapping[str, Any], risk_policy: Mapping[str, Any],
    evaluated_at: str, sport_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one schema-valid BET, WATCH, PASS, or BLOCKED document."""
    output = _base(
        model_output, market_snapshot, portfolio_state,
        risk_policy, evaluated_at, sport_context,
    )
    invalid = []
    for name, payload in (
        ("model", model_output), ("market", market_snapshot),
        ("portfolio", portfolio_state), ("policy", risk_policy),
    ):
        invalid.extend(_errors(name, payload))
    try:
        evaluated = _time(evaluated_at)
    except (TypeError, ValueError) as exc:
        invalid.append(f"evaluated_at: {exc}")
        evaluated = None
    drawdown = risk_policy.get("drawdown", {})
    if all(isinstance(drawdown.get(k), (int, float))
           for k in ("warning_fraction", "review_fraction", "pause_fraction")):
        if not (
            drawdown["warning_fraction"] <= drawdown["review_fraction"]
            <= drawdown["pause_fraction"]
        ):
            invalid.append("policy.drawdown must satisfy warning <= review <= pause")
    if invalid:
        return _finish(output, "BLOCKED", ["INPUT_SCHEMA_INVALID"], invalid)
    assert evaluated is not None

    blocked, diagnostics = [], []
    mismatch = _domain_errors(model_output, market_snapshot)
    if mismatch:
        if "event_id" in mismatch:
            blocked.append("EVENT_ID_MISMATCH")
        if "market_id" in mismatch:
            blocked.append("MARKET_ID_MISMATCH")
        if "selection" in mismatch:
            blocked.append("SELECTION_MISMATCH")
        if any(x not in {"event_id", "market_id", "selection"} for x in mismatch):
            blocked.append("DOMAIN_MISMATCH")
        diagnostics.append("mismatched fields: " + ", ".join(mismatch))
    if portfolio_state["league"] != market_snapshot["competition"]:
        blocked.append("DOMAIN_MISMATCH")
        diagnostics.append("portfolio league mismatch")
    if portfolio_state["correlation_group"] != market_snapshot.get("correlation_group"):
        blocked.append("DOMAIN_MISMATCH")
        diagnostics.append("portfolio correlation group mismatch")
    if risk_policy["block_unknown_correlation"] and not market_snapshot.get("correlation_group"):
        blocked.append("UNKNOWN_CORRELATION")
    if market_snapshot["market_status"] != "open":
        blocked.append("MARKET_NOT_OPEN")
    if _time(market_snapshot["event_start_at"]) <= evaluated:
        blocked.append("EVENT_ALREADY_STARTED")
    try:
        raw, fair, total, overround = _no_vig(market_snapshot)
    except ValueError as exc:
        blocked.append(
            "SELECTED_PRICE_MISMATCH" if "odds" in str(exc) else "MARKET_INCOMPLETE"
        )
        diagnostics.append(str(exc))
        raw = fair = total = overround = None
    output["market"].update({
        "raw_implied_probability": _round(raw),
        "no_vig_probability": _round(fair),
        "market_sum": _round(total), "overround": _round(overround),
    })

    freshness = risk_policy["freshness_seconds"]
    for code, value, maximum in (
        ("MARKET_SNAPSHOT_STALE", market_snapshot["captured_at"], freshness["market_snapshot"]),
        ("PORTFOLIO_STATE_STALE", portfolio_state["captured_at"], freshness["portfolio_state"]),
        ("MODEL_OUTPUT_STALE", model_output["prediction_generated_at"], freshness["model_output"]),
    ):
        age = (evaluated - _time(value)).total_seconds()
        if age < 0:
            blocked.append("TIMESTAMP_IN_FUTURE")
        elif age > maximum:
            blocked.append(code)
    feature = _time(model_output["feature_cutoff_at"])
    prediction = _time(model_output["prediction_generated_at"])
    training = _time(model_output["training_cutoff_at"])
    if feature > prediction:
        blocked.append("FEATURE_CUTOFF_AFTER_PREDICTION")
    if training > feature:
        blocked.append("TRAINING_CUTOFF_AFTER_FEATURES")
    status = model_output["calibration_status"]
    if status not in risk_policy["allowed_calibration_statuses"]:
        blocked.append("CALIBRATION_STATUS_NOT_ALLOWED")
    if status == "unknown":
        blocked.append("CALIBRATION_PROVENANCE_UNKNOWN")
    if blocked:
        return _finish(output, "BLOCKED", blocked, diagnostics)

    probability = (
        model_output["probability_calibrated"]
        if status == "validated" else model_output["probability_raw"]
    )
    if probability is None:
        return _finish(output, "BLOCKED", ["CALIBRATION_PROVENANCE_UNKNOWN"])
    probability = float(probability)
    weight = risk_policy["sizing_model_weight"][status]
    sizing_probability = fair + weight * (probability - fair)
    output["model"]["probability_used_for_economics"] = _round(probability)
    output["model"]["sizing_probability"] = _round(sizing_probability)

    if market_snapshot["sport"] == "MLB":
        context = (
            {"sport": "MLB", "status": "BLOCKED",
             "reason_codes": ["MLB_CONTEXT_MISSING"], "diagnostics": []}
            if sport_context is None
            else evaluate_mlb_context(
                sport_context, market_snapshot=market_snapshot,
                evaluated_at=evaluated_at, max_age_seconds=freshness["mlb_context"],
            )
        )
        output["context"] = {
            "sport": "MLB", "status": context["status"],
            "reason_codes": context["reason_codes"],
        }
        output["diagnostics"].extend(context.get("diagnostics", []))

    odds = market_snapshot["decimal_odds"]
    break_even = 1 / odds
    ev = probability * odds - 1
    edge_market = probability - fair
    full_kelly = max(0, (sizing_probability * odds - 1) / (odds - 1))
    output["economics"].update({
        "break_even_probability": _round(break_even),
        "ev": _round(ev),
        "edge_vs_break_even_pp": _round(probability - break_even),
        "edge_vs_market_pp": _round(edge_market),
        "break_even_odds": _round(1 / probability),
        "minimum_qualifying_odds": _round((1 + risk_policy["minimum_ev"]) / probability),
        "full_kelly": _round(full_kelly),
    })
    failed = []
    if ev < risk_policy["minimum_ev"]:
        failed += ["EV_BELOW_MINIMUM", "PRICE_BELOW_MINIMUM"]
    if edge_market < risk_policy["minimum_edge_probability_points"]:
        failed.append("EDGE_BELOW_MINIMUM")
    if failed:
        return _finish(output, "PASS", failed)
    if output["context"]["status"] == "BLOCKED":
        return _finish(output, "BLOCKED", output["context"]["reason_codes"])
    if output["context"]["status"] == "WATCH":
        return _finish(output, "WATCH", output["context"]["reason_codes"])

    drawdown_value = portfolio_state["drawdown_fraction"]
    if drawdown_value >= drawdown["pause_fraction"]:
        return _finish(output, "BLOCKED", ["DRAWDOWN_PAUSE"])
    if drawdown_value >= drawdown["review_fraction"]:
        return _finish(output, "WATCH", ["DRAWDOWN_REVIEW"])
    warn = drawdown_value >= drawdown["warning_fraction"]

    bankroll = portfolio_state["bankroll"]
    exposure = portfolio_state["exposures"]
    limits = risk_policy["caps"]
    fraction = risk_policy["kelly_fraction"][status]
    provisional = bankroll * full_kelly * fraction
    caps = {
        "kelly": provisional,
        "per_bet": bankroll * limits["max_stake_fraction_per_bet"],
        "open": max(0, bankroll * limits["max_open_exposure_fraction"] - exposure["open_amount"]),
        "daily": max(0, bankroll * limits["max_daily_turnover_fraction"] - exposure["daily_turnover_amount"]),
        "league": max(0, bankroll * limits["max_league_exposure_fraction"] - exposure["league_amount"]),
        "rolling_3d": max(0, bankroll * limits["max_rolling_3d_turnover_fraction"] - exposure["rolling_3d_turnover_amount"]),
        "correlation": max(0, bankroll * limits["max_correlation_group_fraction"] - exposure["correlation_group_amount"]),
        "available_balance": portfolio_state["available_balance"],
    }
    binding = min(caps, key=caps.get)
    stake = _floor(caps[binding], portfolio_state["stake_increment"])
    output["staking"].update({
        "kelly_fraction": _round(fraction),
        "provisional_stake": _round(provisional),
        "final_stake": _round(stake),
        "stake_fraction": _round(stake / bankroll),
        "binding_cap": binding,
        "caps": {key: _round(value) for key, value in caps.items()},
    })
    if min(value for key, value in caps.items() if key != "kelly") <= 0:
        return _finish(output, "BLOCKED", ["NO_RISK_CAPACITY"])
    if stake <= 0 or stake < risk_policy["minimum_stake"]:
        return _finish(output, "PASS", ["STAKE_BELOW_MINIMUM"])
    reasons = ["QUALIFIED"] + (["DRAWDOWN_WARNING"] if warn else [])
    return _finish(output, "BET", reasons)
