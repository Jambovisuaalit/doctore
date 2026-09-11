#!/usr/bin/env python3
"""Acquire immutable MLB park/bullpen source snapshots for one season."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v2_source_acquisition import (
    SourceAcquisitionError,
    canonical_bytes,
    normalize_game_source,
    normalize_schedule_games,
    sha256_bytes,
)

USER_AGENT = "Doctore-Sports/1.0 mlb-v2-source-acquisition"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args()


def fetch_bytes(url: str, *, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=90) as response:
                if getattr(response, "status", 200) != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read()
        except HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                break
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else float(2 ** (attempt - 1))
        except (URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            delay = float(2 ** (attempt - 1))
        if attempt < attempts:
            time.sleep(delay)
    raise RuntimeError(f"fetch failed after {attempts} attempts: {url}: {last}")


def acquire_one(game: dict) -> tuple[dict | None, dict | None]:
    game_pk = int(game["game_pk"])
    try:
        boxscore = fetch_bytes(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore")
        timestamps = fetch_bytes(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live/timestamps")
        return normalize_game_source(game, boxscore_bytes=boxscore, timestamps_bytes=timestamps), None
    except (RuntimeError, SourceAcquisitionError) as exc:
        return None, {"game_pk": game_pk, "reason": type(exc).__name__, "detail": str(exc)}


def main() -> int:
    args = parse_args()
    if not 1900 <= args.season <= 2100:
        raise SystemExit("invalid --season")
    if not 1 <= args.workers <= 16:
        raise SystemExit("--workers must be 1..16")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)

    schedule_url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({
        "sportId": 1,
        "season": args.season,
        "gameType": "R",
    })
    schedule_raw = fetch_bytes(schedule_url)
    schedule_payload = json.loads(schedule_raw.decode("utf-8"))
    games, schedule_rejects = normalize_schedule_games(schedule_payload, args.season)
    if not games:
        raise RuntimeError("no eligible 9-inning final regular-season games")

    records: list[dict] = []
    fetch_rejects: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(acquire_one, game): int(game["game_pk"]) for game in games}
        completed = 0
        for future in as_completed(futures):
            record, reject = future.result()
            if record is not None:
                records.append(record)
            if reject is not None:
                fetch_rejects.append(reject)
            completed += 1
            if completed % 250 == 0 or completed == len(games):
                print(f"season={args.season} completed={completed}/{len(games)} records={len(records)} rejects={len(fetch_rejects)}", flush=True)

    records.sort(key=lambda item: (item["official_date"], item["event_start_at"], item["game_pk"]))
    fetch_rejects.sort(key=lambda item: item["game_pk"])
    all_rejects = schedule_rejects + fetch_rejects
    reason_counts = Counter(
        reason
        for item in schedule_rejects
        for reason in item.get("reasons", [])
    )
    reason_counts.update(item["reason"] for item in fetch_rejects)

    jsonl = b"".join(canonical_bytes(record) for record in records)
    records_path = out / f"mlb-v2-feature-sources-{args.season}.jsonl"
    records_path.write_bytes(jsonl)
    rejects_payload = {
        "schema_version": "doctore.mlb-feature-source-rejects.v1",
        "season": args.season,
        "rejects": all_rejects,
    }
    rejects_bytes = canonical_bytes(rejects_payload)
    (out / "rejects.json").write_bytes(rejects_bytes)

    manifest = {
        "schema_version": "doctore.mlb-feature-source-manifest.v1",
        "season": args.season,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MLB StatsAPI",
        "schedule_url": schedule_url,
        "schedule_sha256": sha256_bytes(schedule_raw),
        "eligible_schedule_games": len(games),
        "normalized_source_records": len(records),
        "schedule_reject_count": len(schedule_rejects),
        "fetch_or_normalization_reject_count": len(fetch_rejects),
        "reason_counts": dict(sorted(reason_counts.items())),
        "records_file": records_path.name,
        "records_sha256": sha256_bytes(jsonl),
        "rejects_sha256": sha256_bytes(rejects_bytes),
        "acquisition_policy": "explicit_rejects_no_silent_drop",
        "workers": args.workers,
    }
    manifest_bytes = canonical_bytes(manifest)
    (out / "manifest.json").write_bytes(manifest_bytes)
    (out / "manifest.sha256").write_text(sha256_bytes(manifest_bytes) + "\n", encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
