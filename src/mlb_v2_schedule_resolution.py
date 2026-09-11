"""Fail-closed schedule resolution overlay for MLB feature-schema v2.

This module only tightens the base schedule normalizer. It reclassifies games as
known domain exclusions when MLB explicitly reports status code FR together with
a Detailed State beginning with ``Completed Early``. Bare FR rows remain
unresolved and are never promoted into canonical 9-inning history.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from mlb_v2_source_acquisition import normalize_schedule_games as _normalize_schedule_games_base


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _status_code(row: Mapping[str, Any]) -> str:
    status = row.get("status") or {}
    return str(status.get("statusCode") or status.get("codedGameState") or "").upper()


def _detailed_state(row: Mapping[str, Any]) -> str:
    status = row.get("status") or {}
    return str(status.get("detailedState") or "").strip()


def _is_explicit_completed_early(row: Mapping[str, Any], season: int) -> bool:
    return (
        row.get("gameType") == "R"
        and str(row.get("officialDate") or "").startswith(str(season))
        and _status_code(row) == "FR"
        and _detailed_state(row).casefold().startswith("completed early")
    )


def _context_from_row(game_pk: int, row: Mapping[str, Any]) -> dict[str, Any]:
    venue = row.get("venue") or {}
    teams = row.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    return {
        "game_pk": game_pk,
        "event_id": f"mlb:{game_pk}",
        "official_date": row.get("officialDate"),
        "event_start_at": row.get("gameDate"),
        "venue_id": _optional_int(venue.get("id")),
        "away_team_id": _optional_int((away.get("team") or {}).get("id")),
        "home_team_id": _optional_int((home.get("team") or {}).get("id")),
    }


def normalize_schedule_games_v3(
    payload: Mapping[str, Any],
    season: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Normalize schedule and reclassify only proven completed-early games.

    ``FR`` by itself is insufficient evidence. Only ``FR`` plus an explicit
    ``Completed Early...`` detailed state is a known domain exclusion. Everything
    else preserves the base normalizer's fail-closed classification.

    ``known_domain_exclusions`` intentionally preserves the base normalizer's
    strict-final accounting semantics. Completed-early FR rows are tracked in the
    separate ``completed_early_domain_exclusions`` counter because they are not
    strict ``F`` rows. ``resolved_schedule_game_pks`` combines both partitions.
    """
    candidates, exclusions, stats = _normalize_schedule_games_base(payload, season)

    rows_by_pk: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for date_block in payload.get("dates", []):
        for row in date_block.get("games", []):
            game_pk = _optional_int(row.get("gamePk"))
            if game_pk is not None:
                rows_by_pk[game_pk].append(row)

    explicit_by_pk: dict[int, Mapping[str, Any]] = {}
    for game_pk, rows in rows_by_pk.items():
        proven = [row for row in rows if _is_explicit_completed_early(row, season)]
        if proven:
            explicit_by_pk[game_pk] = proven[0]

    reclassified = 0
    rewritten: list[dict[str, Any]] = []
    for exclusion in exclusions:
        game_pk = _optional_int(exclusion.get("game_pk"))
        if (
            exclusion.get("reason") == "NO_STRICT_PLAYED_FINAL_ROW"
            and game_pk is not None
            and game_pk in explicit_by_pk
        ):
            row = explicit_by_pk[game_pk]
            rewritten.append({
                **_context_from_row(game_pk, row),
                "reason": "COMPLETED_EARLY_DOMAIN",
                "status_code": _status_code(row),
                "detailed_state": _detailed_state(row),
                "schedule_row_count": exclusion.get("schedule_row_count", len(rows_by_pk[game_pk])),
            })
            reclassified += 1
        else:
            rewritten.append(exclusion)

    updated_stats = dict(stats)
    updated_stats["completed_early_domain_exclusions"] = reclassified
    updated_stats["unresolved_no_strict_played_final"] = sum(
        1 for item in rewritten if item.get("reason") == "NO_STRICT_PLAYED_FINAL_ROW"
    )
    updated_stats["resolved_schedule_game_pks"] = (
        int(updated_stats.get("strict_final_unique_game_pks", 0)) + reclassified
    )
    return candidates, rewritten, updated_stats
