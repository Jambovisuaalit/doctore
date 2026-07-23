#!/usr/bin/env python3
"""Train and validate the Doctore XGBRegressor probability pipeline from CSV."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from src.doctore_probability import (
    WalkForwardConfig,
    fit_probability_pipeline,
    write_immutable_json,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run expanding walk-forward XGBRegressor validation, empirical residual "
            "CDF pricing, Platt calibration, and market-baseline scoring."
        )
    )
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--features", required=True, help="Comma-separated feature columns")
    parser.add_argument("--target", required=True)
    parser.add_argument("--line", required=True)
    parser.add_argument("--over-odds", required=True)
    parser.add_argument("--under-odds", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--feature-schema-version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--min-train-size", required=True, type=int)
    parser.add_argument("--test-size", type=int, default=1)
    parser.add_argument("--min-residual-history", type=int, default=100)
    parser.add_argument("--min-calibration-history", type=int, default=200)
    parser.add_argument("--minimum-validation-sample", type=int, default=200)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--max-depth", type=int, default=4)
    return parser.parse_args()


def _read_csv(
    path: Path,
    feature_columns: Sequence[str],
    target_column: str,
    line_column: str,
    over_odds_column: str,
    under_odds_column: str,
    timestamp_column: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = set(feature_columns) | {
            target_column,
            line_column,
            over_odds_column,
            under_odds_column,
            timestamp_column,
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        rows.extend(reader)
    if not rows:
        raise ValueError("CSV contains no data rows")

    x = np.asarray(
        [[float(row[column]) for column in feature_columns] for row in rows],
        dtype=float,
    )
    target = np.asarray([float(row[target_column]) for row in rows], dtype=float)
    lines = np.asarray([float(row[line_column]) for row in rows], dtype=float)
    over_odds = np.asarray([float(row[over_odds_column]) for row in rows], dtype=float)
    under_odds = np.asarray([float(row[under_odds_column]) for row in rows], dtype=float)
    timestamps = [row[timestamp_column] for row in rows]
    return x, target, lines, over_odds, under_odds, timestamps


def main() -> None:
    args = _parse_args()
    features = [column.strip() for column in args.features.split(",") if column.strip()]
    if not features:
        raise ValueError("at least one feature column is required")
    if args.output_dir.exists():
        raise FileExistsError(
            f"output directory already exists; immutable build refused: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True)

    x, target, lines, over_odds, under_odds, timestamps = _read_csv(
        args.csv,
        features,
        args.target,
        args.line,
        args.over_odds,
        args.under_odds,
        args.timestamp,
    )
    config = WalkForwardConfig(
        min_train_size=args.min_train_size,
        test_size=args.test_size,
        min_residual_history=args.min_residual_history,
        min_calibration_history=args.min_calibration_history,
        minimum_validation_sample=args.minimum_validation_sample,
    )
    fitted = fit_probability_pipeline(
        x,
        target,
        lines,
        over_odds,
        under_odds,
        timestamps,
        model_name=args.model_name,
        model_version=args.model_version,
        feature_schema_version=args.feature_schema_version,
        config=config,
        xgb_params={
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
        },
    )

    model_path = args.output_dir / "xgb-model.json"
    fitted.model.save_model(model_path)  # type: ignore[attr-defined]
    model_path.chmod(0o444)
    write_immutable_json(
        args.output_dir / "residual-distribution.json",
        {
            "model_version": fitted.model_version,
            "residual_distribution_version": fitted.residual_distribution_version,
            "artifact_sha256": fitted.residual_artifact_sha256,
            "method": "expanding_walk_forward_oos",
            "residuals": list(fitted.residuals),
        },
    )
    write_immutable_json(
        args.output_dir / "platt-calibrator.json",
        asdict(fitted.calibrator),
    )
    write_immutable_json(
        args.output_dir / "validation-report.json",
        {
            "model_name": fitted.model_name,
            "model_version": fitted.model_version,
            "model_artifact_sha256": fitted.model_artifact_sha256,
            "feature_schema_version": fitted.feature_schema_version,
            "calibration_status": fitted.calibration_status,
            "validation_period_start": fitted.validation_period_start,
            "validation_period_end": fitted.validation_period_end,
            "metrics": asdict(fitted.validation_metrics),
            "config": asdict(fitted.config),
        },
    )
    manifest = {
        "model": str(model_path.name),
        "residuals": "residual-distribution.json",
        "calibrator": "platt-calibrator.json",
        "validation": "validation-report.json",
        "calibration_status": fitted.calibration_status,
    }
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
