"""Prior-only rolling MLB offense-process feature materialization."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

OFFENSE_PROCESS_COLUMNS = (
    "away_offense_bb_rate_10", "home_offense_bb_rate_10",
    "away_offense_k_rate_10", "home_offense_k_rate_10",
    "away_offense_hr_rate_10", "home_offense_hr_rate_10",
    "away_offense_hit_rate_10", "home_offense_hit_rate_10",
    "away_offense_pa_per_game_10", "home_offense_pa_per_game_10",
)


class OffenseProcessMaterializationError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OffenseProcessMaterializationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise OffenseProcessMaterializationError(f"{field} must be timezone-aware")
    return parsed


def _team_batting(record: Mapping[str, Any], team_id: int) -> Mapping[str, Any]:
    if int(record.get("away_team_id", -1)) == team_id:
        value = record.get("away_batting")
    elif int(record.get("home_team_id", -1)) == team_id:
        value = record.get("home_batting")
    else:
        raise OffenseProcessMaterializationError(f"team {team_id} not in {record.get('event_id')}")
    if not isinstance(value, Mapping):
        raise OffenseProcessMaterializationError("batting payload missing")
    return value


def _aggregate(last10: Sequence[Mapping[str, Any]], team_id: int) -> dict[str, float]:
    if len(last10) != 10:
        raise OffenseProcessMaterializationError("exactly 10 prior games required")
    total_pa = total_bb = total_k = total_hr = total_h = 0
    for record in last10:
        batting = _team_batting(record, team_id)
        total_pa += int(batting["plate_appearances"])
        total_bb += int(batting["walks"])
        total_k += int(batting["strikeouts"])
        total_hr += int(batting["home_runs"])
        total_h += int(batting["hits"])
    if total_pa <= 0:
        raise OffenseProcessMaterializationError("rolling plate appearances must be positive")
    return {
        "bb_rate_10": total_bb / total_pa,
        "k_rate_10": total_k / total_pa,
        "hr_rate_10": total_hr / total_pa,
        "hit_rate_10": total_h / total_pa,
        "pa_per_game_10": total_pa / 10.0,
    }


def materialize_offense_process_group(
    target_event: Mapping[str, Any], *, feature_cutoff_at: str,
    source_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    event_id = str(target_event.get("event_id", "")).strip()
    if not event_id:
        raise OffenseProcessMaterializationError("target event_id missing")
    cutoff = _ts(feature_cutoff_at, "feature_cutoff_at")
    try:
        away_team_id = int(target_event["away_team_id"])
        home_team_id = int(target_event["home_team_id"])
        season = int(str(target_event["official_date"])[:4])
    except (KeyError, TypeError, ValueError) as exc:
        raise OffenseProcessMaterializationError("target identity missing") from exc
    selected: dict[int, list[Mapping[str, Any]]] = {away_team_id: [], home_team_id: []}
    seen_events: set[str] = set()
    seen_games: set[str] = set()
    for record in source_records:
        source_id = str(record.get("event_id", "")).strip()
        game_id = str(record.get("game_pk", "")).strip()
        if not source_id or source_id in seen_events or (game_id and game_id in seen_games):
            raise OffenseProcessMaterializationError("duplicate or missing source event identity")
        seen_events.add(source_id)
        if game_id:
            seen_games.add(game_id)
        if record.get("offense_status") != "PASS" or not record.get("offense_history_eligible"):
            continue
        if int(str(record.get("official_date", "0000"))[:4]) != season:
            continue
        source_event_id = str(record.get("event_id", "")).strip()
        if source_event_id == event_id:
            continue
        final_at = _ts(record.get("final_event_at"), f"final_event_at[{source_event_id}]")
        if final_at >= cutoff:
            continue
        for team_id in (away_team_id, home_team_id):
            if team_id in {int(record.get("away_team_id", -1)), int(record.get("home_team_id", -1))}:
                selected[team_id].append(record)
    for team_id in selected:
        selected[team_id].sort(key=lambda r: (_ts(r["final_event_at"], "final_event_at"), str(r["event_id"])))
        selected[team_id] = selected[team_id][-10:]
    if len(selected[away_team_id]) != 10 or len(selected[home_team_id]) != 10:
        return {
            "event_id": event_id, "feature_group": "offense_process",
            "status": "BLOCKED_PROVENANCE", "feature_cutoff_at": feature_cutoff_at,
            "reason_codes": ["OFFENSE_PROCESS_LAST10_INCOMPLETE"], "features": {}, "provenance": None,
        }
    away = _aggregate(selected[away_team_id], away_team_id)
    home = _aggregate(selected[home_team_id], home_team_id)
    features = {
        "away_offense_bb_rate_10": away["bb_rate_10"],
        "home_offense_bb_rate_10": home["bb_rate_10"],
        "away_offense_k_rate_10": away["k_rate_10"],
        "home_offense_k_rate_10": home["k_rate_10"],
        "away_offense_hr_rate_10": away["hr_rate_10"],
        "home_offense_hr_rate_10": home["hr_rate_10"],
        "away_offense_hit_rate_10": away["hit_rate_10"],
        "home_offense_hit_rate_10": home["hit_rate_10"],
        "away_offense_pa_per_game_10": away["pa_per_game_10"],
        "home_offense_pa_per_game_10": home["pa_per_game_10"],
    }
    sources = {}
    for rows in selected.values():
        for record in rows:
            sources[str(record["event_id"])] = record
    ordered = sorted(sources.values(), key=lambda r: (_ts(r["final_event_at"], "final_event_at"), str(r["event_id"])))
    evidence = {
        "event_id": event_id, "feature_group": "offense_process",
        "feature_cutoff_at": feature_cutoff_at,
        "source_events": [{"event_id": str(r["event_id"]), "end_at": str(r["final_event_at"]), "source_sha256": str(r["source_sha256"])} for r in ordered],
        "window_policy": "last_10_completed_played_same_season_games_per_team",
    }
    raw=(json.dumps(evidence,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()
    digest=sha256(raw).hexdigest()
    return {
        "event_id": event_id, "feature_group": "offense_process", "status": "PASS",
        "feature_cutoff_at": feature_cutoff_at, "reason_codes": [], "features": features,
        "provenance": {
            "schema_version": "doctore.feature-provenance.v1",
            "event_id": event_id, "feature_group": "offense_process",
            "source": "MLB StatsAPI authoritative team batting boxscores",
            "source_record_id": f"mlb-offense-process:{event_id}:{digest[:16]}",
            "availability_mode": "PRIOR_EVENT_FINAL",
            "feature_cutoff_at": feature_cutoff_at, "source_sha256": digest,
            "source_events": [{"event_id": x["event_id"], "end_at": x["end_at"]} for x in evidence["source_events"]],
        },
    }
