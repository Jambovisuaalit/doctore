"""Normalize authoritative MLB source data for feature-schema v2.

Schedule rows are candidate metadata, not event truth. MLB can return an original
postponed row and a later makeup-final row with the same ``gamePk``. Eligibility
is therefore resolved per unique gamePk using strict played-final semantics.
Only incomplete strict-final candidates require a live-feed hydration fallback.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

SOURCE_SCHEMA_VERSION = "doctore.mlb-feature-source.v1"
CANONICAL_SCHEDULE_FIELDS = (
    "official_date",
    "event_start_at",
    "scheduled_innings",
    "venue_id",
    "away_team_id",
    "home_team_id",
    "away_score",
    "home_score",
)


class SourceAcquisitionError(ValueError):
    pass


class ScheduleResolutionError(SourceAcquisitionError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def mlb_timecode_to_iso(value: str) -> str:
    try:
        parsed = datetime.strptime(str(value), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SourceAcquisitionError(f"invalid MLB timecode: {value!r}") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def final_event_at_from_timestamps(payload: Any) -> str:
    if not isinstance(payload, list) or not payload:
        raise SourceAcquisitionError("timestamps payload must be a non-empty list")
    parsed = [mlb_timecode_to_iso(str(value)) for value in payload]
    return max(parsed)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _is_strict_played_final(raw: Mapping[str, Any]) -> bool:
    if raw.get("gameType") != "R":
        return False
    status = raw.get("status") or {}
    code = str(status.get("statusCode") or status.get("codedGameState") or "").upper()
    return code == "F"


def _schedule_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    venue = raw.get("venue") or {}
    teams = raw.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    return {
        "official_date": str(raw.get("officialDate") or "") or None,
        "event_start_at": str(raw.get("gameDate") or "") or None,
        "scheduled_innings": _optional_int(raw.get("scheduledInnings")),
        "venue_id": _optional_int(venue.get("id")),
        "venue_name": str(venue.get("name") or "") or None,
        "away_team_id": _optional_int(_nested(away, "team", "id")),
        "home_team_id": _optional_int(_nested(home, "team", "id")),
        "away_score": _optional_int(away.get("score")),
        "home_score": _optional_int(home.get("score")),
    }


def _merge_strict_final_rows(game_pk: int, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [_schedule_values(row) for row in rows]
    merged: dict[str, Any] = {"game_pk": game_pk}
    conflicts: list[str] = []
    for field in (*CANONICAL_SCHEDULE_FIELDS, "venue_name"):
        present = [value[field] for value in values if value.get(field) not in (None, "")]
        unique = {json.dumps(item, sort_keys=True) for item in present}
        if len(unique) > 1:
            conflicts.append(field)
        merged[field] = present[0] if present else None
    if conflicts:
        raise ScheduleResolutionError(
            "DUPLICATE_STRICT_FINAL_CONFLICT",
            f"gamePk={game_pk} conflicting strict-final fields: {sorted(conflicts)}",
        )
    merged["schedule_row_count"] = len(rows)
    merged["needs_hydration"] = any(merged.get(field) in (None, "") for field in CANONICAL_SCHEDULE_FIELDS)
    return merged


def normalize_schedule_games(
    payload: Mapping[str, Any],
    season: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Return unique strict-final candidates, exclusions and schedule accounting.

    Rows are grouped by ``gamePk`` before any field-completeness decision. A
    postponed/rescheduled row that shares gamePk with a strict played-final row is
    counted as metadata, not as a rejected game.
    """
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    row_without_game_pk = 0
    raw_rows = 0
    for date_block in payload.get("dates", []):
        for raw in date_block.get("games", []):
            raw_rows += 1
            game_pk = _optional_int(raw.get("gamePk"))
            if not game_pk:
                row_without_game_pk += 1
                continue
            grouped[game_pk].append(raw)

    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    duplicate_rows = 0
    metadata_rows = 0
    strict_final_unique = 0
    known_domain_exclusions = 0
    strict_final_conflicts = 0

    for game_pk, rows in grouped.items():
        duplicate_rows += max(0, len(rows) - 1)
        strict_rows = [row for row in rows if _is_strict_played_final(row)]
        metadata_rows += len(rows) - len(strict_rows)
        if not strict_rows:
            exclusions.append({
                "game_pk": game_pk,
                "reason": "NO_STRICT_PLAYED_FINAL_ROW",
                "schedule_row_count": len(rows),
                "status_codes": sorted({
                    str((row.get("status") or {}).get("statusCode") or (row.get("status") or {}).get("codedGameState") or "")
                    for row in rows
                }),
            })
            continue

        in_season = [row for row in strict_rows if str(row.get("officialDate") or "").startswith(str(season))]
        if not in_season:
            exclusions.append({
                "game_pk": game_pk,
                "reason": "STRICT_FINAL_OFFICIAL_DATE_OUTSIDE_SEASON",
                "schedule_row_count": len(rows),
            })
            continue
        strict_rows = in_season
        strict_final_unique += 1

        try:
            candidate = _merge_strict_final_rows(game_pk, strict_rows)
        except ScheduleResolutionError as exc:
            strict_final_conflicts += 1
            exclusions.append({
                "game_pk": game_pk,
                "reason": exc.code,
                "detail": exc.detail,
                "schedule_row_count": len(rows),
            })
            continue

        candidate["raw_schedule_row_count"] = len(rows)
        candidate["reschedule_metadata_row_count"] = len(rows) - len(strict_rows)
        candidate["strict_final_row_count"] = len(strict_rows)
        innings = candidate.get("scheduled_innings")
        if innings is not None and innings != 9:
            known_domain_exclusions += 1
            exclusions.append({
                "game_pk": game_pk,
                "event_id": f"mlb:{game_pk}",
                "official_date": candidate.get("official_date"),
                "event_start_at": candidate.get("event_start_at"),
                "venue_id": candidate.get("venue_id"),
                "away_team_id": candidate.get("away_team_id"),
                "home_team_id": candidate.get("home_team_id"),
                "reason": "NON_NINE_INNING_DOMAIN",
                "scheduled_innings": innings,
                "schedule_row_count": len(rows),
            })
            continue
        candidates.append(candidate)

    candidates.sort(key=lambda item: (
        str(item.get("official_date") or ""),
        str(item.get("event_start_at") or ""),
        int(item["game_pk"]),
    ))
    stats = {
        "raw_schedule_rows": raw_rows,
        "rows_without_game_pk": row_without_game_pk,
        "unique_schedule_game_pks": len(grouped),
        "duplicate_schedule_rows": duplicate_rows,
        "reschedule_or_nonfinal_metadata_rows": metadata_rows,
        "strict_final_unique_game_pks": strict_final_unique,
        "strict_final_conflicts": strict_final_conflicts,
        "known_domain_exclusions": known_domain_exclusions,
        "schedule_candidates": len(candidates),
    }
    return candidates, exclusions, stats


