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
    ScheduleResolutionError,
    SourceAcquisitionError,
    canonical_bytes,
    hydrate_schedule_candidate,
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


def reject_context(game: dict, *, stage: str, reason: str, detail: str) -> dict:
    def maybe_int(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "stage": stage,
        "game_pk": maybe_int(game.get("game_pk")),
        "event_id": f"mlb:{int(game['game_pk'])}" if game.get("game_pk") else None,
        "official_date": game.get("official_date"),
        "event_start_at": game.get("event_start_at"),
        "venue_id": maybe_int(game.get("venue_id")),
        "venue_name": game.get("venue_name"),
        "away_team_id": maybe_int(game.get("away_team_id")),
        "home_team_id": maybe_int(game.get("home_team_id")),
        "reason": reason,
        "detail": detail,
    }


def acquire_one(candidate: dict) -> dict:
    game = dict(candidate)
    game_pk = int(game["game_pk"])
    hydration_attempted = bool(game.get("needs_hydration"))
    hydration_sha: str | None = None

    if hydration_attempted:
        live_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        try:
            live_bytes = fetch_bytes(live_url)
        except RuntimeError as exc:
            return {
                "record": None,
                "reject": reject_context(game, stage="hydration", reason="HYDRATION_FETCH_FAILED", detail=str(exc)),
                "hydration_attempted": True,
                "hydrated": False,
                "hydrated_domain_exclusion": False,
            }
        hydration_sha = sha256_bytes(live_bytes)
        try:
            live_payload = json.loads(live_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "record": None,
                "reject": reject_context(game, stage="hydration", reason="HYDRATION_JSON_INVALID", detail=str(exc)),
                "hydration_attempted": True,
                "hydrated": False,
                "hydrated_domain_exclusion": False,
            }
        try:
            game = hydrate_schedule_candidate(game, live_payload)
        except ScheduleResolutionError as exc:
            return {
                "record": None,
                "reject": reject_context(game, stage="hydration", reason=exc.code, detail=exc.detail),
                "hydration_attempted": True,
                "hydrated": False,
                "hydrated_domain_exclusion": exc.code == "NON_NINE_INNING_DOMAIN",
            }

    timestamps_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live/timestamps"
    try:
        timestamps = fetch_bytes(timestamps_url)
    except RuntimeError as exc:
        return {
            "record": None,
            "reject": reject_context(game, stage="source", reason="TIMESTAMPS_FETCH_FAILED", detail=str(exc)),
            "hydration_attempted": hydration_attempted,
            "hydrated": hydration_attempted,
            "hydrated_domain_exclusion": False,
        }

    boxscore_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    boxscore: bytes | None
    bullpen_error: str | None = None
    try:
        boxscore = fetch_bytes(boxscore_url)
    except RuntimeError as exc:
        boxscore = None
        bullpen_error = "BOXSCORE_FETCH_FAILED"
        print(f"game_pk={game_pk} bullpen blocked: {exc}", flush=True)

    try:
        record = normalize_game_source(
            game,
            boxscore_bytes=boxscore,
            timestamps_bytes=timestamps,
            bullpen_error=bullpen_error,
            hydration_sha256=hydration_sha,
        )
    except SourceAcquisitionError as exc:
        return {
            "record": None,
            "reject": reject_context(
                game,
                stage="source",
                reason="TIMESTAMP_OR_CORE_NORMALIZATION_FAILED",
                detail=str(exc),
            ),
            "hydration_attempted": hydration_attempted,
            "hydrated": hydration_attempted,
            "hydrated_domain_exclusion": False,
        }
    return {
        "record": record,
        "reject": None,
        "hydration_attempted": hydration_attempted,
        "hydrated": hydration_attempted,
        "hydrated_domain_exclusion": False,
    }


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
    games, raw_schedule_exclusions, schedule_stats = normalize_schedule_games(schedule_payload, args.season)
    schedule_exclusions = [{"stage": "schedule", **item} for item in raw_schedule_exclusions]
    if not games:
        raise RuntimeError("no strict-final MLB schedule candidates")

    records: list[dict] = []
    runtime_rejects: list[dict] = []
    hydration_attempted = 0
    hydrated_candidates = 0
    hydrated_domain_exclusions = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(acquire_one, game): int(game["game_pk"]) for game in games}
        completed = 0
        for future in as_completed(futures):
            result = future.result()
            if result["record"] is not None:
                records.append(result["record"])
            if result["reject"] is not None:
                runtime_rejects.append(result["reject"])
            hydration_attempted += int(result["hydration_attempted"])
            hydrated_candidates += int(result["hydrated"])
            hydrated_domain_exclusions += int(result["hydrated_domain_exclusion"])
            completed += 1
            if completed % 250 == 0 or completed == len(games):
                bullpen_blocked = sum(1 for item in records if item.get("bullpen_status") != "PASS")
                print(
                    f"season={args.season} completed={completed}/{len(games)} "
                    f"records={len(records)} runtime_rejects={len(runtime_rejects)} "
                    f"hydrated={hydrated_candidates} bullpen_blocked={bullpen_blocked}",
                    flush=True,
                )

    records.sort(key=lambda item: (item["official_date"], item["event_start_at"], item["game_pk"]))
    runtime_rejects.sort(key=lambda item: (item.get("game_pk") or -1, item["reason"]))
    all_rejects = schedule_exclusions + runtime_rejects

    reason_counts = Counter(item["reason"] for item in all_rejects)
    reason_counts.update(
        str(item.get("bullpen_reason"))
        for item in records
        if item.get("bullpen_status") != "PASS"
    )

    source_reject_count = sum(1 for item in runtime_rejects if item.get("stage") == "source")
    hydration_reject_count = sum(
        1
        for item in runtime_rejects
        if item.get("stage") == "hydration" and item.get("reason") != "NON_NINE_INNING_DOMAIN"
    )
    park_pass_records = sum(1 for item in records if item.get("park_status") == "PASS")
    bullpen_pass_records = sum(1 for item in records if item.get("bullpen_status") == "PASS")
    bullpen_blocked_records = len(records) - bullpen_pass_records

    jsonl = b"".join(canonical_bytes(record) for record in records)
    records_path = out / f"mlb-v2-feature-sources-{args.season}.jsonl"
    records_path.write_bytes(jsonl)
    rejects_payload = {
        "schema_version": "doctore.mlb-feature-source-rejects.v2",
        "season": args.season,
        "rejects": all_rejects,
    }
    rejects_bytes = canonical_bytes(rejects_payload)
    (out / "rejects.json").write_bytes(rejects_bytes)

    manifest = {
        "schema_version": "doctore.mlb-feature-source-manifest.v2",
        "season": args.season,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MLB StatsAPI",
        "schedule_url": schedule_url,
        "schedule_sha256": sha256_bytes(schedule_raw),
        **schedule_stats,
        "eligible_schedule_games": len(games),
        "hydration_attempted": hydration_attempted,
        "hydrated_candidates": hydrated_candidates,
        "hydration_reject_count": hydration_reject_count,
        "hydrated_domain_exclusions": hydrated_domain_exclusions,
        "normalized_source_records": len(records),
        "park_pass_records": park_pass_records,
        "bullpen_pass_records": bullpen_pass_records,
        "bullpen_blocked_records": bullpen_blocked_records,
        "schedule_exclusion_count": len(schedule_exclusions),
        "timestamp_or_core_reject_count": source_reject_count,
        "fetch_or_normalization_reject_count": source_reject_count + hydration_reject_count,
        "reason_counts": dict(sorted(reason_counts.items())),
        "records_file": records_path.name,
        "records_sha256": sha256_bytes(jsonl),
        "rejects_sha256": sha256_bytes(rejects_bytes),
        "acquisition_policy": "strict_final_gamepk_dedupe_live_hydration_fail_closed_v2",
        "workers": args.workers,
    }
    manifest_bytes = canonical_bytes(manifest)
    (out / "manifest.json").write_bytes(manifest_bytes)
    (out / "manifest.sha256").write_text(sha256_bytes(manifest_bytes) + "\n", encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
