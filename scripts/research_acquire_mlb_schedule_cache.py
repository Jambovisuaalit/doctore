#!/usr/bin/env python3
"""Research-only acquisition of authoritative MLB 2012-2021 schedule/results cache.

Duplicate gamePk rows are accepted only when every settlement-critical field is
identical. MLB schedule timestamp revisions are collapsed to the earliest
scheduled gameDate and recorded in audit counters. Any identity/score/domain
conflict fails closed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com/api/v1/schedule"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def settlement_fingerprint(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gamePk": item["gamePk"],
        "officialDate": item["officialDate"],
        "gameType": item["gameType"],
        "doubleHeader": item["doubleHeader"],
        "gameNumber": item["gameNumber"],
        "scheduledInnings": item["scheduledInnings"],
        "teams": item["teams"],
    }


def fetch_year(year: int) -> tuple[dict[str, Any], dict[str, Any]]:
    query = urlencode({
        "sportId": 1,
        "startDate": f"{year}-01-01",
        "endDate": f"{year}-12-31",
        "gameType": "R",
        "hydrate": "linescore",
    })
    url = f"{BASE}?{query}"
    request = Request(url, headers={"User-Agent": "Doctore-Sports/1.0 validation-cache"})
    for attempt in range(1, 5):
        try:
            with urlopen(request, timeout=90) as response:
                if getattr(response, "status", 200) != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            if attempt == 4:
                raise RuntimeError(f"{year} download failed: {exc}") from exc
            time.sleep(2 ** (attempt - 1))

    games: dict[int, dict[str, Any]] = {}
    raw_records = 0
    timestamp_revisions = 0
    for date_block in payload.get("dates", []):
        for raw in date_block.get("games", []):
            raw_records += 1
            if raw.get("gameType") != "R":
                continue
            status = raw.get("status") or {}
            if status.get("abstractGameState") != "Final":
                continue
            if status.get("detailedState") in {"Postponed", "Cancelled", "Suspended"}:
                continue
            official_date = str(raw.get("officialDate") or "")
            if not official_date.startswith(str(year)):
                continue
            teams = raw.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            item = {
                "gamePk": int(raw["gamePk"]),
                "gameDate": str(raw["gameDate"]),
                "officialDate": official_date,
                "gameType": "R",
                "doubleHeader": str(raw.get("doubleHeader", "N")),
                "gameNumber": int(raw.get("gameNumber", 1)),
                "scheduledInnings": int(raw.get("scheduledInnings", 9)),
                "status": {
                    "abstractGameState": str(status.get("abstractGameState", "")),
                    "detailedState": str(status.get("detailedState", "")),
                },
                "teams": {
                    "away": {
                        "score": int(away["score"]),
                        "team": {"id": int(away["team"]["id"]), "name": str(away["team"].get("name", ""))},
                    },
                    "home": {
                        "score": int(home["score"]),
                        "team": {"id": int(home["team"]["id"]), "name": str(home["team"].get("name", ""))},
                    },
                },
            }
            pk = item["gamePk"]
            previous = games.get(pk)
            if previous is not None:
                if settlement_fingerprint(previous) != settlement_fingerprint(item):
                    raise RuntimeError(
                        "settlement-critical duplicate gamePk conflict: "
                        + json.dumps({"previous": previous, "current": item}, sort_keys=True)
                    )
                timestamp_revisions += 1
                if item["gameDate"] < previous["gameDate"]:
                    item["status"] = previous["status"]
                    games[pk] = item
                continue
            games[pk] = item

    if len(games) < 100:
        raise RuntimeError(f"implausibly small season {year}: {len(games)}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in games.values():
        grouped[item["officialDate"]].append(item)
    audit = {
        "raw_game_records": raw_records,
        "final_regular_season_games": len(games),
        "non_material_gameDate_revisions_collapsed": timestamp_revisions,
        "official_date_min": min(grouped),
        "official_date_max": max(grouped),
    }
    normalized = {
        "schema_version": "doctore.mlb-schedule-cache.v1",
        "source": "MLB StatsAPI /api/v1/schedule",
        "season": year,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "dates": [
            {"date": day, "games": sorted(items, key=lambda x: (x["gameDate"], x["gamePk"]))}
            for day, items in sorted(grouped.items())
        ],
        "audit": audit,
    }
    return normalized, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2012)
    parser.add_argument("--end-year", type=int, default=2021)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for year in range(args.start_year, args.end_year + 1):
        normalized, audit = fetch_year(year)
        data = canonical_bytes(normalized)
        digest = sha256(data).hexdigest()
        path = args.output_dir / f"mlb-schedule-{year}.json"
        path.write_bytes(data)
        (args.output_dir / f"mlb-schedule-{year}.sha256").write_text(digest + "\n", encoding="utf-8")
        records.append({"season": year, "file": path.name, "sha256": digest, "game_count": audit["final_regular_season_games"], "timestamp_revisions": audit["non_material_gameDate_revisions_collapsed"]})
        print(year, audit["final_regular_season_games"], audit["non_material_gameDate_revisions_collapsed"], digest)
    manifest = {
        "schema_version": "doctore.mlb-schedule-cache-manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MLB StatsAPI",
        "seasons": records,
        "total_games": sum(int(x["game_count"]) for x in records),
        "total_non_material_gameDate_revisions_collapsed": sum(int(x["timestamp_revisions"]) for x in records),
        "write_policy": "workflow-artifact-immutable-per-commit",
    }
    data = canonical_bytes(manifest)
    (args.output_dir / "schedule-cache-manifest.json").write_bytes(data)
    (args.output_dir / "schedule-cache-manifest.sha256").write_text(sha256(data).hexdigest() + "\n", encoding="utf-8")
    if len(records) != args.end_year - args.start_year + 1 or manifest["total_games"] <= 20000:
        raise RuntimeError(f"schedule cache verification failed: {manifest}")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
