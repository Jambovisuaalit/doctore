"""Fail-closed, point-in-time market and model evidence gates.

These checks are pure and do not manufacture a model probability.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing ISO-8601 timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone offset required")
    return dt.astimezone(timezone.utc)


def classify_quote(last_update: str, commence_time: str, *, live_verified: bool = False) -> str:
    """Timestamp alone cannot prove that a post-start quote was in-play."""
    updated, started = _utc(last_update), _utc(commence_time)
    if updated < started:
        return "PREMATCH"
    return "IN_PLAY" if live_verified else "POST_START_UNKNOWN"


def verify_registry(
    manifest: Mapping[str, Any],
    calibration: Mapping[str, Any],
    oos: Mapping[str, Any],
    prediction: Mapping[str, Any],
    *,
    model_path: Path | None = None,
    calibrator_path: Path | None = None,
) -> list[str]:
    """Return explicit failure codes; empty means *evidence checks* passed.

    Never interpret this as independent verification of statistical validity.
    """
    errors: list[str] = []
    model = prediction.get("model", {})
    market = prediction.get("market", {})
    if not isinstance(model, dict) or not isinstance(market, dict):
        return ["INVALID_PREDICTION_SHAPE"]
    required = ("model_version", "calibrator_version", "feature_cutoff_at",
                "market_rules", "event_id", "OOS_validation_status")
    evidence = {
        "model_version": model.get("model_version"),
        "calibrator_version": calibration.get("calibrator_version"),
        "feature_cutoff_at": model.get("feature_cutoff_at"),
        "market_rules": market.get("settlement_rules"),
        "event_id": prediction.get("event_id"),
        "OOS_validation_status": oos.get("OOS_validation_status"),
    }
    errors += ["MISSING_" + k.upper() for k in required if not evidence[k]]
    if evidence["OOS_validation_status"] != "PASS":
        errors.append("OOS_NOT_PASS")
    for key in ("model_version", "calibrator_version", "market_rules"):
        if evidence[key] != manifest.get(key) or evidence[key] != oos.get(key):
            errors.append("MISMATCH_" + key.upper())
    if evidence["event_id"] != manifest.get("event_id") or evidence["event_id"] != oos.get("event_id"):
        errors.append("EVENT_ID_MISMATCH")
    try:
        cutoff = _utc(evidence["feature_cutoff_at"])
        prediction_at = _utc(model.get("prediction_generated_at"))
        if cutoff > prediction_at:
            errors.append("FEATURE_CUTOFF_AFTER_PREDICTION")
        if "commence_time" in market and cutoff >= _utc(market["commence_time"]):
            errors.append("FEATURE_CUTOFF_NOT_PREGAME")
    except (ValueError, TypeError):
        errors.append("INVALID_FEATURE_TIME")
    for label, path, key in (
        ("MODEL", model_path, "model_artifact_sha256"),
        ("CALIBRATOR", calibrator_path, "calibration_artifact_sha256"),
    ):
        expected = manifest.get(key)
        if not isinstance(expected, str) or len(expected) != 64 or path is None:
            errors.append(label + "_ARTIFACT_UNVERIFIED")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected.lower():
                errors.append(label + "_SHA256_MISMATCH")
        except OSError:
            errors.append(label + "_ARTIFACT_UNREADABLE")
    return sorted(set(errors))
