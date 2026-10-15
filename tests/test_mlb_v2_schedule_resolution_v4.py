from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mlb_v2_schedule_resolution_v4 import (
    hydrate_schedule_candidate_v4,
    normalize_schedule_games_v4,
)
from mlb_v2_source_acquisition import ScheduleResolutionError


class MlbV2ScheduleResolutionV4Tests(unittest.TestCase):
    def row(
        self, *, status='F', detailed='Final', game_pk=1,
        game_date='2014-05-01T23:00:00Z', venue_id=10,
        away_score=2, home_score=1, innings=9,
    ):
        away = {'team': {'id': 1}}
        home = {'team': {'id': 2}}
        if away_score is not None:
            away['score'] = away_score
        if home_score is not None:
            home['score'] = home_score
        row = {
            'gamePk': game_pk,
            'gameType': 'R',
            'gameDate': game_date,
            'officialDate': '2014-05-01',
            'status': {'statusCode': status, 'codedGameState': status, 'detailedState': detailed},
            'venue': {'id': venue_id, 'name': 'Test Park'},
            'teams': {'away': away, 'home': home},
        }
        if innings is not None:
            row['scheduledInnings'] = innings
        return row

    def payload(self, *rows):
        return {'dates': [{'games': list(rows)}]}

    def live(self, *, status='F', detailed='Final', game_pk=1, venue_id=10,
             game_date='2014-05-02T00:00:00Z', away_score=2, home_score=1,
             innings=9, current_inning=None):
        return {
            'gamePk': game_pk,
            'gameData': {
                'game': {'pk': game_pk, 'type': 'R'},
                'status': {'statusCode': status, 'codedGameState': status, 'detailedState': detailed},
                'datetime': {'officialDate': '2014-05-01', 'dateTime': game_date},
                'venue': {'id': venue_id, 'name': 'Test Park'},
                'teams': {'away': {'id': 1}, 'home': {'id': 2}},
            },
            'liveData': {
                'linescore': {
                    'scheduledInnings': innings,
                    'currentInning': current_inning,
                    'teams': {'away': {'runs': away_score}, 'home': {'runs': home_score}},
                }
            },
        }

    def test_mutable_strict_final_revision_becomes_hydration_candidate(self):
        first = self.row(game_date='2014-05-01T23:00:00Z', venue_id=10)
        second = self.row(game_date='2014-05-02T00:00:00Z', venue_id=11)
        games, exclusions, stats = normalize_schedule_games_v4(self.payload(first, second), 2014)
        self.assertEqual([], exclusions)
        self.assertEqual(1, len(games))
        self.assertTrue(games[0]['needs_hydration'])
        self.assertEqual('STRICT_FINAL_REVISION', games[0]['schedule_resolution_kind'])
        self.assertEqual(0, stats['strict_final_conflicts'])
        self.assertEqual(1, stats['schedule_revision_hydration_candidates'])

    def test_score_conflict_remains_fail_closed(self):
        first = self.row(away_score=2)
        second = self.row(away_score=9, game_date='2014-05-02T00:00:00Z')
        games, exclusions, stats = normalize_schedule_games_v4(self.payload(first, second), 2014)
        self.assertEqual([], games)
        self.assertEqual('DUPLICATE_STRICT_FINAL_CONFLICT', exclusions[0]['reason'])
        self.assertEqual(1, stats['strict_final_conflicts'])

    def test_missing_immutable_identity_does_not_resolve_revision(self):
        first = self.row(away_score=None)
        second = self.row(away_score=2, game_date='2014-05-02T00:00:00Z')
        games, exclusions, stats = normalize_schedule_games_v4(self.payload(first, second), 2014)
        self.assertEqual([], games)
        self.assertEqual('DUPLICATE_STRICT_FINAL_CONFLICT', exclusions[0]['reason'])
        self.assertEqual(1, stats['strict_final_conflicts'])

    def test_no_strict_final_becomes_authoritative_live_candidate(self):
        row = self.row(status='DI', detailed='Postponed')
        games, exclusions, stats = normalize_schedule_games_v4(self.payload(row), 2014)
        self.assertEqual([], exclusions)
        self.assertEqual(1, len(games))
        self.assertEqual('NO_STRICT_FINAL_AUTHORITATIVE_CHECK', games[0]['schedule_resolution_kind'])
        self.assertEqual(0, stats['unresolved_no_strict_played_final'])
        self.assertEqual(1, stats['unresolved_schedule_hydration_candidates'])

    def test_authoritative_final_resolves_no_strict_candidate(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        resolved = hydrate_schedule_candidate_v4(games[0], self.live())
        self.assertFalse(resolved['needs_hydration'])
        self.assertTrue(resolved['hydrated_from_live'])

    def test_authoritative_completed_early_is_domain_exclusion(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate_v4(
                games[0],
                self.live(status='FR', detailed='Completed Early: Rain'),
            )
        self.assertEqual('COMPLETED_EARLY_DOMAIN', ctx.exception.code)


    def test_authoritative_cancelled_is_domain_exclusion(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate_v4(
                games[0],
                self.live(status='CI', detailed='Cancelled: Inclement Weather'),
            )
        self.assertEqual('CANCELLED_DOMAIN', ctx.exception.code)

    def test_authoritative_shortened_tied_final_is_domain_exclusion(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate_v4(
                games[0],
                self.live(
                    status='FT',
                    detailed='Final: Tied',
                    innings=9,
                    current_inning=6,
                    away_score=1,
                    home_score=1,
                ),
            )
        self.assertEqual('COMPLETED_EARLY_TIED_DOMAIN', ctx.exception.code)

    def test_tied_final_without_proven_early_completion_remains_blocked(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate_v4(
                games[0],
                self.live(
                    status='FT',
                    detailed='Final: Tied',
                    innings=9,
                    current_inning=9,
                    away_score=1,
                    home_score=1,
                ),
            )
        self.assertEqual('LIVE_TIED_SETTLEMENT_UNVERIFIED', ctx.exception.code)

    def test_other_nonfinal_authoritative_status_stays_blocked(self):
        row = self.row(status='DI', detailed='Postponed')
        games, _, _ = normalize_schedule_games_v4(self.payload(row), 2014)
        with self.assertRaises(ScheduleResolutionError) as ctx:
            hydrate_schedule_candidate_v4(
                games[0],
                self.live(status='DI', detailed='Postponed'),
            )
        self.assertEqual('LIVE_NOT_FINAL', ctx.exception.code)


if __name__ == '__main__':
    unittest.main()
