from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from src.mlb_dataset_v1 import (
    DatasetBuildError,
    OddsTeamRow,
    ResultGame,
    american_to_decimal,
    build_dataset_files,
    build_rows,
)


def odds(date: str, side: str, team: str, game: int, total: float = 8.5) -> OddsTeamRow:
    return OddsTeamRow(date, side, team, game, -120, total, -110, -110, 1)


def result(game_id: str, date: str, game: int, away: str, home: str, start: str) -> ResultGame:
    return ResultGame(game_id, date, game, away, home, 3, 4, start, "final")


class MLBDatasetV1Tests(unittest.TestCase):
    def test_american_odds_conversion(self) -> None:
        self.assertAlmostEqual(american_to_decimal(-110), 1.9090909090909092)
        self.assertAlmostEqual(american_to_decimal(150), 2.5)
        with self.assertRaises(DatasetBuildError):
            american_to_decimal(0)

    def test_full_identity_join_and_doubleheader_separation(self) -> None:
        source_odds = [
            odds("2021-07-01", "V", "NYY", 1), odds("2021-07-01", "H", "BOS", 1),
            odds("2021-07-01", "V", "NYY", 2, 9.0), odds("2021-07-01", "H", "BOS", 2, 9.0),
        ]
        games = [
            result("g1", "2021-07-01", 1, "NYY", "BOS", "2021-07-01T17:05:00-04:00"),
            result("g2", "2021-07-01", 2, "NYY", "BOS", "2021-07-01T21:05:00-04:00"),
        ]
        rows, rejected, report = build_rows(source_odds, games)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rejected, [])
        self.assertEqual([row["market_line"] for row in rows], [8.5, 9.0])
        self.assertNotEqual(rows[0]["event_id"], rows[1]["event_id"])
        self.assertEqual(report.accepted_games, 2)

    def test_team_or_side_mismatch_is_rejected_not_fuzzy_joined(self) -> None:
        source_odds = [odds("2021-07-01", "V", "NYY", 1), odds("2021-07-01", "H", "TOR", 1)]
        games = [result("g1", "2021-07-01", 1, "NYY", "BOS", "2021-07-01T17:05:00-04:00")]
        rows, rejected, report = build_rows(source_odds, games)
        self.assertEqual(rows, [])
        self.assertEqual(rejected[0].reason_code, "ODDS_EVENT_IDENTITY_NOT_FOUND")
        self.assertEqual(report.unmatched_result_games, 1)

    def test_same_slate_timestamps_are_preserved_not_fabricated(self) -> None:
        source_odds = [
            odds("2021-07-01", "V", "NYY", 1), odds("2021-07-01", "H", "BOS", 1),
            odds("2021-07-01", "V", "TOR", 1), odds("2021-07-01", "H", "TB", 1),
        ]
        games = [
            result("g1", "2021-07-01", 1, "NYY", "BOS", "2021-07-01T23:10:00+00:00"),
            result("g2", "2021-07-01", 1, "TOR", "TB", "2021-07-01T23:10:00+00:00"),
        ]
        rows, _, _ = build_rows(source_odds, games)
        self.assertEqual(rows[0]["feature_cutoff_at"], rows[1]["feature_cutoff_at"])
        self.assertEqual(rows[0]["slate_id"], rows[1]["slate_id"])

    def test_output_contains_only_declared_market_features(self) -> None:
        source_odds = [odds("2021-07-01", "V", "NYY", 1), odds("2021-07-01", "H", "BOS", 1)]
        games = [result("g1", "2021-07-01", 1, "NYY", "BOS", "2021-07-01T23:10:00+00:00")]
        rows, _, _ = build_rows(source_odds, games)
        forbidden = {"away_runs", "home_runs", "hits", "rbi", "strikeouts"}
        self.assertTrue(forbidden.isdisjoint(rows[0]))
        self.assertEqual(rows[0]["actual_total"], 7)

    def test_build_is_create_only_and_manifest_is_research_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            odds_path = root / "odds.csv"
            results_path = root / "results.csv"
            with odds_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["date", "at", "team", "gameNumber", "line", "runLine", "runLineOdds", "total", "overOdds", "underOdds"])
                writer.writerow(["2021-07-01", "V", "NYY", 1, -120, -1.5, -110, 8.5, -110, -110])
                writer.writerow(["2021-07-01", "H", "BOS", 1, 110, 1.5, -110, 8.5, -110, -110])
            with results_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["source_game_id", "game_date", "game_number", "away_team", "home_team", "away_runs", "home_runs", "event_start_at", "status"])
                writer.writerow(["g1", "2021-07-01", 1, "NYY", "BOS", 3, 4, "2021-07-01T23:10:00+00:00", "final"])
            output = root / "out"
            result_payload = build_dataset_files(
                odds_path=odds_path,
                results_path=results_path,
                output_dir=output,
                dataset_version="1.0.0-test",
                created_at="2026-07-27T00:00:00+00:00",
            )
            self.assertEqual(result_payload["accepted_games"], 1)
            manifest = (output / "training-dataset-manifest.json").read_text(encoding="utf-8")
            self.assertIn('"research_only": true', manifest)
            self.assertIn('"production_eligible": false', manifest)
            self.assertIn('"timestamp_non_decreasing_grouped"', manifest)
            with self.assertRaises(FileExistsError):
                build_dataset_files(
                    odds_path=odds_path,
                    results_path=results_path,
                    output_dir=output,
                    dataset_version="1.0.0-test",
                )


if __name__ == "__main__":
    unittest.main()
