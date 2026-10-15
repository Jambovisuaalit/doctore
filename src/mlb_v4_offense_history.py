"""Authoritative MLB offense-history normalization for process features."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from mlb_v2_source_acquisition import (
    SourceAcquisitionError, canonical_bytes, final_event_at_from_timestamps, sha256_bytes,
)

OFFENSE_SOURCE_SCHEMA_VERSION = "doctore.mlb-offense-history.v1"
BATTING_FIELDS = ("plateAppearances", "baseOnBalls", "strikeOuts", "homeRuns", "hits")


class OffenseHistoryError(ValueError):
    pass


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise OffenseHistoryError(f"invalid {field}: {value!r}") from exc
    if result < 0:
        raise OffenseHistoryError(f"negative {field}: {result}")
    return result


def normalize_team_batting(team_box: Mapping[str, Any], expected_team_id: int) -> dict[str, int]:
    try:
        actual_team_id = int((team_box.get("team") or {})["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OffenseHistoryError("boxscore team id missing") from exc
    if actual_team_id != int(expected_team_id):
        raise OffenseHistoryError(f"boxscore team mismatch: {actual_team_id} != {expected_team_id}")
    batting = ((team_box.get("teamStats") or {}).get("batting") or {})
    values = {field: _nonnegative_int(batting.get(field), field) for field in BATTING_FIELDS}
    pa = values["plateAppearances"]
    if pa <= 0:
        raise OffenseHistoryError("played game must have positive plateAppearances")
    if values["hits"] > pa:
        raise OffenseHistoryError("hits exceed plateAppearances")
    if values["homeRuns"] > values["hits"]:
        raise OffenseHistoryError("homeRuns exceed hits")
    if values["baseOnBalls"] > pa:
        raise OffenseHistoryError("baseOnBalls exceed plateAppearances")
    if values["strikeOuts"] > pa:
        raise OffenseHistoryError("strikeOuts exceed plateAppearances")
    return {
        "team_id": actual_team_id,
        "plate_appearances": pa,
        "walks": values["baseOnBalls"],
        "strikeouts": values["strikeOuts"],
        "home_runs": values["homeRuns"],
        "hits": values["hits"],
    }


def normalize_offense_history_source(
    game: Mapping[str, Any], *, timestamps_bytes: bytes, boxscore_bytes: bytes,
    live_hydration_sha256: str | None = None, target_domain_eligible: bool,
    domain_role: str,
) -> dict[str, Any]:
    try:
        timestamps = json.loads(timestamps_bytes.decode("utf-8"))
        boxscore = json.loads(boxscore_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OffenseHistoryError("invalid source JSON") from exc
    try:
        final_event_at = final_event_at_from_timestamps(timestamps)
    except SourceAcquisitionError as exc:
        raise OffenseHistoryError(str(exc)) from exc
    try:
        game_pk = int(game["game_pk"])
        away_team_id = int(game["away_team_id"])
        home_team_id = int(game["home_team_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OffenseHistoryError("game identity missing") from exc
    if away_team_id == home_team_id:
        raise OffenseHistoryError("team ids must differ")
    teams = boxscore.get("teams") or {}
    away = normalize_team_batting(teams.get("away") or {}, away_team_id)
    home = normalize_team_batting(teams.get("home") or {}, home_team_id)
    base = {
        "schema_version": OFFENSE_SOURCE_SCHEMA_VERSION,
        "game_pk": game_pk,
        "event_id": f"mlb:{game_pk}",
        "official_date": str(game["official_date"]),
        "event_start_at": str(game["event_start_at"]),
        "final_event_at": final_event_at,
        "away_team_id": away_team_id,
        "home_team_id": home_team_id,
        "away_batting": away,
        "home_batting": home,
        "offense_status": "PASS",
        "offense_history_eligible": True,
        "target_domain_eligible": bool(target_domain_eligible),
        "domain_role": str(domain_role),
        "lineage": {
            "boxscore_source": f"MLB StatsAPI /api/v1/game/{game_pk}/boxscore",
            "timestamps_source": f"MLB StatsAPI /api/v1.1/game/{game_pk}/feed/live/timestamps",
            "boxscore_sha256": sha256_bytes(boxscore_bytes),
            "timestamps_sha256": sha256_bytes(timestamps_bytes),
            "live_hydration_sha256": live_hydration_sha256,
        },
    }
    digest = sha256_bytes(canonical_bytes(base))
    return {
        **base,
        "source_record_id": f"mlb-offense-history:{game_pk}:{digest[:16]}",
        "source_sha256": digest,
    }
\n\ndef write_sha256_sidecar(path: str | Path, digest: str) -> None:\n    value = str(digest).strip().lower()\n    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):\n        raise OffenseHistoryError("invalid sha256 digest")\n    Path(path).write_text(value + "\\n", encoding="utf-8")\n