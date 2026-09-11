"""Atomic slate-grouped expanding walk-forward validation for Doctore.

Rows in the same group share one prior-only model, residual history, and Platt
calibration history. No target, residual, or calibration observation from a
group is visible until every row in that group has been predicted/priced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

try:
    from .doctore_probability import (
        FittedProbabilityPipeline, Regressor, WalkForwardConfig, _hash_json, _hash_model,
        _odds_vector, _timestamp, _vector, _xy, binary_no_vig_probability,
        content_addressed_payload, default_xgb_factory, empirical_line_probability,
        evaluate_against_market, fit_platt_artifact,
    )
except ImportError:
    from doctore_probability import (
        FittedProbabilityPipeline, Regressor, WalkForwardConfig, _hash_json, _hash_model,
        _odds_vector, _timestamp, _vector, _xy, binary_no_vig_probability,
        content_addressed_payload, default_xgb_factory, empirical_line_probability,
        evaluate_against_market, fit_platt_artifact,
    )

GROUPED_VALIDATION_METHOD = "expanding_grouped_walk_forward_oos"


@dataclass(frozen=True)
class GroupedFittedProbabilityPipeline(FittedProbabilityPipeline):
    group_count: int = 0
    validation_method: str = GROUPED_VALIDATION_METHOD

    def predict_exact_line(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = super().predict_exact_line(*args, **kwargs)
        for key in ("prediction_id", "content_sha256", "immutability"):
            payload.pop(key, None)
        payload["validation"]["method"] = self.validation_method
        payload.setdefault("metadata", {})["walk_forward_grouping"] = "atomic_slate"
        return content_addressed_payload(payload)


def _group_boundaries(
    groups: Sequence[str], n: int,
) -> tuple[tuple[str, ...], tuple[tuple[int, int, str], ...]]:
    if len(groups) != n:
        raise ValueError("groups must align")
    normalized = tuple(str(value).strip() for value in groups)
    if any(not value for value in normalized):
        raise ValueError("group ids must be non-empty")
    boundaries: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    start = 0
    while start < n:
        group = normalized[start]
        if group in seen:
            raise ValueError("group ids must be contiguous")
        end = start + 1
        while end < n and normalized[end] == group:
            end += 1
        boundaries.append((start, end, group))
        seen.add(group)
        start = end
    return normalized, tuple(boundaries)


def validate_grouped_order(
    timestamps: Sequence[str], groups: Sequence[str], n: int,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[int, int, str], ...]]:
    if len(timestamps) != n:
        raise ValueError("timestamps must align")
    parsed = [_timestamp(value) for value in timestamps]
    if any(current < previous for previous, current in zip(parsed, parsed[1:])):
        raise ValueError("grouped timestamps must be non-decreasing")
    normalized, boundaries = _group_boundaries(groups, n)
    return tuple(timestamps), normalized, boundaries


def grouped_expanding_walk_forward_predictions(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    groups: Sequence[str],
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor],
) -> np.ndarray:
    x_arr, y_arr = _xy(x, y)
    n = len(y_arr)
    config.validate(n)
    _normalized, boundaries = _group_boundaries(groups, n)
    predictions = np.full(n, np.nan)
    for start, end, _group in boundaries:
        if start < config.min_train_size:
            continue
        model = estimator_factory()
        model.fit(x_arr[:start], y_arr[:start])
        fold = np.asarray(model.predict(x_arr[start:end]), dtype=float)
        if fold.shape != (end - start,) or not np.all(np.isfinite(fold)):
            raise ValueError("invalid estimator predictions")
        predictions[start:end] = fold
    return predictions


def _grouped_predictions_with_boundaries(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    boundaries: Sequence[tuple[int, int, str]],
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor],
) -> np.ndarray:
    predictions = np.full(len(y_arr), np.nan)
    for start, end, _group in boundaries:
        if start < config.min_train_size:
            continue
        model = estimator_factory()
        model.fit(x_arr[:start], y_arr[:start])
        fold = np.asarray(model.predict(x_arr[start:end]), dtype=float)
        if fold.shape != (end - start,) or not np.all(np.isfinite(fold)):
            raise ValueError("invalid estimator predictions")
        predictions[start:end] = fold
    return predictions


def grouped_historical_rows(
    actuals: np.ndarray,
    lines: np.ndarray,
    over_odds: np.ndarray,
    under_odds: np.ndarray,
    point: np.ndarray,
    boundaries: Sequence[tuple[int, int, str]],
    config: WalkForwardConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    residual_history: list[float] = []
    raw: list[float] = []
    outcomes: list[int] = []
    market: list[float] = []
    source: list[int] = []
    source_groups: list[str] = []
    residual_history_sizes: list[int] = []
    for start, end, group in boundaries:
        indices = [index for index in range(start, end) if np.isfinite(point[index])]
        if not indices:
            continue
        prior_residuals = np.asarray(residual_history, dtype=float)
        if len(prior_residuals) >= config.min_residual_history:
            for index in indices:
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
                source_groups.append(group)
                residual_history_sizes.append(len(prior_residuals))
        residual_history.extend(float(actuals[index] - point[index]) for index in indices)
    return (
        np.asarray(raw, dtype=float),
        np.asarray(outcomes, dtype=int),
        np.asarray(market, dtype=float),
        np.asarray(source, dtype=int),
        np.asarray(source_groups, dtype=object),
        np.asarray(residual_history_sizes, dtype=int),
    )


def grouped_walk_forward_platt(
    raw: np.ndarray,
    outcomes: np.ndarray,
    groups: Sequence[str],
    minimum_history: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(raw) != len(outcomes) or len(raw) != len(groups):
        raise ValueError("raw probabilities, outcomes and groups must align")
    calibrated = np.full(len(raw), np.nan)
    mask = np.zeros(len(raw), dtype=bool)
    history_sizes = np.full(len(raw), -1, dtype=int)
    start = 0
    seen: set[str] = set()
    while start < len(raw):
        group = str(groups[start])
        if group in seen:
            raise ValueError("calibration group ids must be contiguous")
        end = start + 1
        while end < len(raw) and str(groups[end]) == group:
            end += 1
        history_sizes[start:end] = start
        if start >= minimum_history and len(np.unique(outcomes[:start])) >= 2:
            calibrator = fit_platt_artifact(
                raw[:start], outcomes[:start], model_version="grouped-walk-forward-evaluation"
            )
            for index in range(start, end):
                calibrated[index] = calibrator.predict(float(raw[index]))
                mask[index] = True
        seen.add(group)
        start = end
    return calibrated, mask, history_sizes


def fit_grouped_probability_pipeline(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    market_lines: Sequence[float] | np.ndarray,
    over_odds_decimal: Sequence[float] | np.ndarray,
    under_odds_decimal: Sequence[float] | np.ndarray,
    timestamps: Sequence[str],
    groups: Sequence[str],
    *,
    model_name: str,
    model_version: str,
    feature_schema_version: str,
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor] | None = None,
    xgb_params: Mapping[str, Any] | None = None,
) -> GroupedFittedProbabilityPipeline:
    x_arr, y_arr = _xy(x, y)
    n = len(y_arr)
    config.validate(n)
    lines = _vector(market_lines, n, "market_lines")
    over_odds = _odds_vector(over_odds_decimal, n)
    under_odds = _odds_vector(under_odds_decimal, n)
    times, normalized_groups, boundaries = validate_grouped_order(timestamps, groups, n)
    factory = estimator_factory or default_xgb_factory(xgb_params)
    point = _grouped_predictions_with_boundaries(x_arr, y_arr, boundaries, config, factory)
    raw, outcomes, market, source_indices, source_groups, _history_sizes = grouped_historical_rows(
        y_arr, lines, over_odds, under_odds, point, boundaries, config
    )
    if len(raw) <= config.min_calibration_history:
        raise ValueError("insufficient non-push grouped OOS rows")
    calibrated, evaluation_mask, _calibration_sizes = grouped_walk_forward_platt(
        raw, outcomes, source_groups, config.min_calibration_history
    )
    if not np.any(evaluation_mask):
        raise ValueError("insufficient prior-group history for OOS Platt evaluation")
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
        "method": GROUPED_VALIDATION_METHOD,
        "groups": [normalized_groups[index] for index in np.flatnonzero(oos_mask)],
        "residuals": residuals.tolist(),
    })
    if metrics.sample_size < config.minimum_validation_sample:
        status = "provisional"
    elif metrics.model_brier_score < metrics.market_brier_score and metrics.model_log_loss < metrics.market_log_loss:
        status = "validated"
    else:
        status = "degraded"
    evaluated_indices = source_indices[evaluation_mask]
    return GroupedFittedProbabilityPipeline(
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
        group_count=len(boundaries),
    )
