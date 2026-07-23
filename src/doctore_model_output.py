"""Map Doctore probability-pipeline reports to the canonical model-output contract."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping

_CANONICAL_SCHEMA_VERSION = "doctore.model-output.v1"
_KNOWN_PIPELINE_STATUSES = {"validated", "provisional", "degraded"}
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class ModelOutputMappingError(ValueError):
    """Raised when a pipeline report cannot be mapped without inventing data."""


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelOutputMappingError(f"{path} must be an object")
    return value


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelOutputMappingError(f"{path} must be a non-empty string")
    return value.strip()


def _probability(value: Any, path: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ModelOutputMappingError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result < 1.0:
        raise ModelOutputMappingError(f"{path} must be strictly between 0 and 1")
    return result


def _finite_number(value: Any, path: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ModelOutputMappingError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ModelOutputMappingError(f"{path} must be finite")
    return result


def _optional_metric(
    value: Any,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def _optional_sample_size(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _optional_sha256(value: Any) -> str | None:
    if isinstance(value, str) and _SHA256_RE.fullmatch(value):
        return value.lower()
    return None


def _validated_evidence(
    *,
    pipeline_status: str,
    calibration: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> bool:
    if pipeline_status != "validated":
        return False

    sample_size = _optional_sample_size(validation.get("sample_size"))
    model_brier = _optional_metric(validation.get("model_brier_score"), maximum=1.0)
    market_brier = _optional_metric(validation.get("market_brier_score"), maximum=1.0)
    model_log_loss = _optional_metric(validation.get("model_log_loss"))
    market_log_loss = _optional_metric(validation.get("market_log_loss"))
    model_ece = _optional_metric(validation.get("model_ece"), maximum=1.0)

    if None in {
        sample_size,
        model_brier,
        market_brier,
        model_log_loss,
        market_log_loss,
        model_ece,
    }:
        return False

    try:
        _probability(
            calibration.get("probability_selected_calibrated"),
            "calibration.probability_selected_calibrated",
        )
    except ModelOutputMappingError:
        return False

    return bool(model_brier < market_brier and model_log_loss < market_log_loss)


def to_canonical_model_output(
    prediction: Mapping[str, Any],
    *,
    market_id: str,
    competition: str,
    target_market: str,
    settlement_rules: str,
) -> dict[str, Any]:
    """Return a strict ``doctore.model-output.v1`` document.

    The rich probability-pipeline report remains an audit artifact. This adapter emits
    only the fields accepted by Doctore's decision layer. It never promotes a
    provisional or degraded pipeline to the validated Kelly tier.
    """

    report = _mapping(prediction, "prediction")
    market = _mapping(report.get("market"), "market")
    model = _mapping(report.get("model"), "model")
    calibration = _mapping(report.get("calibration"), "calibration")
    validation = _mapping(report.get("validation"), "validation")
    distribution = _mapping(report.get("distribution"), "distribution")

    event_id = _non_empty_string(report.get("event_id"), "event_id")
    sport = _non_empty_string(report.get("sport"), "sport")
    market_id_value = _non_empty_string(market_id, "market_id")
    competition_value = _non_empty_string(competition, "competition")
    target_market_value = _non_empty_string(target_market, "target_market")
    settlement_rules_value = _non_empty_string(settlement_rules, "settlement_rules")

    market_type = _non_empty_string(market.get("market_type"), "market.market_type")
    period = _non_empty_string(market.get("period"), "market.period")
    selection = _non_empty_string(market.get("selection"), "market.selection")
    line = _finite_number(market.get("line"), "market.line")

    model_name = _non_empty_string(model.get("model_name"), "model.model_name")
    model_version = _non_empty_string(model.get("model_version"), "model.model_version")
    prediction_generated_at = _non_empty_string(
        model.get("prediction_generated_at"),
        "model.prediction_generated_at",
    )
    feature_cutoff_at = _non_empty_string(
        model.get("feature_cutoff_at"),
        "model.feature_cutoff_at",
    )
    training_cutoff_at = _non_empty_string(
        model.get("training_cutoff_at"),
        "model.training_cutoff_at",
    )
    feature_schema_version = _non_empty_string(
        model.get("feature_schema_version"),
        "model.feature_schema_version",
    )

    probability_raw = _probability(
        calibration.get("probability_selected_raw"),
        "calibration.probability_selected_raw",
    )
    pipeline_status = _non_empty_string(
        calibration.get("status"),
        "calibration.status",
    ).lower()

    evidence_validated = _validated_evidence(
        pipeline_status=pipeline_status,
        calibration=calibration,
        validation=validation,
    )
    if evidence_validated:
        calibration_status = "validated"
        calibration_method = "sigmoid"
        probability_calibrated: float | None = _probability(
            calibration.get("probability_selected_calibrated"),
            "calibration.probability_selected_calibrated",
        )
    elif pipeline_status in _KNOWN_PIPELINE_STATUSES:
        calibration_status = "uncalibrated"
        calibration_method = "none"
        probability_calibrated = None
    else:
        calibration_status = "unknown"
        calibration_method = "none"
        probability_calibrated = None

    validation_start = validation.get("validation_period_start")
    validation_end = validation.get("validation_period_end")
    validation_window = None
    if (
        isinstance(validation_start, str)
        and validation_start
        and isinstance(validation_end, str)
        and validation_end
    ):
        validation_window = f"{validation_start}/{validation_end}"

    validation_sample_size = _optional_sample_size(validation.get("sample_size"))
    brier_score = _optional_metric(validation.get("model_brier_score"), maximum=1.0)
    log_loss = _optional_metric(validation.get("model_log_loss"))
    expected_calibration_error = _optional_metric(
        validation.get("model_ece"),
        maximum=1.0,
    )

    domain = {
        "sport": sport,
        "competition": competition_value,
        "market_type": market_type,
        "target_market": target_market_value,
        "period": period,
        "line": line,
        "settlement_rules": settlement_rules_value,
    }

    notes_payload = {
        "pipeline_status": pipeline_status,
        "market_snapshot_at": market.get("snapshot_at"),
        "market_no_vig_probability": market.get("no_vig_probability"),
        "probability_push": calibration.get("probability_push"),
        "residual_distribution_version": distribution.get(
            "residual_distribution_version"
        ),
        "market_brier_score": validation.get("market_brier_score"),
        "market_log_loss": validation.get("market_log_loss"),
        "brier_skill_score": validation.get("brier_skill_score"),
    }

    canonical: dict[str, Any] = {
        "schema_version": _CANONICAL_SCHEMA_VERSION,
        "event_id": event_id,
        "market_id": market_id_value,
        "model_name": model_name,
        "model_version": model_version,
        "sport": sport,
        "competition": competition_value,
        "market_type": market_type,
        "target_market": target_market_value,
        "period": period,
        "line": line,
        "settlement_rules": settlement_rules_value,
        "selection": selection,
        "probability_raw": probability_raw,
        "probability_calibrated": probability_calibrated,
        "calibration_status": calibration_status,
        "calibration_method": calibration_method,
        "prediction_generated_at": prediction_generated_at,
        "feature_cutoff_at": feature_cutoff_at,
        "training_cutoff_at": training_cutoff_at,
        "feature_schema_version": feature_schema_version,
        "validation_domain": domain,
        "validation_window": validation_window,
        "validation_sample_size": validation_sample_size,
        "brier_score": brier_score,
        "log_loss": log_loss,
        "expected_calibration_error": expected_calibration_error,
        "notes": json.dumps(
            notes_payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }

    model_hash = _optional_sha256(model.get("model_artifact_sha256"))
    if model_hash is not None:
        canonical["model_artifact_sha256"] = model_hash
    calibration_hash = _optional_sha256(
        calibration.get("calibration_artifact_sha256")
    )
    if calibration_hash is not None:
        canonical["calibration_artifact_sha256"] = calibration_hash

    return canonical
