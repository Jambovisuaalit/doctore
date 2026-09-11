from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v2_source_acquisition import (
    SourceAcquisitionError,
    final_event_at_from_timestamps,
    normalize_game_source,
    normalize_schedule_games,
    normalize_team_pitching,
)


class MlbV2SourceAcquisitionTests(unittest.TestCase):
    def schedule_game(self) -> dict:
        return {
            "game_pk": 123,
            "official_date": "2021-07-10",
            "event_start_at": "2021-07-10T23:00:00Z",
            "scheduled_innings": 9,
            "venue_id": 10,
            "venue_name": "Test Park",
            "away_team_id": 1,
            "home_team_id": 2,
            "away_score": 4,
            "home_score": 3,
        }

    def team_box(self, team_id: int) -> dict:
        return {
            "team": {"id": team_id},
            "pitchers": [101, 102, 103],
            "players": {
                "ID101": {"stats": {"pitching": {"gamesStarted": 1, "gamesPitched": 1, "pitchesThrown": 91}}},
                "ID102": {"stats": {"pitching": {"gamesStarted": 0, "gamesPitched": 1, "pitchesThrown": 17}}},
                "ID103": {"stats": {"pitching": {"gamesStarted": 0, "gamesPitched": 1, "numberOfPitches": 12}}},
            },
        }

    def valid_box_bytes(self) -> bytes:
        return json.dumps({
            "teams": {
                "away": self.team_box(1),
                "home": self.team_box(2),
            }
        }, sort_keys=True).encode()

    def timestamps_bytes(self) -> bytes:
        return json.dumps(["20210711_020304"]).encode()

    def test_timestamp_latest_is_final_event_time(self) -> None:
        self.assertEqual(
            "2021-07-11T02:03:04Z",
            final_event_at_from_timestamps(["20210711_010203", "20210711_020304"]),
        )

    def test_any_invalid_timestamp_fails_closed(self) -> None:
        with self.assertRaisesRegex(SourceAcquisitionError, "invalid MLB timecode"):
            final_event_at_from_timestamps(["20210711_020304", "bad"])

    def test_team_pitching_excludes_actual_starter(self) -> None:
        normalized = normalize_team_pitching(self.team_box(1), 1)
        self.assertEqual(101, normalized["starter_id"])
        self.assertEqual([102, 103], normalized["reliever_ids"])
        self.assertEqual(29, normalized["bullpen_pitches"])
        self.assertEqual(2, normalized["bullpen_appearances"])

    def test_multiple_actual_starters_fail_closed(self) -> None:
        box = self.team_box(1)
        box["players"]["ID102"]["stats"]["pitching"]["gamesStarted"] = 1
        with self.assertRaisesRegex(SourceAcquisitionError, "starter identity ambiguous"):
            normalize_team_pitching(box, 1)

    def test_team_identity_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(SourceAcquisitionError, "team mismatch"):
            normalize_team_pitching(self.team_box(1), 2)

    def test_normalized_record_is_content_addressed(self) -> None:
        first = normalize_game_source(
            self.schedule_game(),
            boxscore_bytes=self.valid_box_bytes(),
            timestamps_bytes=self.timestamps_bytes(),
        )
        second = normalize_game_source(
            self.schedule_game(),
            boxscore_bytes=self.valid_box_bytes(),
            timestamps_bytes=self.timestamps_bytes(),
        )
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        self.assertEqual(7, first["final_total_runs"])
        self.assertEqual("2021-07-11T02:03:04Z", first["final_event_at"])
        self.assertEqual("PASS", first["park_status"])
        self.assertEqual("PASS", first["bullpen_status"])
        self.assertEqual(29, first["away_pitching"]["bullpen_pitches"])

    def test_missing_boxscore_blocks_bullpen_but_preserves_park(self) -> None:
        record = normalize_game_source(
            self.schedule_game(),
            boxscore_bytes=None,
            timestamps_bytes=self.timestamps_bytes(),
            bullpen_error="BOXSCORE_FETCH_FAILED",
        )
        self.assertEqual("PASS", record["park_status"])
        self.assertEqual("BLOCKED", record["bullpen_status"])
        self.assertEqual("BOXSCORE_FETCH_FAILED", record["bullpen_reason"])
        self.assertIsNone(record["lineage"]["boxscore_sha256"])
        self.assertNotIn("away_pitching", record)

    def test_invalid_boxscore_json_blocks_bullpen_but_preserves_park(self) -> None:
        record = normalize_game_source(
            self.schedule_game(),
            boxscore_bytes=b"{not-json",
            timestamps_bytes=self.timestamps_bytes(),
        )
        self.assertEqual("PASS", record["park_status"])
        self.assertEqual("BLOCKED", record["bullpen_status"])
        self.assertEqual("BOXSCORE_JSON_INVALID", record["bullpen_reason"])
        self.assertNotIn("away_pitching", record)

    def test_ambiguous_starter_blocks_bullpen_but_preserves_park(self) -> None:
        away = self.team_box(1)
        away["players"]["ID102"]["stats"]["pitching"]["gamesStarted"] = 1
        box = {"teams": {"away": away, "home": self.team_box(2)}}
        record = normalize_game_source(
            self.schedule_game(),
            boxscore_bytes=json.dumps(box).encode(),
            timestamps_bytes=self.timestamps_bytes(),
        )
        self.assertEqual("PASS", record["park_status"])
        self.assertEqual("BLOCKED", record["bullpen_status"])
        self.assertEqual("BULLPEN_NORMALIZATION_BLOCKED", record["bullpen_reason"])
        self.assertIn("starter identity ambiguous", record["bullpen_detail"])

    def test_invalid_timestamps_block_entire_record(self) -> None:
        with self.assertRaisesRegex(SourceAcquisitionError, "timestamps payload"):
            normalize_game_source(
                self.schedule_game(),
                boxscore_bytes=self.valid_box_bytes(),
                timestamps_bytes=b"[]",
            )

    def test_schedule_normalization_rejects_non_nine_inning_domain(self) -> None:
        payload = {
            "dates": [{
                "games": [{
                    "gamePk": 1,
                    "gameType": "R",
                    "gameDate": "2021-07-10T20:00:00Z",
                    "officialDate": "2021-07-10",
                    "scheduledInnings": 7,
                    "status": {"abstractGameState": "Final"},
                    "venue": {"id": 10, "name": "Park"},
                    "teams": {
                        "away": {"team": {"id": 1}, "score": 2},
                        "home": {"team": {"id": 2}, "score": 3},
                    },
                }]
            }]
        }
        games, rejected = normalize_schedule_games(payload, 2021)
        self.assertEqual([], games)
        self.assertIn("NON_NINE_INNING_DOMAIN", rejected[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
