"""Export final MLB schedule results into the dataset-v1 result contract."""
from __future__ import annotations

from datetime import datetime
import json
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://statsapi.mlb.com/api/v1/schedule"

TEAM_ID_TO_ABBREVIATION = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "OAK",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


class StatsAPIError(RuntimeError):
    pass


def _default_fetch(url: str, timeout: float) -> Mapping[str, Any]:
    request = Request(url, headers={"User-Agent": "Doctore-Research/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_season_schedule(
    season: int,
    *,
    fetch_json: Callable[[str, float], Mapping[str, Any]] = _default_fetch,
    timeout: float = 60.0,
    retries: int = 3,
) -> Mapping[str, Any]:
    params = {
        "sportId": 1,
        "startDate": f"{season}-01-01",
        "endDate": f"{season}-12-31",
        "gameType": "R",
        "hydrate": "linescore",
    }
    url = BASE_URL + "?" + urlencode(params)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fetch_json(url, timeout)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise StatsAPIError(f"MLB Stats API request failed for season {season}: {last_error}")


def schedule_to_result_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date_block in payload.get("dates", []):
        if not isinstance(date_block, Mapping):
            continue
        for game in date_block.get("games", []):
            if not isinstance(game, Mapping) or game.get("gameType") != "R":
                continue
            status = str(game.get("status", {}).get("detailedState", "")).lower()
            if status not in {"final", "game over", "completed early"}:
                continue
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})
            away_team_id = int(away.get("team", {}).get("id"))
            home_team_id = int(home.get("team", {}).get("id"))
            if away_team_id not in TEAM_ID_TO_ABBREVIATION or home_team_id not in TEAM_ID_TO_ABBREVIATION:
                raise StatsAPIError(f"unknown MLB team id in game {game.get('gamePk')}")
            game_date = str(game.get("officialDate") or date_block.get("date") or "")
            datetime.strptime(game_date, "%Y-%m-%d")
            event_start = str(game.get("gameDate", ""))
            parsed_start = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
            if parsed_start.tzinfo is None:
                raise StatsAPIError(f"gameDate lacks timezone in game {game.get('gamePk')}")
            rows.append({
                "source_game_id": str(game["gamePk"]),
                "game_date": game_date,
                "game_number": int(game.get("gameNumber", 1)),
                "away_team": TEAM_ID_TO_ABBREVIATION[away_team_id],
                "home_team": TEAM_ID_TO_ABBREVIATION[home_team_id],
                "away_runs": int(away["score"]),
                "home_runs": int(home["score"]),
                "event_start_at": parsed_start.isoformat(),
                "status": "final",
            })
    rows.sort(key=lambda row: (row["event_start_at"], row["source_game_id"]))
    ids = [row["source_game_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise StatsAPIError("duplicate gamePk values in schedule response")
    return rows


def export_seasons(seasons: Iterable[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in seasons:
        rows.extend(schedule_to_result_rows(fetch_season_schedule(int(season))))
    rows.sort(key=lambda row: (row["event_start_at"], row["source_game_id"]))
    return rows
