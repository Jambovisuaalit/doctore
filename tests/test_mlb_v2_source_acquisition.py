from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v2_source_acquisition import (
    ScheduleResolutionError,
    SourceAcquisitionError,
    final_event_at_from_timestamps,
    hydrate_schedule_candidate,
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

    def schedule_row(self, *, game_pk: int = 123, status_code: str = "F", innings: int | None = 9, include_scores: bool = True, game_date: str = "2021-07-10T23:00:00Z") -> dict:
        away = {"team": {"id": 1}}
        home = {"team": {"id": 2}}
        if include_scores:
            away["score"] = 4
            home["score"] = 3
        row = {
            "gamePk": game_pk,
            "gameType": "R",
            "gameDate": game_date,
            "officialDate": "2021-07-10",
            "status": {
                "abstractGameState": "Final",
                "codedGameState": status_code,
                "statusCode": status_code,
                "detailedState": "Final" if status_code == "F" else "Postponed",
            },
            "venue": {"id": 10, "name": "Test Park"},
            "teams": {"away": away, "home": home},
        }
        if innings is not None:
            row["scheduledInnings"] = innings
        return row

    def live_payload(self, *, game_pk: int = 123, innings: int | None = 9, away_score: int = 4, home_score: int = 3, venue_id: int = 10) -> dict:
        linescore = {
            "teams": {
                "away": {"runs": away_score},
                "home": {"runs": home_score},
            }
        }
        if innings is not None:
            linescore["scheduledInnings"] = innings
        return {
            "gamePk": game_pk,
            "gameData": {
                "game": {"pk": game_pk, "type": "R"},
                "status": {"statusCode": "F", "codedGameState": "F", "detailedState": "Final"},
                "datetime": {"officialDate": "2021-07-10", "dateTime": "2021-07-10T23:00:00Z"},
                "venue": {"id": venue_id, "name": "Test Park"},
                "teams": {
                    "away": {"id": 1, "name": "Away"},
                    "home": {"id": 2, "name": "Home"},
                },
            },
            "liveData": {"linescore": linescore},
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

    def test_complete_played_final_schedule_row_needs_no_hydration(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row()]}]}
        games, exclusions, stats = normalize_schedule_games(payload, 2021)
        self.assertEqual([], exclusions)
        self.assertEqual(1, len(games))
        self.assertFalse(games[0]["needs_hydration"])
        self.assertEqual(1, stats["strict_final_unique_game_pks"])

    def test_postponed_stub_plus_makeup_final_is_one_candidate_not_false_reject(self) -> None:
        postponed = self.schedule_row(status_code="DI", include_scores=False, game_date="2021-07-01T23:00:00Z")
        final = self.schedule_row(status_code="F", include_scores=True, game_date="2021-07-10T23:00:00Z")
        payload = {"dates": [{"games": [postponed, final]}]}
        games, exclusions, stats = normalize_schedule_games(payload, 2021)
        self.assertEqual([], exclusions)
        self.assertEqual(1, len(games))
        self.assertEqual("2021-07-10T23:00:00Z", games[0]["event_start_at"])
        self.assertEqual(1, stats["duplicate_schedule_rows"])
        self.assertEqual(1, stats["reschedule_or_nonfinal_metadata_rows"])

    def test_partial_strict_final_candidate_is_hydrated(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row(include_scores=False)]}]}
        games, exclusions, _ = normalize_schedule_games(payload, 2021)
        self.assertEqual([], exclusions)
        self.assertTrue(games[0]["needs_hydration"])
        resolved = hydrate_schedule_candidate(games[0], self.live_payload())
        self.assertFalse(resolved["needs_hydration"])
        self.assertTrue(resolved["hydrated_from_live"])
        self.assertEqual(4, resolved["away_score"])
        self.assertEqual(3, resolved["home_score"])

    def test_missing_scheduled_innings_can_be_hydrated(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row(innings=None)]}]}
        games, _, _ = normalize_schedule_games(payload, 2021)
        self.assertTrue(games[0]["needs_hydration"])
        resolved = hydrate_schedule_candidate(games[0], self.live_payload(innings=9))
        self.assertEqual(9, resolved["scheduled_innings"])

    def test_schedule_live_conflict_fails_closed(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row()]}]}
        games, _, _ = normalize_schedule_games(payload, 2021)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate(games[0], self.live_payload(away_score=99))
        self.assertEqual("SCHEDULE_LIVE_FIELD_CONFLICT", ctx.exception.code)

    def test_duplicate_strict_final_rows_with_conflict_fail_closed(self) -> None:
        first = self.schedule_row()
        second = self.schedule_row()
        second["teams"]["away"]["score"] = 9
        payload = {"dates": [{"games": [first, second]}]}
        games, exclusions, stats = normalize_schedule_games(payload, 2021)
        self.assertEqual([], games)
        self.assertEqual("DUPLICATE_STRICT_FINAL_CONFLICT", exclusions[0]["reason"])
        self.assertEqual(1, stats["strict_final_conflicts"])

    def test_known_non_nine_inning_final_is_domain_exclusion(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row(innings=7)]}]}
        games, exclusions, stats = normalize_schedule_games(payload, 2021)
        self.assertEqual([], games)
        self.assertEqual("NON_NINE_INNING_DOMAIN", exclusions[0]["reason"])
        self.assertEqual(1, stats["known_domain_exclusions"])

    def test_hydrated_non_nine_inning_game_is_domain_exclusion(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row(innings=None)]}]}
        games, _, _ = normalize_schedule_games(payload, 2021)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate(games[0], self.live_payload(innings=7))
        self.assertEqual("NON_NINE_INNING_DOMAIN", ctx.exception.code)

    def test_abstract_final_postponed_stub_is_not_strict_final(self) -> None:
        payload = {"dates": [{"games": [self.schedule_row(status_code="DI", include_scores=False)]}]}
        games, exclusions, stats = normalize_schedule_games(payload, 2021)
        self.assertEqual([], games)
        self.assertEqual("NO_STRICT_PLAYED_FINAL_ROW", exclusions[0]["reason"])
        self.assertEqual(0, stats["strict_final_unique_game_pks"])


if __name__ == "__main__":
    unittest.main()
