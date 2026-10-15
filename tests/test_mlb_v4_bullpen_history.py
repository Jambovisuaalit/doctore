from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v4_bullpen_history import (
    BullpenHistorySupplementError, authoritative_played_domain_game,
    normalize_bullpen_history_source,
)


class BullpenHistorySupplementTests(unittest.TestCase):
    def live(self, *, game_pk=1, status="F", detailed="Final", innings=7, away=3, home=2):
        return {
            "gamePk": game_pk,
            "gameData": {
                "game": {"pk": game_pk, "type": "R"},
                "status": {"statusCode": status, "codedGameState": status, "detailedState": detailed},
                "datetime": {"officialDate": "2020-08-09", "dateTime": "2020-08-09T17:00:00Z"},
                "venue": {"id": 10, "name": "Park"},
                "teams": {"away": {"id": 1}, "home": {"id": 2}},
            },
            "liveData": {"linescore": {
                "scheduledInnings": innings,
                "teams": {"away": {"runs": away}, "home": {"runs": home}},
            }},
        }

    def team_box(self, team_id):
        return {
            "team": {"id": team_id},
            "pitchers": [101, 102],
            "players": {
                "ID101": {"stats": {"pitching": {"gamesStarted": 1, "gamesPitched": 1, "pitchesThrown": 80}}},
                "ID102": {"stats": {"pitching": {"gamesStarted": 0, "gamesPitched": 1, "pitchesThrown": 20}}},
            },
        }

    def test_non_nine_final_is_bullpen_history_eligible(self):
        game, reason = authoritative_played_domain_game(self.live(), expected_game_pk=1, expected_season=2020)
        self.assertEqual("NON_NINE_INNING_DOMAIN", reason)
        self.assertEqual(7, game["scheduled_innings"])

    def test_cancelled_is_proven_unplayed_not_history(self):
        game, reason = authoritative_played_domain_game(
            self.live(status="CI", detailed="Cancelled: Inclement Weather", innings=9),
            expected_game_pk=1, expected_season=2020,
        )
        self.assertIsNone(game)
        self.assertEqual("CANCELLED_UNPLAYED_DOMAIN", reason)

    def test_completed_early_and_tied_are_played_history(self):
        for status, detailed, expected in [(
            "FO", "Completed Early", "COMPLETED_EARLY_DOMAIN"
        ), (
            "FT", "Final: Tied", "TIED_FINAL_DOMAIN"
        )]:
            with self.subTest(status=status):
                game, reason = authoritative_played_domain_game(
                    self.live(status=status, detailed=detailed, innings=9),
                    expected_game_pk=1, expected_season=2020,
                )
                self.assertIsNotNone(game)
                self.assertEqual(expected, reason)

    def test_unknown_terminal_semantics_fail_closed(self):
        with self.assertRaises(BullpenHistorySupplementError) as ctx:
            authoritative_played_domain_game(
                self.live(status="DI", detailed="Postponed", innings=9),
                expected_game_pk=1, expected_season=2020,
            )
        self.assertEqual("TERMINAL_DOMAIN_UNVERIFIED", ctx.exception.code)

    def test_supplement_record_cannot_be_park_or_target_eligible(self):
        game, reason = authoritative_played_domain_game(self.live(), expected_game_pk=1, expected_season=2020)
        box = json.dumps({"teams": {"away": self.team_box(1), "home": self.team_box(2)}}).encode()
        live_bytes = json.dumps(self.live(), sort_keys=True).encode()
        record = normalize_bullpen_history_source(
            game, domain_exclusion_reason=reason,
            timestamps_bytes=json.dumps(["20200809_200000"]).encode(),
            boxscore_bytes=box, live_payload_bytes=live_bytes,
        )
        self.assertEqual("PASS", record["bullpen_status"])
        self.assertTrue(record["bullpen_history_eligible"])
        self.assertFalse(record["target_domain_eligible"])
        self.assertEqual("BLOCKED_DOMAIN", record["park_status"])
        self.assertEqual(reason, record["domain_exclusion_reason"])
        self.assertEqual(64, len(record["source_sha256"]))


if __name__ == "__main__":
    unittest.main()
