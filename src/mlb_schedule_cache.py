"""Acquire and lock authoritative MLB schedule/results caches.

The cache is intentionally minimal: regular-season games, MLB gamePk identity,
UTC start time, official date, game number, scheduled innings, team IDs and
final scores. Postponed/cancelled placeholders are never emitted as settled
games. Duplicate gamePk records are collapsed only when identical or when a
non-final placeholder is superseded by one final record.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
FINAL_ABSTRACT_STATE = "Final"
EXCLUDED_DETAILED_STATES = {"Postponed", "Cancelled", "Suspended"}
FIELDS = (
    "copyright,totalItems,dates,date,games,gamePk,gameDate,officialDate,"
    "gameType,doubleHeader,gameNumber,scheduledInnings,status,abstractGameState,"
    "detailedState,teams,away,home,score,team,id,name,venue,id,name"
)


class ScheduleCacheError(ValueError):
    """Raised when acquisition or cache integrity checks fail."""


def _canonical_bytes(value: Any) -> bytes:
    text = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def build_schedule_url(year: int, *, base_url: str = MLB_SCHEDULE_URL) -> str:
    if not 1900 <= int(year) <= 2100:
        raise ScheduleCacheError(f"invalid MLB season year: {year}")
    query = urlencode(
        {
            "sportId": 1,
            "startDate": f"{year}-01-01",
            "endDate": f"{year}-12-31",
            "gameType": "R",
            "hydrate": "linescore",
            "fields": FIELDS,
        }
    )
    return f"{base_url}?{query}"


def fetch_schedule_payload(
    url: str,
    *,
    timeout_seconds: float = 90.0,
    attempts: int = 4,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    if attempts < 1:
        raise ScheduleCacheError("attempts must be positive")
    request = Request(
        url, headers={"User-Agent": "Doctore-Sports/1.0 schedule-cache"}
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ScheduleCacheError(
                        f"MLB schedule HTTP status {status}"
                    )
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ScheduleCacheError(
                    "MLB schedule response must be a JSON object"
                )
            return payload
        except Exception as exc:  # network errors vary by runtime
            last_error = exc
            if attempt < attempts:
                sleeper(float(2 ** (attempt - 1)))
    raise ScheduleCacheError(
        f"MLB schedule download failed after {attempts} attempts: {last_error}"
    )


def _minimal_final_game(
    raw: Mapping[str, Any], *, requested_year: int
) -> dict[str, Any] | None:
    if raw.get("gameType") != "R":
        return None
    status = raw.get("status")
    if not isinstance(status, Mapping):
        raise ScheduleCacheError("schedule game is missing status")
    abstract = str(status.get("abstractGameState", ""))
    detailed = str(status.get("detailedState", ""))
    if (
        abstract != FINAL_ABSTRACT_STATE
        or detailed in EXCLUDED_DETAILED_STATES
    ):
        return None

    teams = raw.get("teams")
    away = teams.get("away", {}) if isinstance(teams, Mapping) else {}
    home = teams.get("home", {}) if isinstance(teams, Mapping) else {}
    try:
        official_date = str(raw["officialDate"])
        if int(official_date[:4]) != requested_year:
            return None
        item = {
            "gamePk": int(raw["gamePk"]),
            "gameDate": str(raw["gameDate"]),
            "officialDate": official_date,
            "gameType": "R",
            "doubleHeader": str(raw.get("doubleHeader", "N")),
            "gameNumber": int(raw.get("gameNumber", 1)),
            "scheduledInnings": int(raw.get("scheduledInnings", 9)),
            "status": {
                "abstractGameState": abstract,
                "detailedState": detailed,
            },
            "teams": {
                "away": {
                    "score": int(away["score"]),
                    "team": {
                        "id": int(away["team"]["id"]),
                        "name": str(away["team"].get("name", "")),
                    },
                },
                "home": {
                    "score": int(home["score"]),
                    "team": {
                        "id": int(home["team"]["id"]),
                        "name": str(home["team"].get("name", "")),
                    },
                },
            },
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ScheduleCacheError(
            "final regular-season game is missing required fields"
        ) from exc
    away_id = item["teams"]["away"]["team"]["id"]
    home_id = item["teams"]["home"]["team"]["id"]
    if away_id == home_id:
        raise ScheduleCacheError(
            f"gamePk {item['gamePk']} has identical team IDs"
        )
    return item


def normalize_schedule_payload(
    payload: Mapping[str, Any], *, year: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    dates = payload.get("dates")
    if not isinstance(dates, list):
        raise ScheduleCacheError("MLB schedule payload is missing dates[]")

    raw_games = 0
    state_counts: Counter[str] = Counter()
    final_by_pk: dict[int, dict[str, Any]] = {}
    duplicate_records = 0
    for date_block in dates:
        if not isinstance(date_block, Mapping):
            raise ScheduleCacheError("schedule date block must be an object")
        for raw in date_block.get("games", []):
            if not isinstance(raw, Mapping):
                raise ScheduleCacheError("schedule game must be an object")
            raw_games += 1
            status = raw.get("status")
            detailed = (
                str(status.get("detailedState", "UNKNOWN"))
                if isinstance(status, Mapping)
                else "MISSING"
            )
            state_counts[detailed] += 1
            item = _minimal_final_game(raw, requested_year=year)
            if item is None:
                continue
            game_pk = int(item["gamePk"])
            previous = final_by_pk.get(game_pk)
            if previous is not None:
                duplicate_records += 1
                if previous != item:
                    raise ScheduleCacheError(
                        f"conflicting final records for gamePk {game_pk}"
                    )
                continue
            final_by_pk[game_pk] = item

    if len(final_by_pk) < 100:
        raise ScheduleCacheError(
            f"implausibly small MLB regular-season cache for {year}: "
            f"{len(final_by_pk)} games"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in final_by_pk.values():
        grouped[str(item["officialDate"])].append(item)
    normalized_dates = [
        {
            "date": day,
            "games": sorted(
                games,
                key=lambda game: (game["gameDate"], game["gamePk"]),
            ),
        }
        for day, games in sorted(grouped.items())
    ]
    normalized = {
        "schema_version": "doctore.mlb-schedule-cache.v1",
        "source": "MLB StatsAPI /api/v1/schedule",
        "season": int(year),
        "dates": normalized_dates,
    }
    audit = {
        "season": int(year),
        "raw_game_records": raw_games,
        "final_regular_season_games": len(final_by_pk),
        "duplicate_final_records_collapsed": duplicate_records,
        "status_counts": dict(sorted(state_counts.items())),
        "official_date_min": min(grouped) if grouped else None,
        "official_date_max": max(grouped) if grouped else None,
    }
    return normalized, audit


def write_schedule_cache(
    *,
    normalized: Mapping[str, Any],
    audit: Mapping[str, Any],
    source_url: str,
    output_dir: str | Path,
    retrieved_at: str,
) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    year = int(normalized["season"])
    cache_path = destination / f"mlb-schedule-{year}.json"
    sidecar_path = destination / f"mlb-schedule-{year}.sha256"
    if cache_path.exists() or sidecar_path.exists():
        raise FileExistsError(
            f"immutable schedule cache already exists for {year}"
        )
    payload = dict(normalized)
    payload["retrieved_at"] = retrieved_at
    payload["source_url"] = source_url
    payload["audit"] = dict(audit)
    encoded = _canonical_bytes(payload)
    digest = _sha256_bytes(encoded)
    cache_path.write_bytes(encoded)
    sidecar_path.write_text(digest + "\n", encoding="utf-8")
    cache_path.chmod(0o444)
    sidecar_path.chmod(0o444)
    return {
        "season": year,
        "file": cache_path.name,
        "sha256": digest,
        "game_count": int(audit["final_regular_season_games"]),
        "official_date_min": audit.get("official_date_min"),
        "official_date_max": audit.get("official_date_max"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }


def write_cache_manifest(
    records: Sequence[Mapping[str, Any]],
    *,
    output_dir: str | Path,
    created_at: str,
) -> dict[str, Any]:
    if not records:
        raise ScheduleCacheError(
            "schedule cache manifest requires at least one season"
        )
    destination = Path(output_dir)
    path = destination / "schedule-cache-manifest.json"
    sidecar = destination / "schedule-cache-manifest.sha256"
    if path.exists() or sidecar.exists():
        raise FileExistsError(
            "immutable schedule cache manifest already exists"
        )
    ordered = sorted(
        (dict(record) for record in records),
        key=lambda record: int(record["season"]),
    )
    payload = {
        "schema_version": "doctore.mlb-schedule-cache-manifest.v1",
        "created_at": created_at,
        "source": "MLB StatsAPI",
        "seasons": ordered,
        "total_games": sum(
            int(record["game_count"]) for record in ordered
        ),
        "write_policy": "create-only-no-overwrite",
    }
    encoded = _canonical_bytes(payload)
    digest = _sha256_bytes(encoded)
    path.write_bytes(encoded)
    sidecar.write_text(digest + "\n", encoding="utf-8")
    path.chmod(0o444)
    sidecar.chmod(0o444)
    return payload | {"sha256": digest}


def acquire_schedule_cache(
    *,
    years: Sequence[int],
    output_dir: str | Path,
    fetcher: Callable[[str], Mapping[str, Any]] = fetch_schedule_payload,
) -> dict[str, Any]:
    unique_years = sorted(set(int(year) for year in years))
    if not unique_years:
        raise ScheduleCacheError("at least one year is required")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    for year in unique_years:
        url = build_schedule_url(year)
        raw = fetcher(url)
        normalized, audit = normalize_schedule_payload(raw, year=year)
        records.append(
            write_schedule_cache(
                normalized=normalized,
                audit=audit,
                source_url=url,
                output_dir=output_dir,
                retrieved_at=retrieved_at,
            )
        )
    return write_cache_manifest(
        records, output_dir=output_dir, created_at=retrieved_at
    )
