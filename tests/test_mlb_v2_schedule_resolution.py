from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v2_schedule_resolution import normalize_schedule_games_v3


class MlbV2ScheduleResolutionTests(unittest.TestCase):
    def row(self, *, status_code: str, detailed_state: str, game_pk: int = 1) -> dict:
        return {
            "gamePk": game_pk,
            "gameType": "R",
            "gameDate": "2012-05-01T23:00:00Z",
            "officialDate": "2012-05-01",
            "scheduledInnings": 9,
            "status": {
                "statusCode": status_code,
                "codedGameState": status_code,
                "detailedState": detailed_state,
            },
            "venue": {"id": 10, "name": "Test Park"},
            "teams": {
                "away": {"team": {"id": 1}, "score": 2},
                "home": {"team": {"id": 2}, "score": 1},
            },
        }

    def payload(self, *rows: dict) -> dict:
        return {"dates": [{"games": list(rows)}]}

    def test_explicit_fr_completed_early_is_domain_exclusion(self) -> None:
        games, exclusions, stats = normalize_schedule_games_v3(
            self.payload(self.row(status_code="FR", detailed_state="Completed Early: Rain")),
            2012,
        )
        self.assertEqual([], games)
        self.assertEqual(1, len(exclusions))
        self.assertEqual("COMPLETED_EARLY_DOMAIN", exclusions[0]["reason"])
        self.assertEqual("FR", exclusions[0]["status_code"])
        self.assertEqual("Completed Early: Rain", exclusions[0]["detailed_state"])
        self.assertEqual(1, stats["completed_early_domain_exclusions"])
        self.assertEqual(1, stats["known_domain_exclusions"])
        self.assertEqual(0, stats["unresolved_no_strict_played_final"])

    def test_bare_fr_remains_unresolved_fail_closed(self) -> None:
        games, exclusions, stats = normalize_schedule_games_v3(
            self.payload(self.row(status_code="FR", detailed_state="Final")),
            2012,
        )
        self.assertEqual([], games)
        self.assertEqual("NO_STRICT_PLAYED_FINAL_ROW", exclusions[0]["reason"])
        self.assertEqual(0, stats["completed_early_domain_exclusions"])
        self.assertEqual(1, stats["unresolved_no_strict_played_final"])

    def test_completed_early_text_without_fr_is_not_reclassified(self) -> None:
        games, exclusions, stats = normalize_schedule_games_v3(
            self.payload(self.row(status_code="DI", detailed_state="Completed Early: Rain")),
            2012,
        )
        self.assertEqual([], games)
        self.assertEqual("NO_STRICT_PLAYED_FINAL_ROW", exclusions[0]["reason"])
        self.assertEqual(0, stats["completed_early_domain_exclusions"])

    def test_regular_final_stays_candidate(self) -> None:
        games, exclusions, stats = normalize_schedule_games_v3(
            self.payload(self.row(status_code="F", detailed_state="Final")),
            2012,
        )
        self.assertEqual(1, len(games))
        self.assertEqual([], exclusions)
        self.assertEqual(0, stats["completed_early_domain_exclusions"])

    def test_completed_early_outside_requested_season_is_not_reclassified(self) -> None:
        row = self.row(status_code="FR", detailed_state="Completed Early: Rain")
        row["officialDate"] = "2011-09-01"
        games, exclusions, stats = normalize_schedule_games_v3(self.payload(row), 2012)
        self.assertEqual([], games)
        self.assertEqual("NO_STRICT_PLAYED_FINAL_ROW", exclusions[0]["reason"])
        self.assertEqual(0, stats["completed_early_domain_exclusions"])


if __name__ == "__main__":
    unittest.main()
