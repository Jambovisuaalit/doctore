import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from src.doctore_probability import (
    WalkForwardConfig,
    binary_no_vig_probability,
    content_addressed_payload,
    default_xgb_factory,
    empirical_line_probability,
    expanding_walk_forward_predictions,
    fit_platt_artifact,
    fit_probability_pipeline,
    write_immutable_json,
)


class _LinearRegressor:
    def fit(self, x: np.ndarray, y: np.ndarray) -> "_LinearRegressor":
        design = np.column_stack([np.ones(len(x)), x])
        self.coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        design = np.column_stack([np.ones(len(x)), x])
        return design @ self.coefficients

    def get_params(self) -> dict[str, str]:
        return {"kind": "deterministic-linear-test-double"}


class DoctoreProbabilityTests(unittest.TestCase):
    def test_default_factory_builds_xgbregressor(self) -> None:
        x = np.arange(24, dtype=float).reshape(-1, 1)
        y = 1.5 * x[:, 0] + 2.0
        model = default_xgb_factory({"n_estimators": 3, "max_depth": 1})()
        model.fit(x, y)
        prediction = model.predict([[25.0]])
        self.assertEqual(prediction.shape, (1,))
        self.assertTrue(np.isfinite(prediction[0]))

    def test_walk_forward_predictions_are_strictly_oos(self) -> None:
        x = np.arange(30, dtype=float).reshape(-1, 1)
        y = 3.0 + 2.0 * x[:, 0]
        config = WalkForwardConfig(
            min_train_size=10,
            test_size=4,
            min_residual_history=2,
            min_calibration_history=2,
            minimum_validation_sample=2,
        )
        predictions = expanding_walk_forward_predictions(
            x, y, config, estimator_factory=_LinearRegressor
        )
        self.assertTrue(np.all(np.isnan(predictions[:10])))
        np.testing.assert_allclose(predictions[10:], y[10:], atol=1e-9)

    def test_empirical_cdf_prices_exact_line_and_push(self) -> None:
        result = empirical_line_probability(
            point_estimate=10.0,
            market_line=11.0,
            residuals=[-2.0, 0.0, 1.0, 2.0],
        )
        self.assertEqual(result.threshold_residual, 1.0)
        self.assertEqual(result.over, 0.25)
        self.assertEqual(result.under, 0.5)
        self.assertEqual(result.push, 0.25)
        self.assertAlmostEqual(result.over_conditional_non_push, 1.0 / 3.0)

    def test_platt_artifact_is_versioned_and_bounded(self) -> None:
        artifact = fit_platt_artifact(
            [0.15, 0.25, 0.4, 0.6, 0.75, 0.85],
            [0, 0, 0, 1, 1, 1],
            model_version="test-v1",
        )
        self.assertTrue(artifact.version.startswith("test-v1-platt-"))
        self.assertEqual(len(artifact.artifact_sha256), 64)
        self.assertGreater(artifact.predict(0.8), artifact.predict(0.2))

    def test_complete_pipeline_outputs_versioned_immutable_json(self) -> None:
        rng = np.random.default_rng(7)
        sample_size = 180
        feature_1 = np.linspace(-2.0, 2.0, sample_size)
        feature_2 = np.sin(np.linspace(0.0, 10.0, sample_size))
        x = np.column_stack([feature_1, feature_2])
        noise = rng.normal(0.0, 3.0, sample_size)
        y = 100.0 + 4.0 * feature_1 + 2.0 * feature_2 + noise
        lines = 100.0 + 3.5 * feature_1 + rng.normal(0.0, 1.5, sample_size)
        over_odds = np.full(sample_size, 1.95)
        under_odds = np.full(sample_size, 1.95)
        timestamps = [
            f"2026-01-{1 + index // 24:02d}T{index % 24:02d}:00:00+00:00"
            for index in range(sample_size)
        ]
        config = WalkForwardConfig(
            min_train_size=60,
            test_size=10,
            min_residual_history=20,
            min_calibration_history=30,
            minimum_validation_sample=20,
        )
        fitted = fit_probability_pipeline(
            x,
            y,
            lines,
            over_odds,
            under_odds,
            timestamps,
            model_name="doctore-test-regressor",
            model_version="1.0.0",
            feature_schema_version="test-features-v1",
            config=config,
            estimator_factory=_LinearRegressor,
        )
        self.assertGreater(fitted.validation_metrics.sample_size, 0)
        self.assertEqual(len(fitted.model_artifact_sha256), 64)
        self.assertEqual(len(fitted.residual_artifact_sha256), 64)

        payload = fitted.predict_exact_line(
            [0.25, 0.5],
            event_id="TEST-001",
            sport="NBA",
            market_type="game_total",
            period="full_game_including_overtime",
            selection="over",
            market_line=101.5,
            selection_odds_decimal=1.95,
            opposing_odds_decimal=1.95,
            market_snapshot_at="2026-07-23T10:00:00+00:00",
            feature_cutoff_at="2026-07-23T09:59:00+00:00",
            prediction_generated_at="2026-07-23T10:00:01+00:00",
            book="Pinnacle",
        )
        self.assertEqual(payload["output_schema_version"], "doctore-prediction-v2.0.0")
        self.assertEqual(len(payload["content_sha256"]), 64)
        self.assertTrue(payload["prediction_id"].startswith("doctore_"))
        probabilities = payload["calibration"]
        total = (
            probabilities["probability_selected_calibrated"]
            + probabilities["probability_opposing_calibrated"]
            + probabilities["probability_push"]
        )
        self.assertAlmostEqual(total, 1.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.json"
            first_hash = write_immutable_json(path, payload)
            self.assertEqual(len(first_hash), 64)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["content_sha256"], payload["content_sha256"])
            with self.assertRaises(FileExistsError):
                write_immutable_json(path, payload)

    def test_content_address_is_deterministic(self) -> None:
        first = content_addressed_payload({"b": 2, "a": 1})
        second = content_addressed_payload({"a": 1, "b": 2})
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first["prediction_id"], second["prediction_id"])

    def test_binary_no_vig_probability(self) -> None:
        self.assertAlmostEqual(binary_no_vig_probability(2.10, 1.75), 0.4545454545454546)


if __name__ == "__main__":
    unittest.main()
