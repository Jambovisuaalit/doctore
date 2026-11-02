"""Adapters between MCP contracts and the canonical Doctore decision core."""
from __future__ import annotations

from typing import Optional
import json

from .evidence_gates import classify_quote, verify_registry
from .runtime import MAX_SNAPSHOT_AGE_MINUTES, minutes_since, resolve_artifact_path
from bet_decision_core import evaluate_bet_decision
from model_output_adapter import to_model_output_contract
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


def _canonical_decision(params: DecisionInput) -> dict:
    context = params.sport_context
    if params.market_snapshot.get("sport") == "TENNIS":
        from .tennis_data import tennis_mode
        if tennis_mode() == "verified_prematch":
            from .tennis_verification import verified_context
            context = verified_context(params.market_snapshot, params.evaluated_at)
        else:
            context = {"research_only": True}
    return evaluate_bet_decision(
        model_output=params.model_output,
        market_snapshot=params.market_snapshot,
        portfolio_state=params.portfolio_state,
        risk_policy=params.risk_policy,
        evaluated_at=params.evaluated_at,
        sport_context=context,
    )


def run_decision(params: DecisionInput, *, ledger_rows=None, replay_at=None) -> dict:
    from . import risk_authority as authority
    if authority.mode() == "research":
        return _canonical_decision(params)
    from datetime import datetime, timezone
    from .ledger import log_lock, read_bet_rows
    now = datetime.now(timezone.utc)
    if ledger_rows is None:
        with log_lock():
            return run_decision(params, ledger_rows=read_bet_rows(), replay_at=replay_at)
    try:
        prepared, provenance = authority.prepare(params, ledger_rows, now)
        # Replay is internal approval comparison only, never a client mode or clock.
        prepared.evaluated_at = replay_at or now.isoformat()
        decision = _canonical_decision(prepared)
        decision = authority.finalize(decision, provenance, prepared.risk_policy["minimum_stake"], prepared.portfolio_state["stake_increment"])
        errors = schema_errors("decision", decision)
        if errors:
            raise authority.AuthorityError("D3_OUTPUT_INVALID")
        return decision
    except (ValueError, TypeError, KeyError, OSError) as exc:
        decision = _canonical_decision(params)
        decision["decision"] = "BLOCKED"
        decision["reason_codes"] = ["D3_AUTHORITY_BLOCKED"]
        decision["staking"]["final_stake"] = 0.0
        decision["staking"]["stake_fraction"] = 0.0
        reason = str(exc) if isinstance(exc, authority.AuthorityError) else "D3_INPUT_INVALID"
        decision["diagnostics"].append(reason)
        decision["audit"]["risk_authority"] = {"mode": "production", "error_code": reason}
        from .runtime import content_sha256
        decision["decision_id"] = content_sha256(decision)
        return decision


def check_data_quality(params: QualityGateInput) -> QualityGateOutput:
    reasons: list[str] = []
    age: Optional[float]
    try:
        age = minutes_since(params.snapshot_at)
    except (TypeError, ValueError) as exc:
        return QualityGateOutput(status="BLOCKED", reasons=[f"invalid snapshot_at: {exc}"], age_minutes=None)

    market_state = None
    if (params.last_update is None) != (params.commence_time is None):
        reasons.append("last_update and commence_time must be supplied together")
    elif params.last_update is not None:
        try:
            market_state = classify_quote(params.last_update, params.commence_time, live_verified=params.live_verified)
            if market_state != "PREMATCH":
                reasons.append(f"non-pregame market state: {market_state}")
        except (ValueError, TypeError) as exc:
            reasons.append(f"invalid market timestamps: {exc}")
    limit = params.max_age_minutes or MAX_SNAPSHOT_AGE_MINUTES
    from . import risk_authority as authority
    if authority.mode() == "production":
        from datetime import datetime, timezone
        try:
            policy, _ = authority._policy(datetime.now(timezone.utc))
            limit = min(limit, policy["risk_policy"]["freshness_seconds"]["market_snapshot"] / 60)
        except (ValueError, OSError, KeyError, TypeError):
            return QualityGateOutput(status="BLOCKED", reasons=["D3_AUTHORITY_BLOCKED"], age_minutes=None)

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
        market_state=market_state,
    )


def load_model_prediction(params: LoadPredictionInput) -> LoadPredictionOutput:
    try:
        path = resolve_artifact_path(params.prediction_path)
        prediction = json.loads(path.read_text(encoding="utf-8"))
        registry_fields = (
            params.registry_manifest_path, params.registry_calibration_path,
            params.registry_oos_path, params.registry_model_artifact_path,
            params.registry_calibrator_artifact_path,
        )
        if any(registry_fields):
            if not all(registry_fields):
                return LoadPredictionOutput(ok=False, error="INCOMPLETE_REGISTRY_EVIDENCE")
            manifest, calibration, oos = (
                json.loads(resolve_artifact_path(item).read_text(encoding="utf-8"))
                for item in registry_fields[:3]
            )
            errors = verify_registry(
                manifest, calibration, oos, prediction,
                model_path=resolve_artifact_path(registry_fields[3]),
                calibrator_path=resolve_artifact_path(registry_fields[4]),
            )
            if errors:
                return LoadPredictionOutput(ok=False, error="; ".join(errors))
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
        risk_authority=decision["audit"].get("risk_authority"),
        human_approval_required=decision["human_approval_required"],
    )


def evaluate(params: DecisionInput) -> EvaluateOutput:
    decision = run_decision(params)
    recommended = decision["staking"]["final_stake"] if decision["decision"] == "BET" else 0.0
    return EvaluateOutput(decision_output=decision, recommended_stake=float(recommended or 0.0))
