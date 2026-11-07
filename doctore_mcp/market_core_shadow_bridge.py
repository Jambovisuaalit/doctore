"""Read-only market-core parity adapter; never authorize a placement.

This adapter deliberately imports the existing canonical engine. It adds no
independent probability, no-vig, EV, Kelly, or staking calculations.
"""
from __future__ import annotations

from typing import Any, Mapping
import hashlib
import json

from bet_decision_core import evaluate_bet_decision


def _sha(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_shadow_canonical(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    """Compute canonical decision for research only; preserve all original IDs."""
    required = ("model_output", "market_snapshot", "portfolio_state", "risk_policy", "evaluated_at")
    missing = [key for key in required if key not in evaluation]
    if missing:
        raise ValueError("MISSING_CANONICAL_INPUT:" + ",".join(missing))
    model = evaluation["model_output"]
    market = evaluation["market_snapshot"]
    if not isinstance(model, dict) or not isinstance(market, dict):
        raise ValueError("INVALID_CANONICAL_INPUT")
    if model.get("event_id") != market.get("event_id") or model.get("market_id") != market.get("market_id"):
        raise ValueError("CANONICAL_IDENTITY_MISMATCH")
    decision = evaluate_bet_decision(
        model_output=model,
        market_snapshot=market,
        portfolio_state=evaluation["portfolio_state"],
        risk_policy=evaluation["risk_policy"],
        evaluated_at=evaluation["evaluated_at"],
        sport_context=evaluation.get("sport_context"),
    )
    return {
        "schema_version": "doctore.market-core-shadow-parity.v1",
        "mode": "SHADOW_ONLY",
        "execution_authorized": False,
        "recommended_stake_eur": 0.0,
        "canonical_decision": decision,
        "canonical_decision_id": decision["decision_id"],
        "canonical_output_sha256": _sha(decision),
        "canonical_inputs_sha256": _sha(dict(evaluation)),
        "reason_codes": ["SHADOW_NOT_EXECUTABLE", "NO_INDEPENDENT_PRODUCTION_EVIDENCE"],
    }
