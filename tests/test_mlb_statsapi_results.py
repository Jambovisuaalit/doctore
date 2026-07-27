from __future__ import annotations

import unittest
from src.mlb_statsapi_results import schedule_to_result_rows


class MLBStatsAPIResultsTests(unittest.TestCase):
    def test_final_regular_season_game_maps_to_result_contract(self) -> None:
        payload = {
            "dates": [{
                "date": "2021-07-01",
                "games": [{
                    "gamePk": 123,
                    "gameType": "R",
                    "officialDate": "2021-07-01",
                    "gameDate": "2021-07-01T23:10:00Z",
                    "gameNumber": 1,
                    "status": {"detailedState": "Final"},
                    "teams": {
                        "away": {"team": {"id": 147}, "score": 3},
                        "home": {"team": {"id": 111}, "score": 4}
                    }
                }]
            }]
        }
        rows = schedule_to_result_rows(payload)
        self.assertEqual(rows, [{
            "source_game_id": "123",
            "game_date": "2021-07-01",
            "game_number": 1,
            "away_team": "NYY",
            "home_team": "BOS",
            "away_runs": 3,
            "home_runs": 4,
            "event_start_at": "2021-07-01T23:10:00+00:00",
            "status": "final",
        }])

    def test_non_final_or_non_regular_game_is_excluded(self) -> None:
        payload = {"dates": [{"date": "2021-07-01", "games": [
            {"gamePk": 1, "gameType": "S", "status": {"detailedState": "Final"}},
            {"gamePk": 2, "gameType": "R", "status": {"detailedState": "Scheduled"}},
        ]}]}
        self.assertEqual(schedule_to_result_rows(payload), [])


if __name__ == "__main__":
    unittest.main()
