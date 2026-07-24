"""Adapters between MCP contracts and the canonical Doctore decision core."""
from __future__ import annotations

from typing import Optional
import json

from bet_decision_core import evaluate_bet_decision
from model_output_adapter import to_model_output_contract

from .runtime import MAX_SNAPSHOT_AGE_MINUTES, minutes_since, resolve_artifact_path
from .schemas import (
    DecisionInput,
    EdgeAndStakeOutput,
    EvaluateOutput,
    LoadPredictionInput,
    LoadPredictionOutput,
    QualityGateInput,
    QualityGateOutput,
    schema_errors,
)


def run_decision(params: DecisionInput) -> dict:
    return evaluate_bet_decision(
        model_output=params.model_output,
        market_snapshot=params.market_snapshot,
        portfolio_state=params.portfolio_state,
        risk_policy=params.risk_policy,
        evaluated_at=params.evaluated_at,
        sport_context=params.sport_context,
    )


def check_data_quality(params: QualityGateInput) -> QualityGateOutput:
    reasons: list[str] = []
    age: Optional[float]
    try:
        age = minutes_since(params.snapshot_at)
    except (TypeError, ValueError) as exc:
        return QualityGateOutput(status="BLOCKED", reasons=[f"invalid snapshot_at: {exc}"], age_minutes=None)

    limit = params.max_age_minutes or MAX_SNAPSHOT_AGE_MINUTES
    if age < 0:
        reasons.append(f"snapshot timestamp is {-age:.1f} minutes in the future")
    elif age > limit:
        reasons.append(f"snapshot is {age:.1f} minutes old; limit is {limit:.1f}")

    if (params.reference_odds is None) != (params.current_odds is None):
        reasons.append("reference_odds and current_odds must be supplied together")
    elif params.reference_odds is not None and params.current_odds is not None:
        for selection, reference in params.reference_odds.items():
            if selection not in params.current_odds:
                reasons.append(f"current odds missing selection {selection!r}")
                continue
            current = params.current_odds[selection]
            if reference <= 1 or current <= 1:
                reasons.append(f"{selection!r}: decimal odds must be greater than 1")
                continue
            difference = abs(current - reference) / reference * 100
            if difference > params.contradiction_threshold_pct:
                reasons.append(
                    f"{selection!r}: reference {reference} vs current {current} "
                    f"({difference:.1f}% difference; limit {params.contradiction_threshold_pct:.1f}%)"
                )
    return QualityGateOutput(
        status="BLOCKED" if reasons else "PASS",
        reasons=reasons,
        age_minutes=round(age, 3),
    )


def load_model_prediction(params: LoadPredictionInput) -> LoadPredictionOutput:
    try:
        path = resolve_artifact_path(params.prediction_path)
        prediction = json.loads(path.read_text(encoding="utf-8"))
        canonical = to_model_output_contract(
            prediction,
            market_id=params.market_id,
            competition=params.competition,
            target_market=params.target_market,
            settlement_rules=params.settlement_rules,
        )
        errors = schema_errors("model", canonical)
        if errors:
            return LoadPredictionOutput(ok=False, error="; ".join(errors))
        return LoadPredictionOutput(ok=True, model_output=canonical)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LoadPredictionOutput(ok=False, error=str(exc))


def calculate_edge_and_stake(params: DecisionInput) -> EdgeAndStakeOutput:
    decision = run_decision(params)
    recommended = decision["staking"]["final_stake"] if decision["decision"] == "BET" else 0.0
    return EdgeAndStakeOutput(
        decision_id=decision["decision_id"],
        decision=decision["decision"],
        reason_codes=decision["reason_codes"],
        no_vig_probability=decision["market"]["no_vig_probability"],
        overround=decision["market"]["overround"],
        ev=decision["economics"]["ev"],
        edge_vs_market_pp=decision["economics"]["edge_vs_market_pp"],
        full_kelly=decision["economics"]["full_kelly"],
        recommended_stake=float(recommended or 0.0),
        staking=decision["staking"],
        human_approval_required=decision["human_approval_required"],
    )


def evaluate(params: DecisionInput) -> EvaluateOutput:
    decision = run_decision(params)
    recommended = decision["staking"]["final_stake"] if decision["decision"] == "BET" else 0.0
    return EvaluateOutput(decision_output=decision, recommended_stake=float(recommended or 0.0))
