"""Fixed-cohort grouped OOS ablation for Doctore feature groups.

Every stage uses the same rows, group boundaries, target, market lines, odds and
validation configuration. Only cumulative feature columns change. This avoids
sample-composition confounding when measuring incremental feature-group value.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

try:
    from .doctore_probability import (
        Regressor,
        ValidationMetrics,
        WalkForwardConfig,
        default_xgb_factory,
        evaluate_against_market,
        _odds_vector,
        _vector,
        _xy,
    )
    from .grouped_probability import (
        _grouped_predictions_with_boundaries,
        grouped_historical_rows,
        grouped_walk_forward_platt,
        validate_grouped_order,
    )
except ImportError:
    from doctore_probability import (
        Regressor,
        ValidationMetrics,
        WalkForwardConfig,
        default_xgb_factory,
        evaluate_against_market,
        _odds_vector,
        _vector,
        _xy,
    )
    from grouped_probability import (
        _grouped_predictions_with_boundaries,
        grouped_historical_rows,
        grouped_walk_forward_platt,
        validate_grouped_order,
    )


class AblationError(ValueError):
    pass


@dataclass(frozen=True)
class AblationStageResult:
    stage: str
    feature_groups: tuple[str, ...]
    feature_columns: tuple[str, ...]
    metrics: ValidationMetrics
    evaluation_sample_size: int
    brier_improvement_vs_previous: float | None
    log_loss_improvement_vs_previous: float | None
    brier_improvement_vs_market: float
    log_loss_improvement_vs_market: float
    incremental_status: str
    beats_market: bool


def build_cumulative_stages(
    feature_groups: Mapping[str, Sequence[str]],
    group_order: Sequence[str],
) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    if not group_order or group_order[0] != "baseline":
        raise AblationError("group_order must start with baseline")
    if len(set(group_order)) != len(group_order):
        raise AblationError("group_order contains duplicates")
    seen_columns: set[str] = set()
    cumulative_groups: list[str] = []
    cumulative_columns: list[str] = []
    stages: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for group in group_order:
        if group not in feature_groups:
            raise AblationError(f"feature group missing from mapping: {group}")
        columns = tuple(str(value).strip() for value in feature_groups[group])
        if not columns or any(not value for value in columns):
            raise AblationError(f"feature group {group} has empty columns")
        overlap = seen_columns.intersection(columns)
        if overlap:
            raise AblationError(f"feature columns overlap across groups: {sorted(overlap)}")
        seen_columns.update(columns)
        cumulative_groups.append(group)
        cumulative_columns.extend(columns)
        stages.append((
            "+".join(cumulative_groups),
            tuple(cumulative_groups),
            tuple(cumulative_columns),
        ))
    return tuple(stages)


def _feature_matrix(
    feature_values: Mapping[str, Sequence[float]],
    columns: Sequence[str],
    n: int,
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    for column in columns:
        if column not in feature_values:
            raise AblationError(f"missing feature column: {column}")
        values = np.asarray(feature_values[column], dtype=float)
        if values.shape != (n,):
            raise AblationError(f"feature column {column} does not align")
        if not np.all(np.isfinite(values)):
            raise AblationError(f"feature column {column} contains non-finite values")
        vectors.append(values)
    if not vectors:
        raise AblationError("ablation stage has no features")
    return np.column_stack(vectors)


def _classify_increment(brier: float | None, log_loss: float | None) -> str:
    if brier is None or log_loss is None:
        return "BASELINE"
    if brier > 0.0 and log_loss > 0.0:
        return "INCREMENTAL_PASS"
    if brier <= 0.0 and log_loss <= 0.0:
        return "INCREMENTAL_FAIL"
    return "INCREMENTAL_MIXED"


def run_grouped_oos_ablation(
    *,
    feature_values: Mapping[str, Sequence[float]],
    feature_groups: Mapping[str, Sequence[str]],
    group_order: Sequence[str],
    target: Sequence[float] | np.ndarray,
    market_lines: Sequence[float] | np.ndarray,
    over_odds_decimal: Sequence[float] | np.ndarray,
    under_odds_decimal: Sequence[float] | np.ndarray,
    timestamps: Sequence[str],
    groups: Sequence[str],
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor] | None = None,
    xgb_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run cumulative feature-group ablation on one immutable evaluation cohort."""
    y_arr = np.asarray(target, dtype=float)
    if y_arr.ndim != 1 or not np.all(np.isfinite(y_arr)):
        raise AblationError("target must be a finite 1D vector")
    n = len(y_arr)
    config.validate(n)
    lines = _vector(market_lines, n, "market_lines")
    over_odds = _odds_vector(over_odds_decimal, n)
    under_odds = _odds_vector(under_odds_decimal, n)
    _times, _normalized_groups, boundaries = validate_grouped_order(timestamps, groups, n)
    stages = build_cumulative_stages(feature_groups, group_order)
    factory = estimator_factory or default_xgb_factory(xgb_params)

    all_required_columns = stages[-1][2]
    _feature_matrix(feature_values, all_required_columns, n)  # fixed-cohort preflight

    results: list[AblationStageResult] = []
    expected_evaluation_indices: tuple[int, ...] | None = None
    previous_metrics: ValidationMetrics | None = None

    for stage_name, stage_groups, stage_columns in stages:
        x_arr = _feature_matrix(feature_values, stage_columns, n)
        x_arr, y_checked = _xy(x_arr, y_arr)
        point = _grouped_predictions_with_boundaries(
            x_arr, y_checked, boundaries, config, factory
        )
        raw, outcomes, market, source_indices, source_groups, _history_sizes = grouped_historical_rows(
            y_checked, lines, over_odds, under_odds, point, boundaries, config
        )
        if len(raw) <= config.min_calibration_history:
            raise AblationError(f"stage {stage_name}: insufficient non-push grouped OOS rows")
        calibrated, evaluation_mask, _calibration_sizes = grouped_walk_forward_platt(
            raw, outcomes, source_groups, config.min_calibration_history
        )
        if not np.any(evaluation_mask):
            raise AblationError(f"stage {stage_name}: no OOS calibration evaluation rows")
        evaluation_indices = tuple(int(value) for value in source_indices[evaluation_mask])
        if expected_evaluation_indices is None:
            expected_evaluation_indices = evaluation_indices
        elif evaluation_indices != expected_evaluation_indices:
            raise AblationError(
                f"stage {stage_name}: evaluation cohort drifted across ablation stages"
            )
        metrics = evaluate_against_market(
            calibrated[evaluation_mask], market[evaluation_mask], outcomes[evaluation_mask]
        )
        brier_prev = None if previous_metrics is None else previous_metrics.model_brier_score - metrics.model_brier_score
        log_prev = None if previous_metrics is None else previous_metrics.model_log_loss - metrics.model_log_loss
        brier_market = metrics.market_brier_score - metrics.model_brier_score
        log_market = metrics.market_log_loss - metrics.model_log_loss
        results.append(AblationStageResult(
            stage=stage_name,
            feature_groups=stage_groups,
            feature_columns=stage_columns,
            metrics=metrics,
            evaluation_sample_size=len(evaluation_indices),
            brier_improvement_vs_previous=brier_prev,
            log_loss_improvement_vs_previous=log_prev,
            brier_improvement_vs_market=brier_market,
            log_loss_improvement_vs_market=log_market,
            incremental_status=_classify_increment(brier_prev, log_prev),
            beats_market=(brier_market > 0.0 and log_market > 0.0),
        ))
        previous_metrics = metrics

    final = results[-1]
    return {
        "schema_version": "doctore.grouped-ablation.v1",
        "validation_method": "expanding_grouped_walk_forward_oos",
        "fixed_evaluation_cohort": True,
        "row_count": n,
        "group_count": len(boundaries),
        "evaluation_sample_size": final.evaluation_sample_size,
        "group_order": list(group_order),
        "stages": [
            {
                **{key: value for key, value in asdict(result).items() if key != "metrics"},
                "metrics": asdict(result.metrics),
            }
            for result in results
        ],
        "final_stage_beats_market": final.beats_market,
        "promotion_gate": "PASS" if final.beats_market else "FAIL",
    }