def _live_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    game_data = payload.get("gameData") or {}
    live_data = payload.get("liveData") or {}
    game = game_data.get("game") or {}
    status = game_data.get("status") or {}
    datetime_data = game_data.get("datetime") or {}
    venue = game_data.get("venue") or {}
    teams = game_data.get("teams") or {}
    linescore = live_data.get("linescore") or {}
    line_teams = linescore.get("teams") or {}
    return {
        "live_game_pk": _optional_int(payload.get("gamePk") or game.get("pk")),
        "game_type": str(game.get("type") or "") or None,
        "status_code": str(status.get("statusCode") or status.get("codedGameState") or "") or None,
        "official_date": str(datetime_data.get("officialDate") or "") or None,
        "event_start_at": str(datetime_data.get("dateTime") or "") or None,
        "scheduled_innings": _optional_int(linescore.get("scheduledInnings") or game.get("scheduledInnings")),
        "venue_id": _optional_int(venue.get("id")),
        "venue_name": str(venue.get("name") or "") or None,
        "away_team_id": _optional_int(_nested(teams, "away", "id")),
        "home_team_id": _optional_int(_nested(teams, "home", "id")),
        "away_score": _optional_int(_nested(line_teams, "away", "runs")),
        "home_score": _optional_int(_nested(line_teams, "home", "runs")),
    }


