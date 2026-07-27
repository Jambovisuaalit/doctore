from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doctore_probability import WalkForwardConfig
from production_artifact_pipeline import PipelineInputError, run_production_pipeline


class ProductionArtifactPipelineTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _fixtures(self, directory: Path) -> dict[str, Path]:
        rng = np.random.default_rng(17)
        columns = ["timestamp", "f1", "f2", "final_total", "market_line", "over_odds", "under_odds"]
        csv_path = directory / "mlb-training.csv"
        rows = []
        for index in range(180):
            f1 = -1.5 + 3.0 * index / 179
            f2 = float(np.sin(index / 11.0))
            final_total = 8.4 + 1.2 * f1 + 0.6 * f2 + rng.normal(0.0, 1.1)
            market_line = 8.2 + 0.9 * f1 + rng.normal(0.0, 0.45)
            rows.append(
                {
                    "timestamp": f"2026-01-{1 + index // 24:02d}T{index % 24:02d}:00:00+00:00",
                    "f1": f1,
                    "f2": f2,
                    "final_total": final_total,
                    "market_line": market_line,
                    "over_odds": 1.95,
                    "under_odds": 1.95,
                }
            )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        dataset_sha = sha256(csv_path.read_bytes()).hexdigest()

        manifest_path = directory / "dataset-manifest.json"
        self._write_json(
            manifest_path,
            {
                "schema_version": "doctore.training-dataset.v1",
                "dataset_id": "mlb-full-game-totals-test",
                "dataset_version": "test-1.0.0",
                "sport": "MLB",
                "competition": "MLB",
                "market_type": "total",
                "target_market": "full_game_total",
                "period": "full_game",
                "settlement_rules": "including_extra_innings_push_on_exact_integer_line",
                "target_definition": "final home runs plus final away runs",
                "feature_schema_version": "mlb.full-game-total.test.v1",
                "created_at": "2026-07-27T17:00:00+00:00",
                "locked_at": "2026-07-27T17:01:00+00:00",
                "locked": True,
                "dataset_sha256": dataset_sha,
                "row_count": len(rows),
                "columns": columns,
                "feature_columns": ["f1", "f2"],
                "target_column": "final_total",
                "line_column": "market_line",
                "over_odds_column": "over_odds",
                "under_odds_column": "under_odds",
                "timestamp_column": "timestamp",
                "sort_order": "timestamp_strictly_ascending",
            },
        )

        event_id = "MLB-2026-07-27-SEA-TEX"
        market_id = event_id + "-TOTAL-8-OVER"
        live_path = directory / "live-features.json"
        self._write_json(
            live_path,
            {
                "schema_version": "doctore.live-features.v1",
                "event_id": event_id,
                "feature_schema_version": "mlb.full-game-total.test.v1",
                "feature_cutoff_at": "2026-07-27T17:55:00+00:00",
                "features": {"f1": 0.25, "f2": 0.5},
            },
        )
        market_path = directory / "market.json"
        self._write_json(
            market_path,
            {
                "schema_version": "doctore.market-snapshot.v1",
                "event_id": event_id,
                "market_id": market_id,
                "book": "Pinnacle",
                "book_market_id": "1632709835",
                "captured_at": "2026-07-27T17:56:00+00:00",
                "event_start_at": "2026-07-27T18:35:00+00:00",
                "sport": "MLB",
                "competition": "MLB",
                "market_type": "total",
                "target_market": "full_game_total",
                "period": "full_game",
                "line": 8.0,
                "settlement_rules": "including_extra_innings_push_on_exact_integer_line",
                "selection": "over",
                "decimal_odds": 1.943,
                "market_status": "open",
                "is_complete": True,
                "outcomes": [
                    {"selection": "over", "decimal_odds": 1.943},
                    {"selection": "under", "decimal_odds": 1.943},
                ],
                "correlation_group": event_id,
                "source": "synthetic-test",
            },
        )
        portfolio_path = directory / "portfolio.json"
        self._write_json(
            portfolio_path,
            {
                "schema_version": "doctore.portfolio-state.v1",
                "portfolio_id": "primary-eur",
                "captured_at": "2026-07-27T17:57:00+00:00",
                "currency": "EUR",
                "bankroll": 50000.0,
                "available_balance": 40000.0,
                "stake_increment": 1.0,
                "league": "MLB",
                "correlation_group": event_id,
                "drawdown_fraction": 0.04,
                "open_positions_count": 0,
                "exposures": {
                    "open_amount": 0.0,
                    "daily_turnover_amount": 0.0,
                    "league_amount": 0.0,
                    "rolling_3d_turnover_amount": 0.0,
                    "correlation_group_amount": 0.0,
                },
            },
        )
        policy_path = directory / "policy.json"
        self._write_json(
            policy_path,
            {
                "schema_version": "doctore.risk-policy.v1",
                "policy_id": "doctore-test",
                "policy_version": "2026.07.27",
                "minimum_ev": 0.03,
                "minimum_edge_probability_points": 0.015,
                "minimum_stake": 1.0,
                "allowed_calibration_statuses": ["validated", "uncalibrated"],
                "kelly_fraction": {"validated": 0.25, "uncalibrated": 0.10, "unknown": 0},
                "sizing_model_weight": {"validated": 0.85, "uncalibrated": 0.35, "unknown": 0},
                "caps": {
                    "max_stake_fraction_per_bet": 0.02,
                    "max_open_exposure_fraction": 0.10,
                    "max_daily_turnover_fraction": 0.25,
                    "max_league_exposure_fraction": 0.15,
                    "max_rolling_3d_turnover_fraction": 0.40,
                    "max_correlation_group_fraction": 0.04,
                },
                "freshness_seconds": {
                    "market_snapshot": 300,
                    "portfolio_state": 60,
                    "model_output": 1800,
                    "mlb_context": 900,
                },
                "drawdown": {
                    "warning_fraction": 0.10,
                    "review_fraction": 0.15,
                    "pause_fraction": 0.20,
                },
                "human_approval_required": True,
                "block_unknown_correlation": True,
            },
        )
        context_path = directory / "mlb-context.json"
        self._write_json(
            context_path,
            {
                "schema_version": "doctore.mlb-context.v1",
                "event_id": event_id,
                "captured_at": "2026-07-27T17:56:30+00:00",
                "settlement": {"pitcher_rule": "action", "listed_pitchers_match": None},
                "starters": {
                    "home": {"name": "Starter A", "status": "confirmed"},
                    "away": {"name": "Starter B", "status": "confirmed"},
                },
                "lineups": {"home": "confirmed_compatible", "away": "confirmed_compatible"},
                "bullpen": {"home": "current", "away": "current"},
                "environment": {
                    "roof_matches_model": True,
                    "weather_matches_model": True,
                    "umpire_matches_model": None,
                },
                "model_dependencies": {
                    "requires_confirmed_starters": True,
                    "requires_lineup_compatibility": True,
                    "requires_bullpen_state": True,
                    "uses_roof": True,
                    "uses_weather": True,
                    "uses_umpire": False,
                },
            },
        )
        return {
            "csv": csv_path,
            "manifest": manifest_path,
            "live": live_path,
            "market": market_path,
            "portfolio": portfolio_path,
            "policy": policy_path,
            "context": context_path,
        }

    def test_training_manifest_schema_is_valid(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "training-dataset-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)

    def test_complete_pipeline_creates_schema_valid_immutable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fixture = self._fixtures(directory)
            output = directory / "artifacts"
            result = run_production_pipeline(
                csv_path=fixture["csv"],
                dataset_manifest_path=fixture["manifest"],
                live_features_path=fixture["live"],
                market_snapshot_path=fixture["market"],
                portfolio_state_path=fixture["portfolio"],
                risk_policy_path=fixture["policy"],
                mlb_context_path=fixture["context"],
                output_dir=output,
                model_name="doctore-mlb-total-test",
                model_version="test-1.0.0",
                prediction_generated_at="2026-07-27T17:58:00+00:00",
                evaluated_at="2026-07-27T17:58:30+00:00",
                config=WalkForwardConfig(
                    min_train_size=60,
                    test_size=10,
                    min_residual_history=20,
                    min_calibration_history=30,
                    minimum_validation_sample=20,
                ),
                xgb_params={"n_estimators": 5, "max_depth": 2, "learning_rate": 0.1},
            )
            self.assertIn(result["decision"], {"BET", "WATCH", "PASS", "BLOCKED"})
            expected = {
                "xgb-model.json",
                "residual-distribution.json",
                "platt-calibrator.json",
                "validation-report.json",
                "rich-prediction.json",
                "canonical-model-output.json",
                "canonical-model-output.sha256",
                "decision-output.json",
                "run-manifest.json",
            }
            self.assertEqual(expected, {path.name for path in output.iterdir()})
            canonical = json.loads((output / "canonical-model-output.json").read_text())
            self.assertEqual(canonical["schema_version"], "doctore.model-output.v1")
            self.assertEqual(canonical["training_data_version"], "test-1.0.0")
            self.assertEqual(len((output / "canonical-model-output.sha256").read_text().strip()), 64)
            with self.assertRaises(FileExistsError):
                run_production_pipeline(
                    csv_path=fixture["csv"],
                    dataset_manifest_path=fixture["manifest"],
                    live_features_path=fixture["live"],
                    market_snapshot_path=fixture["market"],
                    portfolio_state_path=fixture["portfolio"],
                    risk_policy_path=fixture["policy"],
                    mlb_context_path=fixture["context"],
                    output_dir=output,
                    model_name="doctore-mlb-total-test",
                    model_version="test-1.0.0",
                    prediction_generated_at="2026-07-27T17:58:00+00:00",
                    evaluated_at="2026-07-27T17:58:30+00:00",
                    config=WalkForwardConfig(60, 10, 20, 30, 20),
                )

    def test_tampered_dataset_is_rejected_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fixture = self._fixtures(directory)
            with fixture["csv"].open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(PipelineInputError, "SHA-256 mismatch"):
                run_production_pipeline(
                    csv_path=fixture["csv"],
                    dataset_manifest_path=fixture["manifest"],
                    live_features_path=fixture["live"],
                    market_snapshot_path=fixture["market"],
                    portfolio_state_path=fixture["portfolio"],
                    risk_policy_path=fixture["policy"],
                    mlb_context_path=fixture["context"],
                    output_dir=directory / "artifacts",
                    model_name="doctore-mlb-total-test",
                    model_version="test-1.0.0",
                    prediction_generated_at="2026-07-27T17:58:00+00:00",
                    evaluated_at="2026-07-27T17:58:30+00:00",
                    config=WalkForwardConfig(60, 10, 20, 30, 20),
                )


if __name__ == "__main__":
    unittest.main()
