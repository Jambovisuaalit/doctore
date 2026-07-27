"""Strict feature history over every authoritative completed schedule game."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Sequence

from mlb_canonical_dataset import (
    DatasetBuildError,
    FEATURE_COLUMNS,
    JoinedGame,
    ScheduleGame,
    TeamGame,
    _team_features,
)


def build_canonical_rows_with_schedule(
    joined_games: Sequence[JoinedGame],
    schedule_games: Sequence[ScheduleGame],
    *,
    minimum_prior_games: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build rows while updating history from all authoritative final games.

    A game does not need an odds row to enter future rolling history. Canonical
    model rows are emitted only for exact joined odds games. Same-date results
    are withheld until every game in that date group has been priced.
    """
    if minimum_prior_games != 20:
        raise DatasetBuildError("feature schema v1 is locked to 20 prior games")
    joined_by_game_pk = {item.game.game_pk: item for item in joined_games}
    if len(joined_by_game_pk) != len(joined_games):
        raise DatasetBuildError("duplicate gamePk in joined games")

    histories: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    history_games_used = 0
    grouped: dict[date, list[ScheduleGame]] = defaultdict(list)
    for game in schedule_games:
        if game.status in {"Final", "Game Over", "Completed Early"} and game.scheduled_innings == 9:
            grouped[game.official_date].append(game)

    for official_date in sorted(grouped):
        games = sorted(grouped[official_date], key=lambda item: item.game_pk)
        pending: list[tuple[int, int, TeamGame]] = []
        for game in games:
            season = official_date.year
            joined = joined_by_game_pk.get(game.game_pk)
            if joined is not None:
                away_history = histories[(season, game.away_team_id)]
                home_history = histories[(season, game.home_team_id)]
                if len(away_history) < minimum_prior_games or len(home_history) < minimum_prior_games:
                    skipped.append({
                        "game_pk": game.game_pk,
                        "reason": "INSUFFICIENT_PRIOR_GAMES",
                        "away_prior": len(away_history),
                        "home_prior": len(home_history),
                    })
                else:
                    away = _team_features(away_history, official_date)
                    home = _team_features(home_history, official_date)
                    row: dict[str, Any] = {
                        "event_id": f"mlb:{game.game_pk}",
                        "game_pk": game.game_pk,
                        "official_date": official_date.isoformat(),
                        "cutoff_group_at": f"{official_date.isoformat()}T00:00:00+00:00",
                        "event_start_at": game.start_at,
                        "away_team_id": game.away_team_id,
                        "home_team_id": game.home_team_id,
                        "market_total_line": joined.total_line,
                        "final_total_runs": game.away_score + game.home_score,
                        "total_line": joined.total_line,
                        "over_odds_decimal": joined.over_odds_decimal,
                        "under_odds_decimal": joined.under_odds_decimal,
                    }
                    for name, value in away.items():
                        row[f"away_{name}"] = value
                    for name, value in home.items():
                        row[f"home_{name}"] = value
                    missing = set(FEATURE_COLUMNS) - set(row)
                    if missing:
                        raise DatasetBuildError(
                            f"feature construction did not satisfy locked schema: {sorted(missing)}"
                        )
                    rows.append(row)

            pending.extend([
                (season, game.away_team_id, TeamGame(
                    official_date=official_date,
                    runs_for=game.away_score,
                    runs_against=game.home_score,
                    won=game.away_score > game.home_score,
                )),
                (season, game.home_team_id, TeamGame(
                    official_date=official_date,
                    runs_for=game.home_score,
                    runs_against=game.away_score,
                    won=game.home_score > game.away_score,
                )),
            ])
            history_games_used += 1
        for season, team_id, item in pending:
            histories[(season, team_id)].append(item)

    eligible_game_pks = {game.game_pk for games in grouped.values() for game in games}
    missing_schedule = sorted(set(joined_by_game_pk) - eligible_game_pks)
    if missing_schedule:
        raise DatasetBuildError(
            f"joined games absent from eligible schedule history: {missing_schedule[:10]}"
        )
    rows.sort(key=lambda row: (row["cutoff_group_at"], row["game_pk"]))
    return rows, {
        "canonical_rows": len(rows),
        "skipped_rows": skipped,
        "authoritative_history_games_used": history_games_used,
        "history_policy": "all eligible schedule games, including games without odds",
    }
