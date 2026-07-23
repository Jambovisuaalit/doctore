"""Leakage-safe Doctore regression-to-probability pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression
from xgboost import XGBRegressor

EPS = 1e-6


class Regressor(Protocol):
    def fit(self, x: np.ndarray, y: np.ndarray) -> Any: ...
    def predict(self, x: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class WalkForwardConfig:
    min_train_size: int
    test_size: int = 1
    min_residual_history: int = 100
    min_calibration_history: int = 200
    minimum_validation_sample: int = 200
    push_tolerance: float = 1e-12

    def validate(self, n: int) -> None:
        if not 2 <= self.min_train_size < n:
            raise ValueError("min_train_size must be in [2, sample_size)")
        if self.test_size < 1:
            raise ValueError("test_size must be positive")
        if self.min_residual_history < 2 or self.min_calibration_history < 2:
            raise ValueError("history minimums must be at least 2")
        if self.minimum_validation_sample < 1:
            raise ValueError("minimum_validation_sample must be positive")


@dataclass(frozen=True)
class EmpiricalLineProbability:
    over: float
    under: float
    push: float
    over_conditional_non_push: float
    residual_sample_size: int
    threshold_residual: float


@dataclass(frozen=True)
class PlattArtifact:
    intercept: float
    coefficient: float
    training_sample_size: int
    positive_rate: float
    artifact_sha256: str
    version: str

    def predict(self, raw_probability: float) -> float:
        z = self.intercept + self.coefficient * _logit(raw_probability)
        value = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
        return min(max(value, EPS), 1.0 - EPS)


@dataclass(frozen=True)
class ValidationMetrics:
    sample_size: int
    model_brier_score: float
    market_brier_score: float
    brier_skill_score: float
    model_log_loss: float
    market_log_loss: float
    model_ece: float
    market_ece: float


@dataclass(frozen=True)
class FittedProbabilityPipeline:
    model: Regressor
    model_name: str
    model_version: str
    model_artifact_sha256: str
    residuals: tuple[float, ...]
    residual_artifact_sha256: str
    residual_distribution_version: str
    calibrator: PlattArtifact
    validation_metrics: ValidationMetrics
    calibration_status: str
    feature_schema_version: str
    training_cutoff_at: str
    validation_period_start: str
    validation_period_end: str
    config: WalkForwardConfig

    def predict_exact_line(
        self,
        features: Sequence[float] | np.ndarray,
        *,
        event_id: str,
        sport: str,
        market_type: str,
        period: str,
        selection: str,
        market_line: float,
        selection_odds_decimal: float,
        opposing_odds_decimal: float,
        market_snapshot_at: str,
        feature_cutoff_at: str,
        prediction_generated_at: str | None = None,
        book: str | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        side = selection.lower().strip()
        if side not in {"over", "under"}:
            raise ValueError("selection must be over or under")
        _odds(selection_odds_decimal)
        _odds(opposing_odds_decimal)
        _timestamp(market_snapshot_at)
        _timestamp(feature_cutoff_at)
        x = np.asarray(features, dtype=float).reshape(1, -1)
        if not np.all(np.isfinite(x)):
            raise ValueError("features must be finite")

        point = float(np.asarray(self.model.predict(x), dtype=float)[0])
        raw = empirical_line_probability(
            point, market_line, self.residuals, push_tolerance=self.config.push_tolerance
        )
        calibrated_over_conditional = self.calibrator.predict(raw.over_conditional_non_push)
        non_push = 1.0 - raw.push
        calibrated_over = non_push * calibrated_over_conditional
        calibrated_under = non_push * (1.0 - calibrated_over_conditional)
        selected_raw = raw.over if side == "over" else raw.under
        selected_calibrated = calibrated_over if side == "over" else calibrated_under
        opposing_calibrated = calibrated_under if side == "over" else calibrated_over
        market_no_vig = binary_no_vig_probability(selection_odds_decimal, opposing_odds_decimal)
        generated_at = prediction_generated_at or datetime.now(timezone.utc).isoformat()
        _timestamp(generated_at)

        payload = {
            "output_schema_version": "doctore-prediction-v2.0.0",
            "event_id": event_id,
            "sport": sport,
            "market": {
                "market_type": market_type,
                "period": period,
                "selection": side,
                "line": float(market_line),
                "book": book,
                "odds_decimal": float(selection_odds_decimal),
                "opposing_odds_decimal": float(opposing_odds_decimal),
                "no_vig_probability": market_no_vig,
                "snapshot_at": market_snapshot_at,
            },
            "model": {
                "model_name": self.model_name,
                "model_version": self.model_version,
                "model_artifact_sha256": self.model_artifact_sha256,
                "feature_schema_version": self.feature_schema_version,
                "point_estimate": point,
                "prediction_generated_at": generated_at,
                "feature_cutoff_at": feature_cutoff_at,
                "training_cutoff_at": self.training_cutoff_at,
            },
            "distribution": {
                "method": "empirical_oos_residual_cdf",
                "residual_distribution_version": self.residual_distribution_version,
                "residual_artifact_sha256": self.residual_artifact_sha256,
                "residual_sample_size": raw.residual_sample_size,
                "threshold_residual": raw.threshold_residual,
                "probability_over_raw": raw.over,
                "probability_under_raw": raw.under,
                "probability_push_raw": raw.push,
                "probability_over_conditional_non_push_raw": raw.over_conditional_non_push,
            },
            "calibration": {
                "method": "platt_logistic_on_logit_raw_probability",
                "status": self.calibration_status,
                "calibration_version": self.calibrator.version,
                "calibration_artifact_sha256": self.calibrator.artifact_sha256,
                "training_sample_size": self.calibrator.training_sample_size,
                "probability_selected_raw": selected_raw,
                "probability_selected_calibrated": selected_calibrated,
                "probability_opposing_calibrated": opposing_calibrated,
                "probability_push": raw.push,
            },
            "validation": asdict(self.validation_metrics) | {
                "method": "expanding_walk_forward_oos",
                "validation_period_start": self.validation_period_start,
                "validation_period_end": self.validation_period_end,
            },
            "decision_inputs": {
                "edge_probability_points": selected_calibrated - market_no_vig,
                "expected_value_with_push": selected_calibrated * selection_odds_decimal + raw.push - 1.0,
            },
            "metadata": dict(extra_metadata or {}),
        }
        return content_addressed_payload(payload)


def default_xgb_factory(params: Mapping[str, Any] | None = None) -> Callable[[], Regressor]:
    settings: dict[str, Any] = {
        "objective": "reg:squarederror",
        "n_estimators": 300,
        "learning_rate": 0.03,
        "max_depth": 4,
        "min_child_weight": 5,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": 1,
    }
    settings.update(dict(params or {}))
    return lambda: XGBRegressor(**settings)


def expanding_walk_forward_predictions(
    x: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    config: WalkForwardConfig,
    estimator_factory: Callable[[], Regressor],
) -> np.ndarray:
    x_arr, y_arr = _xy(x, y)
    config.validate(len(y_arr))
    predictions = np.full(len(y_arr), np.nan)
    for start in range(config.min_train_size, len(y_arr), config.test_size):
        end = min(start + config.test_size, len(y_arr))
        model = estimator_factory()
        model.fit(x_arr[:start], y_arr[:start])
        fold = np.asarray(model.predict(x_arr[start:end]), dtype=float)
        if fold.shape != (end - start,) or not np.all(np.isfinite(fold)):
            raise ValueError("invalid estimator predictions")
        predictions[start:end] = fold
    return predictions


def empirical_line_probability(
    point_estimate: float,
    market_line: float,
    residuals: Sequence[float] | np.ndarray,
    *,
    push_tolerance: float = 1e-12,
) -> EmpiricalLineProbability:
    values = np.asarray(residuals, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("residuals must be a finite 1D sample of size >= 2")
    threshold = market_line - point_estimate
    over_n = int(np.count_nonzero(values > threshold + push_tolerance))
    under_n = int(np.count_nonzero(values < threshold - push_tolerance))
    push_n = len(values) - over_n - under_n
    if over_n + under_n == 0:
        raise ValueError("residual history contains only pushes")
    return EmpiricalLineProbability(
        over=over_n / len(values),
        under=under_n / len(values),
        push=push_n / len(values),
        over_conditional_non_push=over_n / (over_n + under_n),
        residual_sample_size=len(values),
        threshold_residual=float(threshold),
    )


def fit_probability_pipeline(
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
    x_arr, y_arr = _xy(x, y)
    n = len(y_arr)
    config.validate(n)
    lines = _vector(market_lines, n, "market_lines")
    over_odds = _odds_vector(over_odds_decimal, n)
    under_odds = _odds_vector(under_odds_decimal, n)
    times = _chronological_timestamps(timestamps, n)
    factory = estimator_factory or default_xgb_factory(xgb_params)
    point = expanding_walk_forward_predictions(x_arr, y_arr, config, factory)
    raw, outcomes, market, source_indices = _historical_rows(
        y_arr, lines, over_odds, under_odds, point, config
    )
    calibrated, evaluation_mask = _walk_forward_platt(raw, outcomes, config.min_calibration_history)
    if not np.any(evaluation_mask):
        raise ValueError("insufficient history for OOS Platt evaluation")
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
        "method": "expanding_walk_forward_oos",
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
        residuals=tuple(float(v) for v in residuals),
        residual_artifact_sha256=residual_hash,
        residual_distribution_version=f"{model_version}-residuals-{residual_hash[:12]}",
        calibrator=calibrator,
        validation_metrics=metrics,
        calibration_status=status,
        feature_schema_version=feature_schema_version,
        training_cutoff_at=times[-1],
        validation_period_start=times[int(evaluated_indices[0])],
        validation_period_end=times[int(evaluated_indices[-1])],
        config=config,
    )


def fit_platt_artifact(
    raw_probabilities: Sequence[float] | np.ndarray,
    outcomes: Sequence[int] | np.ndarray,
    *,
    model_version: str,
) -> PlattArtifact:
    raw = np.asarray(raw_probabilities, dtype=float)
    target = np.asarray(outcomes, dtype=int)
    if raw.ndim != 1 or target.shape != raw.shape or len(np.unique(target)) < 2:
        raise ValueError("Platt calibration requires aligned probabilities and both classes")
    scores = np.array([_logit(v) for v in raw]).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=2000).fit(scores, target)
    payload = {
        "method": "platt_logistic_on_logit_raw_probability",
        "model_version": model_version,
        "intercept": float(model.intercept_[0]),
        "coefficient": float(model.coef_[0, 0]),
        "training_sample_size": len(target),
        "positive_rate": float(np.mean(target)),
    }
    digest = _hash_json(payload)
    return PlattArtifact(
        intercept=payload["intercept"],
        coefficient=payload["coefficient"],
        training_sample_size=len(target),
        positive_rate=payload["positive_rate"],
        artifact_sha256=digest,
        version=f"{model_version}-platt-{digest[:12]}",
    )


def evaluate_against_market(model_p: Sequence[float], market_p: Sequence[float], outcomes: Sequence[int]) -> ValidationMetrics:
    model = _probability_vector(model_p)
    market = _probability_vector(market_p)
    target = np.asarray(outcomes, dtype=int)
    if model.shape != market.shape or target.shape != model.shape:
        raise ValueError("probabilities and outcomes must align")
    model_brier = brier_score(model, target)
    market_brier = brier_score(market, target)
    return ValidationMetrics(
        sample_size=len(target),
        model_brier_score=model_brier,
        market_brier_score=market_brier,
        brier_skill_score=1.0 - model_brier / market_brier if market_brier > 0 else float("nan"),
        model_log_loss=binary_log_loss(model, target),
        market_log_loss=binary_log_loss(market, target),
        model_ece=expected_calibration_error(model, target),
        market_ece=expected_calibration_error(market, target),
    )


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    p = _probability_vector(probabilities)
    y = np.asarray(outcomes, dtype=float)
    if y.shape != p.shape or not np.all(np.isin(y, [0, 1])):
        raise ValueError("outcomes must be aligned and binary")
    return float(np.mean((p - y) ** 2))


def binary_log_loss(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    p = np.clip(_probability_vector(probabilities), EPS, 1.0 - EPS)
    y = np.asarray(outcomes, dtype=float)
    if y.shape != p.shape or not np.all(np.isin(y, [0, 1])):
        raise ValueError("outcomes must be aligned and binary")
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> float:
    p = _probability_vector(probabilities)
    y = np.asarray(outcomes, dtype=float)
    assignments = np.minimum(np.digitize(p, np.linspace(0, 1, bins + 1)[1:-1]), bins - 1)
    return float(sum(
        np.mean(assignments == i) * abs(np.mean(p[assignments == i]) - np.mean(y[assignments == i]))
        for i in range(bins) if np.any(assignments == i)
    ))


def binary_no_vig_probability(selection_odds: float, opposing_odds: float) -> float:
    _odds(selection_odds)
    _odds(opposing_odds)
    q1, q2 = 1.0 / selection_odds, 1.0 / opposing_odds
    return q1 / (q1 + q2)


def content_addressed_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = json.loads(_canonical(payload))
    digest = sha256(_canonical(normalized).encode()).hexdigest()
    return normalized | {
        "prediction_id": f"doctore_{digest[:24]}",
        "content_sha256": digest,
        "immutability": {
            "canonicalization": "json-sort-keys-utf8",
            "write_policy": "create-only-no-overwrite",
        },
    }


def write_immutable_json(path: str | Path, payload: Mapping[str, Any]) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical(payload) + "\n"
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    destination.chmod(0o444)
    return sha256(content.encode()).hexdigest()


def _historical_rows(actuals: np.ndarray, lines: np.ndarray, over_odds: np.ndarray, under_odds: np.ndarray, point: np.ndarray, config: WalkForwardConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    oos_indices = np.flatnonzero(np.isfinite(point))
    residuals = actuals[oos_indices] - point[oos_indices]
    raw: list[float] = []
    outcomes: list[int] = []
    market: list[float] = []
    source: list[int] = []
    for position in range(config.min_residual_history, len(oos_indices)):
        index = int(oos_indices[position])
        priced = empirical_line_probability(point[index], lines[index], residuals[:position], push_tolerance=config.push_tolerance)
        difference = actuals[index] - lines[index]
        if abs(difference) <= config.push_tolerance:
            continue
        raw.append(priced.over_conditional_non_push)
        outcomes.append(int(difference > 0))
        market.append(binary_no_vig_probability(over_odds[index], under_odds[index]))
        source.append(index)
    if len(raw) <= config.min_calibration_history:
        raise ValueError("insufficient non-push OOS rows")
    return np.asarray(raw), np.asarray(outcomes), np.asarray(market), np.asarray(source)


def _walk_forward_platt(raw: np.ndarray, outcomes: np.ndarray, minimum_history: int) -> tuple[np.ndarray, np.ndarray]:
    calibrated = np.full(len(raw), np.nan)
    mask = np.zeros(len(raw), dtype=bool)
    for i in range(minimum_history, len(raw)):
        if len(np.unique(outcomes[:i])) < 2:
            continue
        calibrated[i] = fit_platt_artifact(raw[:i], outcomes[:i], model_version="walk-forward-evaluation").predict(raw[i])
        mask[i] = True
    return calibrated, mask


def _xy(x: Sequence[Sequence[float]] | np.ndarray, y: Sequence[float] | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x_arr, y_arr = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x_arr.ndim != 2 or y_arr.ndim != 1 or len(x_arr) != len(y_arr) or len(y_arr) < 3:
        raise ValueError("x and y must be aligned finite arrays")
    if not np.all(np.isfinite(x_arr)) or not np.all(np.isfinite(y_arr)):
        raise ValueError("x and y must be finite")
    return x_arr, y_arr


def _vector(values: Sequence[float], n: int, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape != (n,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite aligned vector")
    return array


def _odds_vector(values: Sequence[float], n: int) -> np.ndarray:
    array = _vector(values, n, "odds")
    if np.any(array <= 1.0):
        raise ValueError("decimal odds must be greater than 1")
    return array


def _probability_vector(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) == 0 or not np.all(np.isfinite(array)) or np.any((array < 0) | (array > 1)):
        raise ValueError("probabilities must be a non-empty vector in [0,1]")
    return array


def _chronological_timestamps(values: Sequence[str], n: int) -> tuple[str, ...]:
    if len(values) != n:
        raise ValueError("timestamps must align")
    parsed = [_timestamp(value) for value in values]
    if any(current <= previous for previous, current in zip(parsed, parsed[1:])):
        raise ValueError("timestamps must be strictly increasing")
    return tuple(values)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _odds(value: float) -> None:
    if not math.isfinite(value) or value <= 1.0:
        raise ValueError("decimal odds must be finite and greater than 1")


def _logit(probability: float) -> float:
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0,1]")
    p = min(max(probability, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def _hash_model(model: Regressor) -> str:
    if hasattr(model, "get_booster"):
        return sha256(bytes(model.get_booster().save_raw(raw_format="json"))).hexdigest()  # type: ignore[attr-defined]
    return _hash_json(model.get_params()) if hasattr(model, "get_params") else sha256(repr(model).encode()).hexdigest()  # type: ignore[attr-defined]


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_json(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical(payload).encode()).hexdigest()
