from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v4_offense_history import OffenseHistoryError, normalize_offense_history_source, normalize_team_batting, write_sha256_sidecar


class MlbV4OffenseHistoryTests(unittest.TestCase):
    def team(self, team_id=1, pa=40, bb=4, k=8, hr=1, hits=9):
        return {"team": {"id": team_id}, "teamStats": {"batting": {
            "plateAppearances": pa, "baseOnBalls": bb, "strikeOuts": k, "homeRuns": hr, "hits": hits
        }}}

    def test_team_batting_normalizes_required_components(self):
        out = normalize_team_batting(self.team(), 1)
        self.assertEqual(40, out["plate_appearances"])
        self.assertEqual(4, out["walks"])
        self.assertEqual(8, out["strikeouts"])
        self.assertEqual(1, out["home_runs"])
        self.assertEqual(9, out["hits"])

    def test_zero_pa_is_blocked(self):
        with self.assertRaises(OffenseHistoryError):
            normalize_team_batting(self.team(pa=0, bb=0, k=0, hr=0, hits=0), 1)

    def test_impossible_counts_are_blocked(self):
        with self.assertRaises(OffenseHistoryError):
            normalize_team_batting(self.team(pa=5, hits=6), 1)
        with self.assertRaises(OffenseHistoryError):
            normalize_team_batting(self.team(pa=10, hits=2, hr=3), 1)

    def test_record_is_content_addressed_and_domain_separated(self):
        game = {"game_pk": 123, "official_date": "2020-08-09", "event_start_at": "2020-08-09T17:00:00Z", "away_team_id": 1, "home_team_id": 2}
        box = json.dumps({"teams": {"away": self.team(1), "home": self.team(2, pa=42)}}).encode()
        ts = json.dumps(["20200809_200000", "20200809_200500"]).encode()
        out = normalize_offense_history_source(
            game, timestamps_bytes=ts, boxscore_bytes=box,
            target_domain_eligible=False, domain_role="NON_NINE_INNING_DOMAIN",
        )
        self.assertEqual("PASS", out["offense_status"])
        self.assertTrue(out["offense_history_eligible"])
        self.assertFalse(out["target_domain_eligible"])
        self.assertEqual("2020-08-09T20:05:00Z", out["final_event_at"])
        self.assertEqual(64, len(out["source_sha256"]))
        self.assertTrue(out["source_record_id"].startswith("mlb-offense-history:123:"))


    def test_sha256_sidecar_uses_real_newline(self):
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.sha256"
            write_sha256_sidecar(path, digest)
            self.assertEqual((digest + "\n").encode("utf-8"), path.read_bytes())
            self.assertNotIn(b"\\n", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
