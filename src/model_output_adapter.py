"""Adapt rich Doctore probability predictions to the canonical model-output contract."""
from __future__ import annotations

from typing import Any, Mapping


_STATUS_MAP = {
    "validated": "validated",
    "provisional": "unknown",
    "degraded": "unknown",
}


def to_model_output_contract(
    prediction: Mapping[str, Any],
    *,
    market_id: str,
    competition: str,
    target_market: str,
    settlement_rules: str,
) -> dict[str, Any]:
    """Return a canonical ``doctore.model-output.v1`` document.

    ``provisional`` and ``degraded`` rich-pipeline states map to ``unknown`` so
    the decision validator blocks staking. Only a fully ``validated`` pipeline
    may enter the validated Kelly tier.
    """
    market = _mapping(prediction, "market")
    model = _mapping(prediction, "model")
    calibration = _mapping(prediction, "calibration")
    validation = _mapping(prediction, "validation")

    rich_status = str(calibration.get("status", "unknown"))
    status = _STATUS_MAP.get(rich_status, "unknown")
    probability_raw = _probability(calibration, "probability_selected_raw")
    probability_calibrated = _probability(calibration, "probability_selected_calibrated")

    sport = _required_string(prediction, "sport")
    market_type = _required_string(market, "market_type")
    period = _required_string(market, "period")
    line = market.get("line")

    domain = {
        "sport": sport,
        "competition": competition,
        "market_type": market_type,
        "target_market": target_market,
        "period": period,
        "line": line,
        "settlement_rules": settlement_rules,
    }

    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": _required_string(prediction, "event_id"),
        "market_id": _nonempty(market_id, "market_id"),
        "model_name": _required_string(model, "model_name"),
        "model_version": _required_string(model, "model_version"),
        "sport": sport,
        "competition": _nonempty(competition, "competition"),
        "market_type": market_type,
        "target_market": _nonempty(target_market, "target_market"),
        "period": period,
        "line": line,
        "settlement_rules": _nonempty(settlement_rules, "settlement_rules"),
        "selection": _required_string(market, "selection"),
        "probability_raw": probability_raw,
        "probability_calibrated": probability_calibrated,
        "calibration_status": status,
        "calibration_method": "other",
        "prediction_generated_at": _required_string(model, "prediction_generated_at"),
        "feature_cutoff_at": _required_string(model, "feature_cutoff_at"),
        "training_cutoff_at": _required_string(model, "training_cutoff_at"),
        "feature_schema_version": _required_string(model, "feature_schema_version"),
        "validation_domain": domain,
        "validation_window": _validation_window(validation),
        "validation_sample_size": _integer(validation, "sample_size"),
        "brier_score": _number(validation, "model_brier_score"),
        "log_loss": _number(validation, "model_log_loss"),
        "expected_calibration_error": _number(validation, "model_ece"),
        "model_artifact_sha256": _required_string(model, "model_artifact_sha256"),
        "calibration_artifact_sha256": _required_string(calibration, "calibration_artifact_sha256"),
        "notes": f"adapted_from={prediction.get('output_schema_version', 'unknown')}; rich_status={rich_status}",
    }


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(parent: Mapping[str, Any], key: str) -> str:
    return _nonempty(parent.get(key), key)


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _probability(parent: Mapping[str, Any], key: str) -> float:
    value = _number(parent, key)
    if not 0.0 < value < 1.0:
        raise ValueError(f"{key} must be in (0, 1)")
    return value


def _number(parent: Mapping[str, Any], key: str) -> float:
    value = parent.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _integer(parent: Mapping[str, Any], key: str) -> int:
    value = parent.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _validation_window(validation: Mapping[str, Any]) -> str:
    start = _required_string(validation, "validation_period_start")
    end = _required_string(validation, "validation_period_end")
    return f"{start}/{end}"
