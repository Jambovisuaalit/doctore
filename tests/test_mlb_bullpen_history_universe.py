from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from mlb_bullpen_history_universe import (
    BullpenHistoryUniverseError, build_history_universe_manifest,
    validate_season_history_universe,
)


class BullpenHistoryUniverseTests(unittest.TestCase):
    def target_manifest(self):
        return {
            "season": 2020,
            "acquisition_policy": "authoritative_live_schedule_resolution_v4",
            "strict_final_conflicts": 0,
            "unresolved_no_strict_played_final": 0,
            "timestamp_or_core_reject_count": 0,
            "bullpen_blocked_records": 0,
            "hydration_reject_count": 0,
            "normalized_source_records": 2,
            "unique_schedule_game_pks": 4,
        }

    def supplement_manifest(self):
        return {
            "season": 2020,
            "policy": "authoritative_played_target_exclusions_bullpen_history_v1",
            "reject_count": 0,
            "bullpen_blocked_records": 0,
            "supplemental_records": 1,
        }

    def record(self, pk, *, supplement=False):
        row={"game_pk":pk,"bullpen_status":"PASS"}
        if supplement:
            row["bullpen_history_eligible"]=True
        return row

    def test_exact_partition_proves_complete_played_universe(self):
        proof=validate_season_history_universe(
            target_manifest=self.target_manifest(),
            target_records=[self.record(1),self.record(2)],
            supplement_manifest=self.supplement_manifest(),
            supplement_records=[self.record(3,supplement=True)],
            supplement_skips=[
                {"game_pk":2,"reason":"STANDARD_TARGET_DOMAIN"},
                {"game_pk":4,"reason":"CANCELLED_UNPLAYED_DOMAIN"},
            ],
        )
        self.assertEqual(3,proof["played_event_count"])
        self.assertEqual(1,proof["cancelled_unplayed_count"])
        manifest=build_history_universe_manifest([proof],source_sha="a"*40)
        self.assertEqual("PASS",manifest["completeness_status"])
        self.assertTrue(manifest["manifest_id"].startswith("mlb-bullpen-history-universe:"))

    def test_missing_partition_event_fails_closed(self):
        with self.assertRaisesRegex(BullpenHistoryUniverseError,"partition incomplete"):
            validate_season_history_universe(
                target_manifest=self.target_manifest(),
                target_records=[self.record(1),self.record(2)],
                supplement_manifest=self.supplement_manifest(),
                supplement_records=[self.record(3,supplement=True)],
                supplement_skips=[],
            )

    def test_cancelled_event_cannot_enter_played_history(self):
        with self.assertRaisesRegex(BullpenHistoryUniverseError,"cancelled event entered"):
            validate_season_history_universe(
                target_manifest=self.target_manifest(),
                target_records=[self.record(1),self.record(2)],
                supplement_manifest=self.supplement_manifest(),
                supplement_records=[self.record(3,supplement=True)],
                supplement_skips=[{"game_pk":3,"reason":"CANCELLED_UNPLAYED_DOMAIN"}],
            )


if __name__=="__main__":
    unittest.main()
