"""Fail-closed MLB schedule resolver with authoritative live hydration candidates.

V4 extends the v3 completed-early resolver. Duplicate strict-final schedule rows
may be converted into a hydration candidate only when all immutable settlement
identity fields agree and the differences are limited to mutable scheduling
metadata (start time / venue). The live feed must then supply the authoritative
mutable values through the existing acquisition hydration path.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from mlb_v2_schedule_resolution import normalize_schedule_games_v3

IMMUTABLE_FIELDS = (
    "official_date",
    "scheduled_innings",
    "away_team_id",
    "home_team_id",
    "away_score",
    "home_score",
)
MUTABLE_FIELDS = ("event_start_at", "venue_id", "venue_name")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_code(row: Mapping[str, Any]) -> str:
    status = row.get("status") or {}
    return str(status.get("statusCode") or status.get("codedGameState") or "").upper()


def _is_strict_final(row: Mapping[str, Any], season: int) -> bool:
    return (
        row.get("gameType") == "R"
        and _status_code(row) == "F"
        and str(row.get("officialDate") or "").startswith(str(season))
    )


def _values(row: Mapping[str, Any]) -> dict[str, Any]:
    venue = row.get("venue") or {}
    teams = row.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    return {
        "official_date": str(row.get("officialDate") or "") or None,
        "event_start_at": str(row.get("gameDate") or "") or None,
        "scheduled_innings": _optional_int(row.get("scheduledInnings")),
        "venue_id": _optional_int(venue.get("id")),
        "venue_name": str(venue.get("name") or "") or None,
        "away_team_id": _optional_int((away.get("team") or {}).get("id")),
        "home_team_id": _optional_int((home.get("team") or {}).get("id")),
        "away_score": _optional_int(away.get("score")),
        "home_score": _optional_int(home.get("score")),
    }


def _unique_present(values: Sequence[Mapping[str, Any]], field: str) -> set[Any]:
    return {value.get(field) for value in values if value.get(field) not in (None, "")}


def _revision_candidate(game_pk: int, rows: Sequence[Mapping[str, Any]], season: int) -> dict[str, Any] | None:
    strict_rows = [row for row in rows if _is_strict_final(row, season)]
    if len(strict_rows) < 2:
        return None
    values = [_values(row) for row in strict_rows]

    # Immutable settlement identity must be fully present and identical.
    merged: dict[str, Any] = {"game_pk": game_pk}
    for field in IMMUTABLE_FIELDS:
        unique = _unique_present(values, field)
        if len(unique) != 1:
            return None
        value = next(iter(unique))
        if value in (None, ""):
            return None
        merged[field] = value

    # A revision resolver is only justified when at least one mutable field differs.
    mutable_conflicts = [field for field in MUTABLE_FIELDS if len(_unique_present(values, field)) > 1]
    if not mutable_conflicts:
        return None

    # Never select one conflicting mutable value heuristically. Force live hydration.
    merged.update({field: None for field in MUTABLE_FIELDS})
    merged["schedule_row_count"] = len(strict_rows)
    merged["raw_schedule_row_count"] = len(rows)
    merged["strict_final_row_count"] = len(strict_rows)
    merged["reschedule_metadata_row_count"] = len(rows) - len(strict_rows)
    merged["needs_hydration"] = True
    merged["revision_conflict_fields"] = sorted(mutable_conflicts)
    merged["schedule_revision_resolution"] = "AUTHORITATIVE_LIVE_HYDRATION_REQUIRED"
    return merged


def normalize_schedule_games_v4(
    payload: Mapping[str, Any],
    season: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Resolve only settlement-identical strict-final schedule revisions.

    Immutable identity disagreements remain ``DUPLICATE_STRICT_FINAL_CONFLICT``.
    Mutable-only conflicts become hydration candidates and are not canonical until
    the existing live-feed hydration path succeeds.
    """
    candidates, exclusions, stats = normalize_schedule_games_v3(payload, season)

    rows_by_pk: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for date_block in payload.get("dates", []):
        for row in date_block.get("games", []):
            game_pk = _optional_int(row.get("gamePk"))
            if game_pk is not None:
                rows_by_pk[game_pk].append(row)

    resolved_count = 0
    kept_exclusions: list[dict[str, Any]] = []
    for exclusion in exclusions:
        if exclusion.get("reason") != "DUPLICATE_STRICT_FINAL_CONFLICT":
            kept_exclusions.append(exclusion)
            continue
        game_pk = _optional_int(exclusion.get("game_pk"))
        candidate = None if game_pk is None else _revision_candidate(game_pk, rows_by_pk.get(game_pk, ()), season)
        if candidate is None:
            kept_exclusions.append(exclusion)
            continue
        candidates.append(candidate)
        resolved_count += 1

    candidates.sort(key=lambda item: (
        str(item.get("official_date") or ""),
        str(item.get("event_start_at") or ""),
        int(item["game_pk"]),
    ))
    updated = dict(stats)
    updated["schedule_revision_hydration_candidates"] = resolved_count
    updated["strict_final_conflicts"] = max(0, int(updated.get("strict_final_conflicts", 0)) - resolved_count)
    updated["schedule_candidates"] = int(updated.get("schedule_candidates", 0)) + resolved_count
    return candidates, kept_exclusions, updated
