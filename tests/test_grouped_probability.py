from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doctore_probability import WalkForwardConfig, expanding_walk_forward_predictions
from grouped_probability import (
    grouped_expanding_walk_forward_predictions,
    grouped_historical_rows,
    grouped_walk_forward_platt,
    validate_grouped_order,
)


class MeanRegressor:
    def fit(self, x: np.ndarray, y: np.ndarray) -> "MeanRegressor":
        self.value = float(np.mean(y))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value, dtype=float)


class GroupedWalkForwardTests(unittest.TestCase):
    def config(self) -> WalkForwardConfig:
        return WalkForwardConfig(
            min_train_size=2,
            test_size=1,
            min_residual_history=2,
            min_calibration_history=2,
            minimum_validation_sample=1,
        )

    def test_same_slate_second_row_cannot_benefit_from_first_row_target(self) -> None:
        x = np.arange(6, dtype=float).reshape(-1, 1)
        groups = ["a", "a", "b", "b", "c", "c"]
        first = np.asarray([0.0, 2.0, 100.0, 4.0, 5.0, 6.0])
        changed = np.asarray([0.0, 2.0, -100.0, 4.0, 5.0, 6.0])
        p1 = grouped_expanding_walk_forward_predictions(x, first, groups, self.config(), MeanRegressor)
        p2 = grouped_expanding_walk_forward_predictions(x, changed, groups, self.config(), MeanRegressor)
        self.assertEqual(p1[2], p1[3])
        self.assertEqual(p2[2], p2[3])
        self.assertEqual(p1[3], p2[3])
        self.assertNotEqual(p1[4], p2[4])

    def test_residual_history_is_frozen_within_group(self) -> None:
        timestamps = [
            "2026-07-01T12:00:00+00:00", "2026-07-01T12:00:00+00:00",
            "2026-07-02T12:00:00+00:00", "2026-07-02T12:00:00+00:00",
            "2026-07-03T12:00:00+00:00", "2026-07-03T12:00:00+00:00",
        ]
        groups = ["a", "a", "b", "b", "c", "c"]
        _, _, boundaries = validate_grouped_order(timestamps, groups, 6)
        actuals = np.asarray([0.0, 0.0, 3.0, 1.0, 3.0, 1.0])
        lines = np.asarray([2.5] * 6)
        odds = np.asarray([1.9] * 6)
        point = np.asarray([np.nan, np.nan, 2.0, 2.0, 2.0, 2.0])
        raw, _outcomes, _market, source, source_groups, history_sizes = grouped_historical_rows(
            actuals, lines, odds, odds, point, boundaries, self.config()
        )
        self.assertEqual([4, 5], source.tolist())
        self.assertEqual(["c", "c"], source_groups.tolist())
        self.assertEqual([2, 2], history_sizes.tolist())
        self.assertEqual(raw[0], raw[1])

    def test_platt_history_is_frozen_within_group(self) -> None:
        raw = np.asarray([0.3, 0.7, 0.6, 0.4, 0.65, 0.35])
        outcomes = np.asarray([0, 1, 1, 0, 1, 0])
        groups = ["a", "a", "b", "b", "c", "c"]
        calibrated, mask, history_sizes = grouped_walk_forward_platt(raw, outcomes, groups, minimum_history=2)
        self.assertEqual([0, 0, 2, 2, 4, 4], history_sizes.tolist())
        self.assertEqual([False, False, True, True, True, True], mask.tolist())
        self.assertTrue(np.all(np.isfinite(calibrated[mask])))

    def test_unique_groups_match_legacy_rowwise_walk_forward(self) -> None:
        x = np.arange(8, dtype=float).reshape(-1, 1)
        y = np.asarray([1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0])
        groups = [f"g{i}" for i in range(len(y))]
        legacy = expanding_walk_forward_predictions(x, y, self.config(), MeanRegressor)
        grouped = grouped_expanding_walk_forward_predictions(x, y, groups, self.config(), MeanRegressor)
        np.testing.assert_allclose(legacy, grouped, equal_nan=True)

    def test_non_contiguous_repeated_group_fails_closed(self) -> None:
        timestamps = [
            "2026-07-01T12:00:00+00:00",
            "2026-07-02T12:00:00+00:00",
            "2026-07-03T12:00:00+00:00",
        ]
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_grouped_order(timestamps, ["a", "b", "a"], 3)

    def test_grouped_timestamps_may_tie_but_not_reverse(self) -> None:
        tied = ["2026-07-01T12:00:00+00:00", "2026-07-01T12:00:00+00:00"]
        validate_grouped_order(tied, ["a", "a"], 2)
        with self.assertRaisesRegex(ValueError, "non-decreasing"):
            validate_grouped_order(
                ["2026-07-02T12:00:00+00:00", "2026-07-01T12:00:00+00:00"],
                ["a", "b"], 2,
            )


class GroupedManifestSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "contracts" / "training-dataset-manifest.schema.json").read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def manifest(self) -> dict:
        return {
            "schema_version": "doctore.training-dataset.v1",
            "dataset_id": "mlb-test",
            "dataset_version": "1",
            "sport": "MLB",
            "competition": "MLB",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "settlement_rules": "full_game_including_extra_innings",
            "target_definition": "home_runs + away_runs",
            "feature_schema_version": "mlb.total.v1",
            "created_at": "2026-07-01T00:00:00+00:00",
            "locked_at": "2026-07-01T00:00:00+00:00",
            "locked": True,
            "dataset_sha256": "a" * 64,
            "row_count": 10,
            "columns": ["f1", "target", "line", "over", "under", "ts", "slate"],
            "feature_columns": ["f1"],
            "target_column": "target",
            "line_column": "line",
            "over_odds_column": "over",
            "under_odds_column": "under",
            "timestamp_column": "ts",
            "sort_order": "timestamp_strictly_ascending"
        }

    def test_legacy_manifest_still_validates(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(self.manifest())))

    def test_grouped_manifest_requires_slate_column(self) -> None:
        manifest = self.manifest()
        manifest["sort_order"] = "timestamp_non_decreasing_grouped"
        errors = list(self.validator.iter_errors(manifest))
        self.assertTrue(any("slate_column" in error.message for error in errors))

    def test_grouped_manifest_with_slate_column_validates(self) -> None:
        manifest = self.manifest()
        manifest["sort_order"] = "timestamp_non_decreasing_grouped"
        manifest["slate_column"] = "slate"
        self.assertEqual([], list(self.validator.iter_errors(manifest)))


if __name__ == "__main__":
    unittest.main()
