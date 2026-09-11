"""Normalize authoritative MLB source data for feature-schema v2.

The normalized record contains only fields required by park/bullpen research and
point-in-time provenance. Network acquisition lives in the CLI; this module is
pure and testable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

SOURCE_SCHEMA_VERSION = "doctore.mlb-feature-source.v1"


class SourceAcquisitionError(ValueError):
    pass


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
    values = [str(value) for value in payload]
    # Fixed YYYYMMDD_HHMMSS format is chronologically lexicographically sortable.
    latest = max(values)
    return mlb_timecode_to_iso(latest)


def normalize_schedule_games(payload: Mapping[str, Any], season: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    games: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for date_block in payload.get("dates", []):
        for raw in date_block.get("games", []):
            game_pk = int(raw.get("gamePk", 0) or 0)
            reasons: list[str] = []
            if raw.get("gameType") != "R":
                reasons.append("NOT_REGULAR_SEASON")
            status = raw.get("status") or {}
            if status.get("abstractGameState") != "Final":
                reasons.append("NOT_FINAL")
            official_date = str(raw.get("officialDate") or "")
            if not official_date.startswith(str(season)):
                reasons.append("OFFICIAL_DATE_OUTSIDE_SEASON")
            scheduled_innings = int(raw.get("scheduledInnings", 9) or 9)
            if scheduled_innings != 9:
                reasons.append("NON_NINE_INNING_DOMAIN")
            teams = raw.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            venue = raw.get("venue") or {}
            try:
                selected = {
                    "game_pk": game_pk,
                    "official_date": official_date,
                    "event_start_at": str(raw["gameDate"]),
                    "scheduled_innings": scheduled_innings,
                    "venue_id": int(venue["id"]),
                    "venue_name": str(venue.get("name", "")),
                    "away_team_id": int(away["team"]["id"]),
                    "home_team_id": int(home["team"]["id"]),
                    "away_score": int(away["score"]),
                    "home_score": int(home["score"]),
                }
            except (KeyError, TypeError, ValueError) as exc:
                reasons.append("SCHEDULE_FIELDS_MISSING")
                selected = {"game_pk": game_pk, "official_date": official_date}
            if not game_pk:
                reasons.append("GAME_PK_MISSING")
            if game_pk in seen:
                reasons.append("DUPLICATE_GAME_PK")
            if reasons:
                rejected.append({"game_pk": game_pk, "reasons": sorted(set(reasons))})
                continue
            seen.add(game_pk)
            games.append(selected)
    games.sort(key=lambda item: (item["official_date"], item["event_start_at"], item["game_pk"]))
    return games, rejected


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


def normalize_game_source(
    schedule_game: Mapping[str, Any],
    *,
    boxscore_bytes: bytes,
    timestamps_bytes: bytes,
) -> dict[str, Any]:
    try:
        boxscore = json.loads(boxscore_bytes.decode("utf-8"))
        timestamps = json.loads(timestamps_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAcquisitionError("invalid upstream JSON") from exc

    away = normalize_team_pitching(boxscore.get("teams", {}).get("away", {}), int(schedule_game["away_team_id"]))
    home = normalize_team_pitching(boxscore.get("teams", {}).get("home", {}), int(schedule_game["home_team_id"]))
    final_event_at = final_event_at_from_timestamps(timestamps)

    base = {
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
        "away_pitching": away,
        "home_pitching": home,
        "lineage": {
            "schedule_source": "MLB StatsAPI /api/v1/schedule",
            "boxscore_source": f"MLB StatsAPI /api/v1/game/{int(schedule_game['game_pk'])}/boxscore",
            "timestamps_source": f"MLB StatsAPI /api/v1.1/game/{int(schedule_game['game_pk'])}/feed/live/timestamps",
            "boxscore_sha256": sha256_bytes(boxscore_bytes),
            "timestamps_sha256": sha256_bytes(timestamps_bytes),
        },
    }
    digest = sha256_bytes(canonical_bytes(base))
    return {
        **base,
        "source_record_id": f"mlb-feature-source:{base['game_pk']}:{digest[:16]}",
        "source_sha256": digest,
    }
