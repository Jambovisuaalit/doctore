from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doctore_probability import WalkForwardConfig
from grouped_ablation import AblationError, build_cumulative_stages, run_grouped_oos_ablation


class MeanRegressor:
    def fit(self, x: np.ndarray, y: np.ndarray) -> "MeanRegressor":
        self.value = float(np.mean(y))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value, dtype=float)


class GroupedAblationTests(unittest.TestCase):
    def config(self) -> WalkForwardConfig:
        return WalkForwardConfig(
            min_train_size=2,
            test_size=1,
            min_residual_history=2,
            min_calibration_history=2,
            minimum_validation_sample=1,
        )

    def test_stages_are_cumulative(self) -> None:
        stages = build_cumulative_stages(
            {"baseline": ["a", "b"], "park": ["c"]},
            ["baseline", "park"],
        )
        self.assertEqual("baseline", stages[0][0])
        self.assertEqual(("a", "b"), stages[0][2])
        self.assertEqual("baseline+park", stages[1][0])
        self.assertEqual(("a", "b", "c"), stages[1][2])

    def test_overlap_fails_closed(self) -> None:
        with self.assertRaisesRegex(AblationError, "overlap"):
            build_cumulative_stages(
                {"baseline": ["a"], "park": ["a"]},
                ["baseline", "park"],
            )

    def test_nonfinite_future_group_fails_preflight(self) -> None:
        n = 12
        with self.assertRaisesRegex(AblationError, "non-finite"):
            run_grouped_oos_ablation(
                feature_values={
                    "baseline": np.arange(n, dtype=float),
                    "park": np.asarray([1.0] * 11 + [np.nan]),
                },
                feature_groups={"baseline": ["baseline"], "park": ["park"]},
                group_order=["baseline", "park"],
                target=np.asarray([0.0, 4.0] * 6),
                market_lines=np.asarray([2.0] * n),
                over_odds_decimal=np.asarray([1.91] * n),
                under_odds_decimal=np.asarray([1.91] * n),
                timestamps=[f"2026-07-{1 + i // 2:02d}T12:00:00+00:00" for i in range(n)],
                groups=[f"g{i // 2}" for i in range(n)],
                config=self.config(),
                estimator_factory=MeanRegressor,
            )

    def test_all_stages_share_identical_evaluation_cohort(self) -> None:
        n = 16
        report = run_grouped_oos_ablation(
            feature_values={
                "baseline_x": np.arange(n, dtype=float),
                "park_x": np.linspace(0.0, 1.0, n),
            },
            feature_groups={"baseline": ["baseline_x"], "park": ["park_x"]},
            group_order=["baseline", "park"],
            target=np.asarray([0.0, 4.0] * 8),
            market_lines=np.asarray([2.0] * n),
            over_odds_decimal=np.asarray([1.91] * n),
            under_odds_decimal=np.asarray([1.91] * n),
            timestamps=[f"2026-07-{1 + i // 2:02d}T12:00:00+00:00" for i in range(n)],
            groups=[f"g{i // 2}" for i in range(n)],
            config=self.config(),
            estimator_factory=MeanRegressor,
        )
        self.assertTrue(report["fixed_evaluation_cohort"])
        self.assertEqual(2, len(report["stages"]))
        self.assertEqual(
            report["stages"][0]["evaluation_sample_size"],
            report["stages"][1]["evaluation_sample_size"],
        )
        self.assertEqual(
            report["stages"][0]["metrics"]["model_brier_score"],
            report["stages"][1]["metrics"]["model_brier_score"],
        )
        self.assertEqual("INCREMENTAL_FAIL", report["stages"][1]["incremental_status"])


if __name__ == "__main__":
    unittest.main()
