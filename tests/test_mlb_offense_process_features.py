from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_offense_process_features import materialize_offense_process_group


class MlbOffenseProcessFeatureTests(unittest.TestCase):
    def record(self, game_pk, day, away_team_id, home_team_id, final_at, pa=40, bb=4, k=8, hr=1, hits=9):
        def bat(team_id):
            return {"team_id": team_id, "plate_appearances": pa, "walks": bb, "strikeouts": k, "home_runs": hr, "hits": hits}
        return {
            "event_id": f"mlb:{game_pk}", "game_pk": game_pk, "official_date": day,
            "final_event_at": final_at, "away_team_id": away_team_id, "home_team_id": home_team_id,
            "away_batting": bat(away_team_id), "home_batting": bat(home_team_id),
            "offense_status": "PASS", "offense_history_eligible": True, "source_sha256": "a" * 64,
        }

    def test_last10_completed_same_season_only(self):
        cutoff = datetime(2020, 6, 20, 18, 0, tzinfo=timezone.utc)
        rows = []
        for i in range(12):
            t = cutoff - timedelta(days=12 - i)
            rows.append(self.record(100 + i, t.date().isoformat(), 1, 10 + i, t.isoformat().replace("+00:00", "Z"), pa=40 + i, bb=4, k=8, hr=1, hits=9))
            rows.append(self.record(200 + i, t.date().isoformat(), 2, 30 + i, t.isoformat().replace("+00:00", "Z"), pa=42, bb=3, k=7, hr=2, hits=10))
        target = {"event_id": "mlb:999", "official_date": "2020-06-20", "away_team_id": 1, "home_team_id": 2}
        out = materialize_offense_process_group(target, feature_cutoff_at=cutoff.isoformat().replace("+00:00", "Z"), source_records=rows)
        self.assertEqual("PASS", out["status"])
        self.assertAlmostEqual(out["features"]["away_offense_bb_rate_10"], 40 / sum(range(42, 52)))
        self.assertAlmostEqual(out["features"]["home_offense_hr_rate_10"], 20 / (42 * 10))
        self.assertEqual(42.0, out["features"]["home_offense_pa_per_game_10"])
        self.assertEqual(20, len(out["provenance"]["source_events"]))

    def test_future_or_current_results_do_not_enter_history(self):
        cutoff = datetime(2020, 6, 20, 18, 0, tzinfo=timezone.utc)
        rows = []
        for i in range(9):
            t = cutoff - timedelta(days=10 - i)
            rows.append(self.record(100 + i, t.date().isoformat(), 1, 20 + i, t.isoformat().replace("+00:00", "Z")))
            rows.append(self.record(200 + i, t.date().isoformat(), 2, 40 + i, t.isoformat().replace("+00:00", "Z")))
        rows.append(self.record(999, "2020-06-20", 1, 2, (cutoff + timedelta(hours=3)).isoformat().replace("+00:00", "Z")))
        target = {"event_id": "mlb:999", "official_date": "2020-06-20", "away_team_id": 1, "home_team_id": 2}
        out = materialize_offense_process_group(target, feature_cutoff_at=cutoff.isoformat().replace("+00:00", "Z"), source_records=rows)
        self.assertEqual("BLOCKED_PROVENANCE", out["status"])


if __name__ == "__main__":
    unittest.main()
