#!/usr/bin/env python3
"""Run the grouped MLB dataset through model, schema and decision artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doctore_probability import WalkForwardConfig
from grouped_production_artifact_pipeline import run_grouped_production_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--live-features", required=True, type=Path)
    parser.add_argument("--market-snapshot", required=True, type=Path)
    parser.add_argument("--portfolio-state", required=True, type=Path)
    parser.add_argument("--risk-policy", required=True, type=Path)
    parser.add_argument("--mlb-context", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--prediction-generated-at", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--min-train-size", required=True, type=int)
    parser.add_argument("--min-residual-history", type=int, default=100)
    parser.add_argument("--min-calibration-history", type=int, default=200)
    parser.add_argument("--minimum-validation-sample", type=int, default=200)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--max-depth", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_grouped_production_pipeline(
        csv_path=args.csv,
        dataset_manifest_path=args.dataset_manifest,
        live_features_path=args.live_features,
        market_snapshot_path=args.market_snapshot,
        portfolio_state_path=args.portfolio_state,
        risk_policy_path=args.risk_policy,
        mlb_context_path=args.mlb_context,
        output_dir=args.output_dir,
        model_name=args.model_name,
        model_version=args.model_version,
        prediction_generated_at=args.prediction_generated_at,
        evaluated_at=args.evaluated_at,
        config=WalkForwardConfig(
            min_train_size=args.min_train_size,
            test_size=1,
            min_residual_history=args.min_residual_history,
            min_calibration_history=args.min_calibration_history,
            minimum_validation_sample=args.minimum_validation_sample,
        ),
        xgb_params={
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
