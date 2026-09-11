from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feature_provenance import validate_provenance_record
from mlb_feature_schema_v2 import BULLPEN_COLUMNS
from mlb_v2_bullpen_features import derive_slate_cutoffs, materialize_bullpen_group


class MlbV2BullpenFeatureTests(unittest.TestCase):
    def target(self) -> dict:
        return {
            "event_id": "mlb:target",
            "official_date": "2021-07-10",
            "event_start_at": "2021-07-10T20:00:00Z",
            "away_team_id": 1,
            "home_team_id": 2,
        }

    def source(
        self,
        event_id: str,
        *,
        official_date: str,
        final_event_at: str,
        team_id: int,
        opponent_id: int,
        bullpen_pitches: int,
        reliever_ids: list[int],
        bullpen_status: str = "PASS",
        source_sha: str = "a" * 64,
    ) -> dict:
        pitching = {
            "team_id": team_id,
            "starter_id": 9000 + team_id,
            "reliever_ids": reliever_ids,
            "bullpen_pitches": bullpen_pitches,
            "bullpen_appearances": len(reliever_ids),
            "relievers": [{"pitcher_id": pid, "pitches": 1} for pid in reliever_ids],
        }
        return {
            "schema_version": "doctore.mlb-feature-source.v1",
            "game_pk": int(event_id.split(":")[-1]) if event_id.split(":")[-1].isdigit() else 999999,
            "event_id": event_id,
            "official_date": official_date,
            "event_start_at": final_event_at,
            "final_event_at": final_event_at,
            "venue": {"id": 10, "name": "Park"},
            "away_team_id": team_id,
            "home_team_id": opponent_id,
            "away_score": 1,
            "home_score": 1,
            "final_total_runs": 2,
            "park_status": "PASS",
            "bullpen_status": bullpen_status,
            "away_pitching": pitching if bullpen_status == "PASS" else None,
            "home_pitching": None,
            "source_record_id": f"source:{event_id}",
            "source_sha256": source_sha,
        }

    def passing_sources(self) -> list[dict]:
        return [
            self.source(
                "mlb:101",
                official_date="2021-07-08",
                final_event_at="2021-07-08T20:00:00Z",
                team_id=1,
                opponent_id=11,
                bullpen_pitches=20,
                reliever_ids=[11, 13],
            ),
            self.source(
                "mlb:102",
                official_date="2021-07-09",
                final_event_at="2021-07-09T20:00:00Z",
                team_id=1,
                opponent_id=12,
                bullpen_pitches=30,
                reliever_ids=[11, 12],
            ),
            self.source(
                "mlb:201",
                official_date="2021-07-08",
                final_event_at="2021-07-08T19:00:00Z",
                team_id=2,
                opponent_id=21,
                bullpen_pitches=10,
                reliever_ids=[21, 22],
            ),
            self.source(
                "mlb:202",
                official_date="2021-07-09",
                final_event_at="2021-07-09T19:00:00Z",
                team_id=2,
                opponent_id=22,
                bullpen_pitches=40,
                reliever_ids=[21],
            ),
            # Full source universes include the target game after it becomes final.
            # Its later final time must not be treated as pre-cutoff leakage.
            self.source(
                "mlb:target",
                official_date="2021-07-10",
                final_event_at="2021-07-10T23:00:00Z",
                team_id=1,
                opponent_id=2,
                bullpen_pitches=99,
                reliever_ids=[99],
            ),
        ]

    def test_slate_cutoff_is_earliest_start_for_every_event_in_slate(self) -> None:
        events = [
            {"event_id": "a", "official_date": "2021-07-10", "event_start_at": "2021-07-10T23:00:00Z"},
            {"event_id": "b", "official_date": "2021-07-10", "event_start_at": "2021-07-10T19:00:00Z"},
            {"event_id": "c", "official_date": "2021-07-11", "event_start_at": "2021-07-11T20:30:00Z"},
        ]
        cutoffs = derive_slate_cutoffs(events)
        self.assertEqual("2021-07-10T19:00:00Z", cutoffs["a"])
        self.assertEqual("2021-07-10T19:00:00Z", cutoffs["b"])
        self.assertEqual("2021-07-11T20:30:00Z", cutoffs["c"])

    def test_materializes_exact_24h_72h_features_and_valid_provenance(self) -> None:
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-10T18:00:00Z",
            source_records=self.passing_sources(),
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(set(BULLPEN_COLUMNS), set(result["features"]))
        self.assertEqual(30, result["features"]["away_bullpen_pitches_1d"])
        self.assertEqual(50, result["features"]["away_bullpen_pitches_3d"])
        self.assertEqual(40, result["features"]["home_bullpen_pitches_1d"])
        self.assertEqual(50, result["features"]["home_bullpen_pitches_3d"])
        self.assertEqual(2, result["features"]["away_bullpen_appearances_1d"])
        self.assertEqual(4, result["features"]["away_bullpen_appearances_3d"])
        self.assertEqual(1, result["features"]["home_bullpen_appearances_1d"])
        self.assertEqual(3, result["features"]["home_bullpen_appearances_3d"])
        self.assertEqual(1, result["features"]["away_bullpen_back_to_back_count"])
        self.assertEqual(1, result["features"]["home_bullpen_back_to_back_count"])
        self.assertEqual((), validate_provenance_record(result["provenance"]))
        source_ids = {item["event_id"] for item in result["provenance"]["source_events"]}
        self.assertEqual({"mlb:101", "mlb:102", "mlb:201", "mlb:202"}, source_ids)

    def test_blocked_source_inside_72h_blocks_group(self) -> None:
        sources = self.passing_sources()
        sources[1]["bullpen_status"] = "BLOCKED"
        sources[1].pop("away_pitching", None)
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-10T18:00:00Z",
            source_records=sources,
        )
        self.assertEqual("BLOCKED_PROVENANCE", result["status"])
        self.assertIn("AWAY_BULLPEN_SOURCE_BLOCKED_IN_3D", result["reason_codes"])
        self.assertEqual({}, result["features"])

    def test_any_prior_eligible_reject_for_team_blocks_until_repaired(self) -> None:
        reject = {
            "game_pk": 77,
            "event_id": "mlb:77",
            "official_date": "2021-06-01",
            "event_start_at": "2021-06-01T20:00:00Z",
            "venue_id": 10,
            "away_team_id": 1,
            "home_team_id": 30,
            "reason": "TIMESTAMPS_FETCH_FAILED",
            "detail": "source unavailable",
        }
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-10T18:00:00Z",
            source_records=self.passing_sources(),
            eligible_rejects=[reject],
        )
        self.assertEqual("BLOCKED_PROVENANCE", result["status"])
        self.assertIn("AWAY_BULLPEN_HISTORY_HAS_ELIGIBLE_REJECT", result["reason_codes"])

    def test_unrelated_team_reject_does_not_block(self) -> None:
        reject = {
            "game_pk": 77,
            "event_id": "mlb:77",
            "official_date": "2021-06-01",
            "event_start_at": "2021-06-01T20:00:00Z",
            "venue_id": 10,
            "away_team_id": 31,
            "home_team_id": 30,
            "reason": "TIMESTAMPS_FETCH_FAILED",
            "detail": "source unavailable",
        }
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-10T18:00:00Z",
            source_records=self.passing_sources(),
            eligible_rejects=[reject],
        )
        self.assertEqual("PASS", result["status"])

    def test_no_proven_prior_game_in_72h_blocks_group(self) -> None:
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-20T18:00:00Z",
            source_records=self.passing_sources(),
        )
        self.assertEqual("BLOCKED_PROVENANCE", result["status"])
        self.assertIn("AWAY_BULLPEN_NO_PROVEN_PRIOR_GAME_3D", result["reason_codes"])
        self.assertIn("HOME_BULLPEN_NO_PROVEN_PRIOR_GAME_3D", result["reason_codes"])

    def test_invalid_final_timestamp_for_relevant_source_fails_closed(self) -> None:
        sources = self.passing_sources()
        sources[0]["final_event_at"] = "bad"
        result = materialize_bullpen_group(
            self.target(),
            feature_cutoff_at="2021-07-10T18:00:00Z",
            source_records=sources,
        )
        self.assertEqual("BLOCKED_PROVENANCE", result["status"])
        self.assertIn("AWAY_BULLPEN_SOURCE_FINAL_AT_INVALID", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