def hydrate_schedule_candidate(candidate: Mapping[str, Any], live_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fill missing canonical candidate fields from live feed and verify overlaps."""
    game_pk = int(candidate["game_pk"])
    live = _live_values(live_payload)
    if live["live_game_pk"] != game_pk:
        raise ScheduleResolutionError(
            "LIVE_GAME_PK_MISMATCH",
            f"live gamePk={live['live_game_pk']} != candidate {game_pk}",
        )
    if live["game_type"] != "R":
        raise ScheduleResolutionError("LIVE_NOT_REGULAR_SEASON", f"gamePk={game_pk} type={live['game_type']!r}")
    if str(live["status_code"] or "").upper() != "F":
        raise ScheduleResolutionError("LIVE_NOT_FINAL", f"gamePk={game_pk} status={live['status_code']!r}")

    resolved = dict(candidate)
    conflicts: list[str] = []
    for field in (*CANONICAL_SCHEDULE_FIELDS, "venue_name"):
        scheduled = candidate.get(field)
        authoritative = live.get(field)
        if scheduled not in (None, "") and authoritative not in (None, "") and scheduled != authoritative:
            conflicts.append(field)
        elif scheduled in (None, "") and authoritative not in (None, ""):
            resolved[field] = authoritative
    if conflicts:
        raise ScheduleResolutionError(
            "SCHEDULE_LIVE_FIELD_CONFLICT",
            f"gamePk={game_pk} schedule/live conflicts: {sorted(conflicts)}",
        )

    missing = [field for field in CANONICAL_SCHEDULE_FIELDS if resolved.get(field) in (None, "")]
    if missing:
        raise ScheduleResolutionError(
            "HYDRATION_FIELDS_MISSING",
            f"gamePk={game_pk} missing after live hydration: {sorted(missing)}",
        )
    if int(resolved["scheduled_innings"]) != 9:
        raise ScheduleResolutionError(
            "NON_NINE_INNING_DOMAIN",
            f"gamePk={game_pk} scheduled_innings={resolved['scheduled_innings']}",
        )
    resolved["needs_hydration"] = False
    resolved["hydrated_from_live"] = True
    return resolved


def _pitch_count(stats: Mapping[str, Any]) -> int:
    raw = stats.get("pitchesThrown", stats.get("numberOfPitches"))
    if raw is None:
        raise SourceAcquisitionError("pitch count missing")
    value = int(raw)
    if value < 0:
        raise SourceAcquisitionError("negative pitch count")
    return value


def normalize_team_pitching(team_box: Mapping[str, Any], expected_team_id: int) -> dict[str, Any]:
    try:
        actual_team_id = int(team_box["team"]["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceAcquisitionError("boxscore team id missing") from exc
    if actual_team_id != expected_team_id:
        raise SourceAcquisitionError(f"boxscore team mismatch: {actual_team_id} != {expected_team_id}")

    players = team_box.get("players") or {}
    pitcher_ids = [int(value) for value in team_box.get("pitchers", [])]
    if not pitcher_ids:
        raise SourceAcquisitionError("pitcher list missing")

    starters: list[int] = []
    relievers: list[dict[str, int]] = []
    for pitcher_id in pitcher_ids:
        player = players.get(f"ID{pitcher_id}") or {}
        stats = ((player.get("stats") or {}).get("pitching") or {})
        try:
            games_started = int(stats.get("gamesStarted", 0) or 0)
            games_pitched = int(stats.get("gamesPitched", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise SourceAcquisitionError(f"invalid pitching status for {pitcher_id}") from exc
        pitches = _pitch_count(stats)
        if games_started == 1:
            starters.append(pitcher_id)
        elif games_started == 0 and games_pitched > 0:
            relievers.append({"pitcher_id": pitcher_id, "pitches": pitches})
        elif games_started not in {0, 1}:
            raise SourceAcquisitionError(f"unexpected gamesStarted={games_started} for {pitcher_id}")

    if len(starters) != 1:
        raise SourceAcquisitionError(f"starter identity ambiguous: {starters}")
    return {
        "team_id": expected_team_id,
        "starter_id": starters[0],
        "reliever_ids": [item["pitcher_id"] for item in relievers],
        "bullpen_pitches": sum(item["pitches"] for item in relievers),
        "bullpen_appearances": len(relievers),
        "relievers": relievers,
    }


def _block_bullpen(base: dict[str, Any], reason: str, detail: str | None = None) -> None:
    base["bullpen_status"] = "BLOCKED"
    base["bullpen_reason"] = reason
    if detail:
        base["bullpen_detail"] = detail


def normalize_game_source(
    schedule_game: Mapping[str, Any],
    *,
    timestamps_bytes: bytes,
    boxscore_bytes: bytes | None = None,
    bullpen_error: str | None = None,
    hydration_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        timestamps = json.loads(timestamps_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAcquisitionError("invalid timestamps JSON") from exc
    final_event_at = final_event_at_from_timestamps(timestamps)

    base: dict[str, Any] = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "game_pk": int(schedule_game["game_pk"]),
        "event_id": f"mlb:{int(schedule_game['game_pk'])}",
        "official_date": str(schedule_game["official_date"]),
        "event_start_at": str(schedule_game["event_start_at"]),
        "final_event_at": final_event_at,
        "venue": {
            "id": int(schedule_game["venue_id"]),
            "name": str(schedule_game.get("venue_name", "")),
        },
        "away_team_id": int(schedule_game["away_team_id"]),
        "home_team_id": int(schedule_game["home_team_id"]),
        "away_score": int(schedule_game["away_score"]),
        "home_score": int(schedule_game["home_score"]),
        "final_total_runs": int(schedule_game["away_score"]) + int(schedule_game["home_score"]),
        "park_status": "PASS",
        "lineage": {
            "schedule_source": "MLB StatsAPI /api/v1/schedule",
            "live_hydration_source": (
                f"MLB StatsAPI /api/v1.1/game/{int(schedule_game['game_pk'])}/feed/live"
                if hydration_sha256 else None
            ),
            "live_hydration_sha256": hydration_sha256,
            "boxscore_source": f"MLB StatsAPI /api/v1/game/{int(schedule_game['game_pk'])}/boxscore",
            "timestamps_source": f"MLB StatsAPI /api/v1.1/game/{int(schedule_game['game_pk'])}/feed/live/timestamps",
            "boxscore_sha256": sha256_bytes(boxscore_bytes) if boxscore_bytes is not None else None,
            "timestamps_sha256": sha256_bytes(timestamps_bytes),
        },
    }

    if boxscore_bytes is None:
        _block_bullpen(base, bullpen_error or "BOXSCORE_UNAVAILABLE")
    else:
        try:
            boxscore = json.loads(boxscore_bytes.decode("utf-8"))
            away = normalize_team_pitching(
                boxscore.get("teams", {}).get("away", {}),
                int(schedule_game["away_team_id"]),
            )
            home = normalize_team_pitching(
                boxscore.get("teams", {}).get("home", {}),
                int(schedule_game["home_team_id"]),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _block_bullpen(base, "BOXSCORE_JSON_INVALID", str(exc))
        except SourceAcquisitionError as exc:
            _block_bullpen(base, "BULLPEN_NORMALIZATION_BLOCKED", str(exc))
        else:
            base["bullpen_status"] = "PASS"
            base["away_pitching"] = away
            base["home_pitching"] = home

    digest = sha256_bytes(canonical_bytes(base))
    return {
        **base,
        "source_record_id": f"mlb-feature-source:{base['game_pk']}:{digest[:16]}",
        "source_sha256": digest,
    }
