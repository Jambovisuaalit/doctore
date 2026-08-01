from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_schedule_cache import (
    ScheduleCacheError,
    build_schedule_url,
    normalize_schedule_payload,
    write_cache_manifest,
    write_schedule_cache,
)


def game(
    game_pk: int,
    *,
    detailed: str = "Final",
    abstract: str = "Final",
    away_score=3,
    home_score=2,
):
    return {
        "gamePk": game_pk,
        "gameDate": "2021-04-01T17:05:00Z",
        "officialDate": "2021-04-01",
        "gameType": "R",
        "doubleHeader": "N",
        "gameNumber": 1,
        "scheduledInnings": 9,
        "status": {
            "abstractGameState": abstract,
            "detailedState": detailed,
        },
        "teams": {
            "away": {
                "score": away_score,
                "team": {"id": 112, "name": "Chicago Cubs"},
            },
            "home": {
                "score": home_score,
                "team": {"id": 138, "name": "St. Louis Cardinals"},
            },
        },
    }


class ScheduleCacheTests(unittest.TestCase):
    def test_url_locks_regular_season_and_required_fields(self):
        url = build_schedule_url(2021)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["sportId"], ["1"])
        self.assertEqual(query["gameType"], ["R"])
        self.assertEqual(query["startDate"], ["2021-01-01"])
        self.assertIn("gamePk", query["fields"][0])
        self.assertIn("scheduledInnings", query["fields"][0])

    def test_postponed_placeholder_is_excluded_and_final_is_kept(self):
        postponed = game(
            100,
            detailed="Postponed",
            abstract="Final",
            away_score=None,
            home_score=None,
        )
        final = game(100)
        fillers = [game(pk) | {"gamePk": pk} for pk in range(101, 201)]
        payload = {
            "dates": [
                {
                    "date": "2021-04-01",
                    "games": [postponed, final, *fillers],
                }
            ]
        }
        normalized, audit = normalize_schedule_payload(
            payload, year=2021
        )
        pks = [
            item["gamePk"]
            for block in normalized["dates"]
            for item in block["games"]
        ]
        self.assertIn(100, pks)
        self.assertEqual(audit["final_regular_season_games"], 101)
        self.assertEqual(audit["status_counts"]["Postponed"], 1)

    def test_conflicting_final_gamepk_is_rejected(self):
        first = game(100)
        second = game(100, away_score=4)
        fillers = [game(pk) | {"gamePk": pk} for pk in range(101, 201)]
        payload = {
            "dates": [
                {
                    "date": "2021-04-01",
                    "games": [first, second, *fillers],
                }
            ]
        }
        with self.assertRaisesRegex(
            ScheduleCacheError, "conflicting final records"
        ):
            normalize_schedule_payload(payload, year=2021)

    def test_cache_and_manifest_are_create_only_and_hashed(self):
        fillers = [game(pk) | {"gamePk": pk} for pk in range(100, 201)]
        normalized, audit = normalize_schedule_payload(
            {"dates": [{"date": "2021-04-01", "games": fillers}]},
            year=2021,
        )
        with tempfile.TemporaryDirectory() as tmp:
            record = write_schedule_cache(
                normalized=normalized,
                audit=audit,
                source_url="https://example.test/schedule",
                output_dir=tmp,
                retrieved_at="2026-07-27T00:00:00+00:00",
            )
            self.assertEqual(len(record["sha256"]), 64)
            manifest = write_cache_manifest(
                [record],
                output_dir=tmp,
                created_at="2026-07-27T00:00:00+00:00",
            )
            self.assertEqual(manifest["total_games"], 101)
            with self.assertRaises(FileExistsError):
                write_schedule_cache(
                    normalized=normalized,
                    audit=audit,
                    source_url="https://example.test/schedule",
                    output_dir=tmp,
                    retrieved_at="2026-07-27T00:00:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
