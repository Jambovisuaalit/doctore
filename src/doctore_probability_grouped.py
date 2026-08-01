"""Timestamp-grouped leakage-safe probability pipeline.

All rows sharing a timestamp are predicted, residual-priced and calibrated as
one block. No result from a cutoff group can enter another prediction in the
same group.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from doctore_probability import (
    FittedProbabilityPipeline,
    Regressor,
    WalkForwardConfig,
    binary_no_vig_probability,
    default_xgb_factory,
    empirical_line_probability,
    evaluate_against_market,
    fit_platt_artifact,
)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _arrays(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    timestamps: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...], np.ndarray]:
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if x_arr.ndim != 2 or y_arr.ndim != 1 or len(x_arr) != len(y_arr):
        raise ValueError("x and y must be aligned")
    if len(timestamps) != len(y_arr) or len(y_arr) < 3:
        raise ValueError("timestamps must align")
    if not np.all(np.isfinite(x_arr)) or not np.all(np.isfinite(y_arr)):
        raise ValueError("x and y must be finite")
    parsed = np.asarray([_timestamp(value).timestamp() for value in timestamps], dtype=float)
    if np.any(parsed[1:] < parsed[:-1]):
        raise ValueError("timestamps must be nondecreasing")
    return x_arr, y_arr, tuple(timestamps), parsed


def _hash_json(value: Mapping[str, Any]) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(content.encode("utf-8")).hexdigest()


def _hash_model(model: Regressor) -> str:
    if hasattr(model, "save_model"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save_model(path)  # type: ignore[attr-defined]
            return sha256(path.read_bytes()).hexdigest()
    params = model.get_params() if hasattr(model, "get_params") else {"repr": repr(model)}
    return _hash_json({"model": type(model).__name__, "params": params})


def _timestamp_groups(parsed: np.ndarray) -> list[np.ndarray]:
    groups: list[np.ndarray] = []
    start = 0
    for index in range(1, len(parsed) + 1):
        if index == len(parsed) or parsed[index] != parsed[start]:
            groups.append(np.arange(start, index, dtype=int))
            start = index
    return groups


def expanding_walk_forward_predictions_grouped(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    timestamps: Sequence[str],
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor],
) -> np.ndarray:
    x_arr, y_arr, _, parsed = _arrays(x, y, timestamps)
    config.validate(len(y_arr))
    predictions = np.full(len(y_arr), np.nan)
    for group in _timestamp_groups(parsed):
        start = int(group[0])
        if start < config.min_train_size:
            continue
        model = estimator_factory()
        model.fit(x_arr[:start], y_arr[:start])
        fold = np.asarray(model.predict(x_arr[group]), dtype=float)
        if fold.shape != (len(group),) or not np.all(np.isfinite(fold)):
            raise ValueError("invalid estimator predictions")
        predictions[group] = fold
    return predictions


def _historical_rows_grouped(
    actuals: np.ndarray,
    lines: np.ndarray,
    over_odds: np.ndarray,
    under_odds: np.ndarray,
    point: np.ndarray,
    parsed: np.ndarray,
    config: WalkForwardConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    prior_residuals: list[float] = []
    raw: list[float] = []
    outcomes: list[int] = []
    market: list[float] = []
    source: list[int] = []
    source_times: list[float] = []
    for group in _timestamp_groups(parsed):
        valid = [int(index) for index in group if np.isfinite(point[index])]
        if not valid:
            continue
        if len(prior_residuals) >= config.min_residual_history:
            for index in valid:
                priced = empirical_line_probability(
                    point[index], lines[index], prior_residuals,
                    push_tolerance=config.push_tolerance,
                )
                difference = actuals[index] - lines[index]
                if abs(difference) <= config.push_tolerance:
                    continue
                raw.append(priced.over_conditional_non_push)
                outcomes.append(int(difference > 0))
                market.append(binary_no_vig_probability(over_odds[index], under_odds[index]))
                source.append(index)
                source_times.append(parsed[index])
        # Add residuals only after every row in the group has been priced.
        prior_residuals.extend(float(actuals[index] - point[index]) for index in valid)
    if len(raw) <= config.min_calibration_history:
        raise ValueError("insufficient non-push grouped OOS rows")
    return (
        np.asarray(raw), np.asarray(outcomes), np.asarray(market),
        np.asarray(source), np.asarray(source_times),
    )


def _walk_forward_platt_grouped(
    raw: np.ndarray,
    outcomes: np.ndarray,
    source_times: np.ndarray,
    minimum_history: int,
) -> tuple[np.ndarray, np.ndarray]:
    calibrated = np.full(len(raw), np.nan)
    mask = np.zeros(len(raw), dtype=bool)
    start = 0
    while start < len(raw):
        end = start + 1
        while end < len(raw) and source_times[end] == source_times[start]:
            end += 1
        if start >= minimum_history and len(np.unique(outcomes[:start])) >= 2:
            artifact = fit_platt_artifact(
                raw[:start], outcomes[:start], model_version="grouped-walk-forward-evaluation"
            )
            for index in range(start, end):
                calibrated[index] = artifact.predict(float(raw[index]))
                mask[index] = True
        start = end
    return calibrated, mask


def fit_probability_pipeline_grouped(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    market_lines: Sequence[float] | np.ndarray,
    over_odds_decimal: Sequence[float] | np.ndarray,
    under_odds_decimal: Sequence[float] | np.ndarray,
    timestamps: Sequence[str],
    *,
    model_name: str,
    model_version: str,
    feature_schema_version: str,
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor] | None = None,
    xgb_params: Mapping[str, Any] | None = None,
) -> FittedProbabilityPipeline:
    x_arr, y_arr, times, parsed = _arrays(x, y, timestamps)
    n = len(y_arr)
    config.validate(n)
    lines = np.asarray(market_lines, dtype=float)
    over_odds = np.asarray(over_odds_decimal, dtype=float)
    under_odds = np.asarray(under_odds_decimal, dtype=float)
    for name, values in (("market_lines", lines), ("over_odds", over_odds), ("under_odds", under_odds)):
        if values.shape != (n,) or not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must be a finite aligned vector")
    if np.any(over_odds <= 1.0) or np.any(under_odds <= 1.0):
        raise ValueError("decimal odds must exceed 1")

    factory = estimator_factory or default_xgb_factory(xgb_params)
    point = expanding_walk_forward_predictions_grouped(x_arr, y_arr, times, config, factory)
    raw, outcomes, market, source_indices, source_times = _historical_rows_grouped(
        y_arr, lines, over_odds, under_odds, point, parsed, config
    )
    calibrated, evaluation_mask = _walk_forward_platt_grouped(
        raw, outcomes, source_times, config.min_calibration_history
    )
    if not np.any(evaluation_mask):
        raise ValueError("insufficient history for grouped OOS Platt evaluation")
    metrics = evaluate_against_market(
        calibrated[evaluation_mask], market[evaluation_mask], outcomes[evaluation_mask]
    )
    calibrator = fit_platt_artifact(raw, outcomes, model_version=model_version)
    final_model = factory()
    final_model.fit(x_arr, y_arr)
    model_hash = _hash_model(final_model)
    oos_mask = np.isfinite(point)
    residuals = y_arr[oos_mask] - point[oos_mask]
    residual_hash = _hash_json({
        "model_version": model_version,
        "method": "timestamp_grouped_expanding_walk_forward_oos",
        "residuals": residuals.tolist(),
    })
    if metrics.sample_size < config.minimum_validation_sample:
        status = "provisional"
    elif metrics.model_brier_score < metrics.market_brier_score and metrics.model_log_loss < metrics.market_log_loss:
        status = "validated"
    else:
        status = "degraded"
    evaluated_indices = source_indices[evaluation_mask]
    return FittedProbabilityPipeline(
        model=final_model,
        model_name=model_name,
        model_version=model_version,
        model_artifact_sha256=model_hash,
        residuals=tuple(float(value) for value in residuals),
        residual_artifact_sha256=residual_hash,
        residual_distribution_version=f"{model_version}-grouped-residuals-{residual_hash[:12]}",
        calibrator=calibrator,
        validation_metrics=metrics,
        calibration_status=status,
        feature_schema_version=feature_schema_version,
        training_cutoff_at=times[-1],
        validation_period_start=times[int(evaluated_indices[0])],
        validation_period_end=times[int(evaluated_indices[-1])],
        config=config,
    )
