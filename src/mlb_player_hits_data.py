"""Canonical MLB plate-appearance and pregame-context data extraction.

This module is intentionally data-only. It does not estimate probabilities,
calculate EV, size stakes, or place bets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
OFFICIAL_HIT_EVENT_TYPES = frozenset({"single", "double", "triple", "home_run"})
FINAL_STATES = frozenset({"final", "game over", "completed early"})


class MLBPlayerHitsDataError(RuntimeError):
    """Raised when source data cannot satisfy the canonical contract."""


def _parse_datetime(value: str, *, field: str) -> datetime:
    if not value:
        raise MLBPlayerHitsDataError(f"missing {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBPlayerHitsDataError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MLBPlayerHitsDataError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _default_fetch(url: str, timeout: float) -> Mapping[str, Any]:
    request = Request(url, headers={"User-Agent": "Doctore-Research/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_game_feed(
    game_pk: int,
    *,
    timecode: str | None = None,
    fetch_json: Callable[[str, float], Mapping[str, Any]] = _default_fetch,
    timeout: float = 60.0,
    retries: int = 3,
) -> Mapping[str, Any]:
    if game_pk <= 0:
        raise MLBPlayerHitsDataError("game_pk must be positive")
    url = FEED_URL.format(game_pk=game_pk)
    if timecode:
        url += "?" + urlencode({"timecode": timecode})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fetch_json(url, timeout)
        except Exception as exc:  # pragma: no cover - network implementation
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise MLBPlayerHitsDataError(f"MLB feed request failed for gamePk {game_pk}: {last_error}")


def _game_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    game_data = payload.get("gameData")
    if not isinstance(game_data, Mapping):
        raise MLBPlayerHitsDataError("missing gameData")
    game = game_data.get("game")
    datetime_block = game_data.get("datetime")
    teams = game_data.get("teams")
    status = game_data.get("status")
    if not all(isinstance(item, Mapping) for item in (game, datetime_block, teams, status)):
        raise MLBPlayerHitsDataError("incomplete game metadata")

    game_pk = int(game.get("pk"))
    official_date = str(datetime_block.get("officialDate") or "")
    datetime.strptime(official_date, "%Y-%m-%d")
    event_start = _parse_datetime(str(datetime_block.get("dateTime") or ""), field="event_start_at")
    away_team = teams.get("away")
    home_team = teams.get("home")
    if not isinstance(away_team, Mapping) or not isinstance(home_team, Mapping):
        raise MLBPlayerHitsDataError("missing team metadata")

    return {
        "game_pk": game_pk,
        "event_id": f"mlb:{game_pk}",
        "official_date": official_date,
        "slate_id": f"mlb-slate:{official_date}",
        "event_start_at": _iso(event_start),
        "game_number": int(game.get("gameNumber") or 1),
        "away_team_id": int(away_team.get("id")),
        "home_team_id": int(home_team.get("id")),
        "final_state": str(status.get("detailedState") or status.get("abstractGameState") or "").strip(),
    }


def _boxscore_players(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    live_data = payload.get("liveData")
    if not isinstance(live_data, Mapping):
        return {}
    boxscore = live_data.get("boxscore")
    if not isinstance(boxscore, Mapping):
        return {}
    teams = boxscore.get("teams")
    return teams if isinstance(teams, Mapping) else {}


def _player_lookup(payload: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    teams = _boxscore_players(payload)
    for side in ("away", "home"):
        block = teams.get(side)
        if not isinstance(block, Mapping):
            continue
        players = block.get("players")
        if not isinstance(players, Mapping):
            continue
        for player in players.values():
            if not isinstance(player, Mapping):
                continue
            person = player.get("person")
            if isinstance(person, Mapping) and person.get("id") is not None:
                result[int(person["id"])] = player
    return result


def _starter_ids(payload: Mapping[str, Any]) -> set[int]:
    starters: set[int] = set()
    for player_id, player in _player_lookup(payload).items():
        stats = player.get("stats")
        pitching = stats.get("pitching") if isinstance(stats, Mapping) else None
        if isinstance(pitching, Mapping) and int(pitching.get("gamesStarted") or 0) == 1:
            starters.add(player_id)
    return starters


def _batting_order(player: Mapping[str, Any] | None) -> int | None:
    if not isinstance(player, Mapping):
        return None
    raw = player.get("battingOrder")
    if raw in (None, ""):
        return None
    try:
        number = int(str(raw))
    except ValueError:
        return None
    if 100 <= number <= 999:
        number //= 100
    return number if 1 <= number <= 9 else None


def extract_plate_appearances(
    payload: Mapping[str, Any],
    *,
    extraction_generated_at: str | None = None,
    require_final: bool = True,
) -> list[dict[str, Any]]:
    metadata = _game_metadata(payload)
    state = metadata["final_state"].lower()
    if require_final and state not in FINAL_STATES:
        raise MLBPlayerHitsDataError(f"game is not final: {metadata['final_state']!r}")

    extraction_time = (
        _parse_datetime(extraction_generated_at, field="extraction_generated_at")
        if extraction_generated_at
        else datetime.now(timezone.utc)
    )
    source_hash = payload_sha256(payload)
    player_lookup = _player_lookup(payload)
    starter_ids = _starter_ids(payload)

    live_data = payload.get("liveData")
    plays_block = live_data.get("plays") if isinstance(live_data, Mapping) else None
    plays = plays_block.get("allPlays") if isinstance(plays_block, Mapping) else None
    if not isinstance(plays, Sequence):
        raise MLBPlayerHitsDataError("missing liveData.plays.allPlays")

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for play in plays:
        if not isinstance(play, Mapping):
            continue
        about = play.get("about")
        matchup = play.get("matchup")
        result = play.get("result")
        if not all(isinstance(item, Mapping) for item in (about, matchup, result)):
            continue
        if not bool(about.get("isComplete")) or about.get("atBatIndex") is None:
            continue

        batter = matchup.get("batter")
        pitcher = matchup.get("pitcher")
        if not isinstance(batter, Mapping) or not isinstance(pitcher, Mapping):
            continue
        batter_id = int(batter.get("id"))
        pitcher_id = int(pitcher.get("id"))
        at_bat_index = int(about.get("atBatIndex"))
        pa_id = f"mlb:{metadata['game_pk']}:ab:{at_bat_index}"
        if pa_id in seen_ids:
            raise MLBPlayerHitsDataError(f"duplicate plate_appearance_id: {pa_id}")
        seen_ids.add(pa_id)

        half = str(about.get("halfInning") or "").lower()
        if half not in {"top", "bottom"}:
            raise MLBPlayerHitsDataError(f"invalid halfInning for {pa_id}: {half!r}")
        batting_team_id = metadata["away_team_id"] if half == "top" else metadata["home_team_id"]
        fielding_team_id = metadata["home_team_id"] if half == "top" else metadata["away_team_id"]
        event_type = str(result.get("eventType") or "").lower()
        batter_box = player_lookup.get(batter_id)
        bat_side = matchup.get("batSide")
        pitch_hand = matchup.get("pitchHand")

        rows.append({
            "schema_version": "doctore.mlb-pa.v1",
            "data_role": "settled_plate_appearance",
            "source_name": "MLB Stats API game feed",
            "source_game_pk": metadata["game_pk"],
            "source_at_bat_index": at_bat_index,
            "source_payload_sha256": source_hash,
            "event_id": metadata["event_id"],
            "plate_appearance_id": pa_id,
            "official_date": metadata["official_date"],
            "slate_id": metadata["slate_id"],
            "event_start_at": metadata["event_start_at"],
            "play_start_at": about.get("startTime"),
            "play_end_at": about.get("endTime"),
            "game_number": metadata["game_number"],
            "batter_id": f"mlbam:{batter_id}",
            "batter_name": str(batter.get("fullName") or ""),
            "pitcher_id": f"mlbam:{pitcher_id}",
            "pitcher_name": str(pitcher.get("fullName") or ""),
            "batting_team_id": batting_team_id,
            "fielding_team_id": fielding_team_id,
            "inning": int(about.get("inning")),
            "half_inning": half,
            "outs_before": int(about.get("outs") or 0),
            "batting_order_position": _batting_order(batter_box),
            "pitcher_role": "starter" if pitcher_id in starter_ids else "reliever",
            "batter_side": str(bat_side.get("code") or "") if isinstance(bat_side, Mapping) else "",
            "pitcher_hand": str(pitch_hand.get("code") or "") if isinstance(pitch_hand, Mapping) else "",
            "result_event": str(result.get("event") or ""),
            "result_event_type": event_type,
            "is_official_hit": event_type in OFFICIAL_HIT_EVENT_TYPES,
            "is_complete": True,
            "final_game_status": metadata["final_state"],
            "extraction_generated_at": _iso(extraction_time),
        })

    rows.sort(key=lambda row: row["source_at_bat_index"])
    return rows


def extract_pregame_context(
    payload: Mapping[str, Any],
    *,
    observed_at: str,
    feature_cutoff_at: str,
) -> dict[str, Any]:
    metadata = _game_metadata(payload)
    observed = _parse_datetime(observed_at, field="observed_at")
    cutoff = _parse_datetime(feature_cutoff_at, field="feature_cutoff_at")
    start = _parse_datetime(metadata["event_start_at"], field="event_start_at")
    if observed > cutoff:
        raise MLBPlayerHitsDataError("observed_at must be <= feature_cutoff_at")

    game_data = payload.get("gameData")
    probable = game_data.get("probablePitchers") if isinstance(game_data, Mapping) else None
    probable = probable if isinstance(probable, Mapping) else {}
    teams = _boxscore_players(payload)

    lineups: dict[str, list[dict[str, Any]]] = {"away": [], "home": []}
    for side in ("away", "home"):
        block = teams.get(side)
        players = block.get("players") if isinstance(block, Mapping) else None
        if not isinstance(players, Mapping):
            continue
        for player in players.values():
            if not isinstance(player, Mapping):
                continue
            person = player.get("person")
            if not isinstance(person, Mapping) or person.get("id") is None:
                continue
            order = _batting_order(player)
            if order is None:
                continue
            lineups[side].append({
                "player_id": f"mlbam:{int(person['id'])}",
                "player_name": str(person.get("fullName") or ""),
                "batting_order_position": order,
            })
        lineups[side].sort(key=lambda item: item["batting_order_position"])

    starters: dict[str, dict[str, Any] | None] = {"away": None, "home": None}
    for side in ("away", "home"):
        pitcher = probable.get(side)
        if isinstance(pitcher, Mapping) and pitcher.get("id") is not None:
            starters[side] = {
                "player_id": f"mlbam:{int(pitcher['id'])}",
                "player_name": str(pitcher.get("fullName") or ""),
                "status": "probable",
            }

    pregame = observed < start and cutoff < start
    lineup_complete = len(lineups["away"]) == 9 and len(lineups["home"]) == 9
    starter_complete = starters["away"] is not None and starters["home"] is not None
    reason_codes: list[str] = []
    if not pregame:
        reason_codes.append("SNAPSHOT_NOT_PREGAME")
    if not lineup_complete:
        reason_codes.append("LINEUP_INCOMPLETE")
    if not starter_complete:
        reason_codes.append("STARTER_INCOMPLETE")

    return {
        "schema_version": "doctore.mlb-pregame-context.v1",
        "source_name": "MLB Stats API game feed",
        "source_payload_sha256": payload_sha256(payload),
        "event_id": metadata["event_id"],
        "source_game_pk": metadata["game_pk"],
        "official_date": metadata["official_date"],
        "slate_id": metadata["slate_id"],
        "scheduled_start_at": metadata["event_start_at"],
        "observed_at": _iso(observed),
        "feature_cutoff_at": _iso(cutoff),
        "lineup_status": "confirmed" if lineup_complete and pregame else "unavailable",
        "starter_status": "probable" if starter_complete and pregame else "unavailable",
        "away_lineup": lineups["away"],
        "home_lineup": lineups["home"],
        "away_starter": starters["away"],
        "home_starter": starters["home"],
        "training_eligible": bool(pregame and lineup_complete and starter_complete),
        "reason_codes": reason_codes,
    }


def write_json_create_only(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise MLBPlayerHitsDataError(f"refusing to overwrite existing file: {path}")
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_bundle(
    feeds: Iterable[Mapping[str, Any]],
    *,
    extraction_generated_at: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    source_hashes: list[str] = []
    event_ids: set[str] = set()
    for feed in feeds:
        feed_rows = extract_plate_appearances(
            feed,
            extraction_generated_at=extraction_generated_at,
            require_final=True,
        )
        if not feed_rows:
            raise MLBPlayerHitsDataError("final feed produced zero complete plate appearances")
        event_id = feed_rows[0]["event_id"]
        if event_id in event_ids:
            raise MLBPlayerHitsDataError(f"duplicate event in bundle: {event_id}")
        event_ids.add(event_id)
        source_hashes.append(feed_rows[0]["source_payload_sha256"])
        rows.extend(feed_rows)
    rows.sort(key=lambda row: (row["event_start_at"], row["event_id"], row["source_at_bat_index"]))
    return {
        "rows": rows,
        "manifest": {
            "schema_version": "doctore.mlb-pa-dataset-manifest.v1",
            "dataset_role": "historical_settled_plate_appearances",
            "row_count": len(rows),
            "event_count": len(event_ids),
            "event_ids": sorted(event_ids),
            "source_payload_sha256": sorted(source_hashes),
            "identity_policy": "event_id=mlb:{gamePk}; plate_appearance_id=mlb:{gamePk}:ab:{atBatIndex}",
            "split_policy": "chronological_slate_grouped_then_event_grouped",
            "production_eligible": False,
            "reason_codes": ["PREGAME_FEATURE_JOIN_NOT_INCLUDED_IN_PA_OUTCOME_DATASET"],
        },
    }
