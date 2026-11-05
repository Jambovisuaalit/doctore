from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from src.mlb_player_hits_data import (
    MLBPlayerHitsDataError,
    build_bundle,
    extract_plate_appearances,
    extract_pregame_context,
    payload_sha256,
    write_json_create_only,
)


def _player(pid: int, name: str, order: int | None = None, started: bool = False) -> dict:
    data = {
        "person": {"id": pid, "fullName": name},
        "stats": {"pitching": {"gamesStarted": 1 if started else 0}},
    }
    if order is not None:
        data["battingOrder"] = str(order * 100)
    return data


def fixture_feed() -> dict:
    away_players = {f"ID{i}": _player(i, f"Away {i}", i - 9) for i in range(10, 19)}
    home_players = {f"ID{i}": _player(i, f"Home {i}", i - 19) for i in range(20, 29)}
    away_players["ID90"] = _player(90, "Away Starter", started=True)
    home_players["ID91"] = _player(91, "Home Starter", started=True)
    home_players["ID92"] = _player(92, "Home Reliever", started=False)
    return {
        "gameData": {
            "game": {"pk": 123456, "gameNumber": 1},
            "datetime": {"officialDate": "2026-07-27", "dateTime": "2026-07-27T23:10:00Z"},
            "teams": {"away": {"id": 147}, "home": {"id": 111}},
            "status": {"detailedState": "Final"},
            "probablePitchers": {
                "away": {"id": 90, "fullName": "Away Starter"},
                "home": {"id": 91, "fullName": "Home Starter"},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"players": away_players},
                    "home": {"players": home_players},
                }
            },
            "plays": {
                "allPlays": [
                    {
                        "about": {
                            "atBatIndex": 0,
                            "isComplete": True,
                            "inning": 1,
                            "halfInning": "top",
                            "outs": 0,
                            "startTime": "2026-07-27T23:12:00Z",
                            "endTime": "2026-07-27T23:14:00Z",
                        },
                        "matchup": {
                            "batter": {"id": 10, "fullName": "Away 10"},
                            "pitcher": {"id": 91, "fullName": "Home Starter"},
                            "batSide": {"code": "L"},
                            "pitchHand": {"code": "R"},
                        },
                        "result": {"event": "Single", "eventType": "single"},
                    },
                    {
                        "about": {
                            "atBatIndex": 1,
                            "isComplete": True,
                            "inning": 7,
                            "halfInning": "top",
                            "outs": 1,
                            "startTime": "2026-07-28T01:10:00Z",
                            "endTime": "2026-07-28T01:12:00Z",
                        },
                        "matchup": {
                            "batter": {"id": 11, "fullName": "Away 11"},
                            "pitcher": {"id": 92, "fullName": "Home Reliever"},
                            "batSide": {"code": "R"},
                            "pitchHand": {"code": "R"},
                        },
                        "result": {"event": "Field Out", "eventType": "field_out"},
                    },
                    {
                        "about": {"atBatIndex": 2, "isComplete": False},
                        "matchup": {},
                        "result": {},
                    },
                ]
            },
        },
    }


class MLBPlayerHitsDataTests(unittest.TestCase):
    def test_extracts_exact_identity_and_hit_target(self) -> None:
        rows = extract_plate_appearances(
            fixture_feed(), extraction_generated_at="2026-07-28T05:00:00Z"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event_id"], "mlb:123456")
        self.assertEqual(rows[0]["plate_appearance_id"], "mlb:123456:ab:0")
        self.assertTrue(rows[0]["is_official_hit"])
        self.assertFalse(rows[1]["is_official_hit"])

    def test_starter_reliever_and_batting_order_are_derived(self) -> None:
        rows = extract_plate_appearances(fixture_feed())
        self.assertEqual(rows[0]["pitcher_role"], "starter")
        self.assertEqual(rows[1]["pitcher_role"], "reliever")
        self.assertEqual(rows[0]["batting_order_position"], 1)
        self.assertEqual(rows[1]["batting_order_position"], 2)

    def test_team_identity_follows_half_inning(self) -> None:
        rows = extract_plate_appearances(fixture_feed())
        self.assertEqual(rows[0]["batting_team_id"], 147)
        self.assertEqual(rows[0]["fielding_team_id"], 111)

    def test_duplicate_at_bat_is_rejected(self) -> None:
        payload = fixture_feed()
        payload["liveData"]["plays"]["allPlays"].append(
            payload["liveData"]["plays"]["allPlays"][0]
        )
        with self.assertRaises(MLBPlayerHitsDataError):
            extract_plate_appearances(payload)

    def test_non_final_game_is_rejected(self) -> None:
        payload = fixture_feed()
        payload["gameData"]["status"]["detailedState"] = "Scheduled"
        with self.assertRaises(MLBPlayerHitsDataError):
            extract_plate_appearances(payload)

    def test_pregame_lineup_and_starter_snapshot_is_eligible(self) -> None:
        context = extract_pregame_context(
            fixture_feed(),
            observed_at="2026-07-27T21:00:00Z",
            feature_cutoff_at="2026-07-27T22:00:00Z",
        )
        self.assertTrue(context["training_eligible"])
        self.assertEqual(context["lineup_status"], "confirmed")
        self.assertEqual(len(context["away_lineup"]), 9)
        self.assertEqual(context["away_starter"]["player_id"], "mlbam:90")

    def test_post_start_snapshot_is_blocked(self) -> None:
        context = extract_pregame_context(
            fixture_feed(),
            observed_at="2026-07-28T00:00:00Z",
            feature_cutoff_at="2026-07-28T00:05:00Z",
        )
        self.assertFalse(context["training_eligible"])
        self.assertIn("SNAPSHOT_NOT_PREGAME", context["reason_codes"])

    def test_hash_and_bundle_are_deterministic(self) -> None:
        payload = fixture_feed()
        self.assertEqual(payload_sha256(payload), payload_sha256(json.loads(json.dumps(payload))))
        bundle = build_bundle([payload], extraction_generated_at="2026-07-28T05:00:00Z")
        self.assertEqual(bundle["manifest"]["row_count"], 2)
        self.assertEqual(bundle["manifest"]["event_count"], 1)

    def test_create_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            write_json_create_only(path, {"a": 1})
            with self.assertRaises(MLBPlayerHitsDataError):
                write_json_create_only(path, {"a": 2})

    def test_outputs_validate_against_contracts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        row_schema = json.loads((root / "contracts/mlb-pa-row.schema.json").read_text())
        context_schema = json.loads((root / "contracts/mlb-pregame-context.schema.json").read_text())
        row = extract_plate_appearances(fixture_feed())[0]
        context = extract_pregame_context(
            fixture_feed(),
            observed_at="2026-07-27T21:00:00Z",
            feature_cutoff_at="2026-07-27T22:00:00Z",
        )
        Draft202012Validator(row_schema, format_checker=FormatChecker()).validate(row)
        Draft202012Validator(context_schema, format_checker=FormatChecker()).validate(context)


if __name__ == "__main__":
    unittest.main()
