from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import numpy as np

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_canonical_dataset import (
    OddsRow,
    ScheduleGame,
    american_to_decimal,
    build_canonical_rows,
    join_odds_to_schedule,
)
from doctore_probability import WalkForwardConfig
from doctore_probability_grouped import expanding_walk_forward_predictions_grouped


class MeanRegressor:
    def fit(self, x, y):
        self.value = float(np.mean(y))
        return self
    def predict(self, x):
        return np.full(len(x), self.value)
    def get_params(self):
        return {"kind": "mean"}


class CanonicalDatasetTests(unittest.TestCase):
    def test_american_odds(self):
        self.assertAlmostEqual(american_to_decimal(-120), 1.833333333333)
        self.assertEqual(american_to_decimal(100), 2.0)

    def test_exact_schedule_join_uses_team_and_game_number(self):
        d = date(2021, 7, 19)
        odds = [
            OddsRow(d, "V", 112, "CHC", 1, 8.5, 1.9, 1.8, 2),
            OddsRow(d, "H", 138, "STL", 1, 8.5, 1.9, 1.8, 5),
            OddsRow(d, "V", 121, "NYM", 1, 11.0, 1.9, 1.8, 3),
            OddsRow(d, "H", 113, "CIN", 1, 11.0, 1.9, 1.8, 4),
        ]
        games = [
            ScheduleGame(1, d, "2021-07-19T23:00:00Z", 112, 138, 3, 8, 1, 9, "Final"),
            ScheduleGame(2, d, "2021-07-19T23:10:00Z", 121, 113, 15, 11, 1, 9, "Final"),
        ]
        joined, audit = join_odds_to_schedule(odds, games)
        self.assertEqual([item.game.game_pk for item in joined], [1, 2])
        self.assertEqual([item.total_line for item in joined], [8.5, 11.0])
        self.assertEqual(audit["unmatched_odds_source_lines"], [])

    def test_contradictory_two_sided_market_is_rejected(self):
        d = date(2021, 7, 19)
        odds = [
            OddsRow(d, "V", 112, "CHC", 1, 8.5, 1.9, 1.8, 2),
            OddsRow(d, "H", 138, "STL", 1, 9.0, 1.9, 1.8, 3),
        ]
        game = ScheduleGame(1, d, "2021-07-19T23:00:00Z", 112, 138, 3, 8, 1, 9, "Final")
        joined, audit = join_odds_to_schedule(odds, [game])
        self.assertEqual(joined, [])
        self.assertIn("TOTAL_LINE_CONTRADICTION", audit["rejected_games"][0]["reasons"])

    def test_grouped_walk_forward_never_trains_on_same_timestamp(self):
        x = np.arange(8, dtype=float).reshape(-1, 1)
        y = np.array([1, 1, 10, 10, 20, 20, 30, 30], dtype=float)
        timestamps = [
            "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
            "2026-01-03T00:00:00+00:00", "2026-01-03T00:00:00+00:00",
            "2026-01-04T00:00:00+00:00", "2026-01-04T00:00:00+00:00",
        ]
        config = WalkForwardConfig(
            min_train_size=2, min_residual_history=2,
            min_calibration_history=2, minimum_validation_sample=1,
        )
        predictions = expanding_walk_forward_predictions_grouped(
            x, y, timestamps, config, MeanRegressor
        )
        self.assertTrue(np.isnan(predictions[:2]).all())
        np.testing.assert_allclose(predictions[2:4], [1.0, 1.0])
        np.testing.assert_allclose(predictions[4:6], [5.5, 5.5])

    def test_unpriced_schedule_games_enter_future_history(self):
        from mlb_canonical_dataset import JoinedGame
        from mlb_canonical_dataset_history import build_canonical_rows_with_schedule
        schedule = []
        for day in range(1, 22):
            d = date(2021, 4, day)
            schedule.append(ScheduleGame(
                day, d, f"2021-04-{day:02d}T18:00:00Z",
                112, 138, 4, 3, 1, 9, "Final",
            ))
        joined = [JoinedGame(schedule[-1], 8.0, 1.91, 1.91, 100, 101)]
        rows, audit = build_canonical_rows_with_schedule(joined, schedule)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["away_games_prior"], 20.0)
        self.assertEqual(rows[0]["home_games_prior"], 20.0)
        self.assertEqual(audit["authoritative_history_games_used"], 21)

    def test_same_day_results_are_not_added_mid_group(self):
        joined = []
        for day in range(1, 21):
            d = date(2021, 4, day)
            game = ScheduleGame(day, d, f"2021-04-{day:02d}T18:00:00Z", 112, 138, 4, 3, 1, 9, "Final")
            from mlb_canonical_dataset import JoinedGame
            joined.append(JoinedGame(game, 8.0, 1.91, 1.91, day * 2, day * 2 + 1))
        from mlb_canonical_dataset import JoinedGame
        d = date(2021, 4, 21)
        joined.extend([
            JoinedGame(ScheduleGame(100, d, "2021-04-21T17:00:00Z", 112, 138, 20, 0, 1, 9, "Final"), 8.0, 1.91, 1.91, 100, 101),
            JoinedGame(ScheduleGame(101, d, "2021-04-21T22:00:00Z", 112, 138, 0, 20, 2, 9, "Final"), 8.0, 1.91, 1.91, 102, 103),
        ])
        rows, _ = build_canonical_rows(joined)
        same_day = [row for row in rows if row["official_date"] == "2021-04-21"]
        self.assertEqual(len(same_day), 2)
        self.assertEqual(same_day[0]["away_games_prior"], 20.0)
        self.assertEqual(same_day[1]["away_games_prior"], 20.0)
        self.assertEqual(same_day[0]["away_rolling5_runs_for"], same_day[1]["away_rolling5_runs_for"])


if __name__ == "__main__":
    unittest.main()
