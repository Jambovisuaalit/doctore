#!/usr/bin/env python3
"""Acquire bullpen-only history for played MLB target-domain exclusions."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import acquire_mlb_v2_sources as base
from mlb_v2_schedule_resolution_v4 import normalize_schedule_games_v4
from mlb_v2_source_acquisition import canonical_bytes, sha256_bytes
from mlb_v4_bullpen_history import (
    BullpenHistorySupplementError, authoritative_played_domain_game,
    normalize_bullpen_history_source,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1900 <= args.season <= 2100:
        raise SystemExit("invalid --season")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    schedule_url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({
        "sportId": 1, "season": args.season, "gameType": "R",
    })
    schedule_raw = base.fetch_bytes(schedule_url)
    schedule = json.loads(schedule_raw.decode("utf-8"))
    candidates, exclusions, stats = normalize_schedule_games_v4(schedule, args.season)

    review_pks: set[int] = {
        int(item["game_pk"]) for item in exclusions
        if item.get("reason") in {"NON_NINE_INNING_DOMAIN", "COMPLETED_EARLY_DOMAIN"}
        and item.get("game_pk") is not None
    }
    review_pks.update(
        int(item["game_pk"]) for item in candidates if item.get("needs_hydration")
    )

    records = []
    rejects = []
    skipped = []
    classification_counts = Counter()

    for index, game_pk in enumerate(sorted(review_pks), start=1):
        live_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        try:
            live_bytes = base.fetch_bytes(live_url)
            live_payload = json.loads(live_bytes.decode("utf-8"))
            game, reason = authoritative_played_domain_game(
                live_payload, expected_game_pk=game_pk, expected_season=args.season,
            )
        except (RuntimeError, UnicodeDecodeError, json.JSONDecodeError, BullpenHistorySupplementError) as exc:
            code = exc.code if isinstance(exc, BullpenHistorySupplementError) else "LIVE_CLASSIFICATION_FAILED"
            rejects.append({"game_pk": game_pk, "stage": "classification", "reason": code, "detail": str(exc)})
            classification_counts[code] += 1
            continue

        classification_counts[reason] += 1
        if game is None:
            skipped.append({"game_pk": game_pk, "reason": reason})
            continue
        if reason == "STANDARD_TARGET_DOMAIN":
            skipped.append({"game_pk": game_pk, "reason": reason})
            continue

        try:
            timestamps = base.fetch_bytes(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live/timestamps")
            boxscore = base.fetch_bytes(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore")
            record = normalize_bullpen_history_source(
                game, domain_exclusion_reason=reason, timestamps_bytes=timestamps,
                boxscore_bytes=boxscore, live_payload_bytes=live_bytes,
            )
        except (RuntimeError, BullpenHistorySupplementError) as exc:
            code = exc.code if isinstance(exc, BullpenHistorySupplementError) else "SUPPLEMENT_SOURCE_FETCH_FAILED"
            rejects.append({"game_pk": game_pk, "stage": "source", "reason": code, "detail": str(exc)})
            continue
        records.append(record)
        if index % 50 == 0:
            print(f"season={args.season} reviewed={index}/{len(review_pks)} records={len(records)} rejects={len(rejects)}", flush=True)

    records.sort(key=lambda item: (item["official_date"], item["event_start_at"], item["game_pk"]))
    rejects.sort(key=lambda item: (item["game_pk"], item["reason"]))
    skipped.sort(key=lambda item: (item["game_pk"], item["reason"]))
    jsonl = b"".join(canonical_bytes(item) for item in records)
    records_name = f"mlb-v4-bullpen-history-{args.season}.jsonl"
    (args.output_dir / records_name).write_bytes(jsonl)
    rejects_bytes = canonical_bytes({"schema_version": "doctore.mlb-bullpen-history-rejects.v1", "season": args.season, "rejects": rejects})
    skipped_bytes = canonical_bytes({"schema_version": "doctore.mlb-bullpen-history-skips.v1", "season": args.season, "skipped": skipped})
    (args.output_dir / "rejects.json").write_bytes(rejects_bytes)
    (args.output_dir / "skipped.json").write_bytes(skipped_bytes)

    manifest = {
        "schema_version": "doctore.mlb-bullpen-history-manifest.v1",
        "season": args.season,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MLB StatsAPI",
        "schedule_sha256": sha256_bytes(schedule_raw),
        "review_game_pks": len(review_pks),
        "supplemental_records": len(records),
        "classification_skips": len(skipped),
        "reject_count": len(rejects),
        "bullpen_blocked_records": sum(1 for item in records if item.get("bullpen_status") != "PASS"),
        "classification_counts": dict(sorted(classification_counts.items())),
        "records_file": records_name,
        "records_sha256": sha256_bytes(jsonl),
        "rejects_sha256": sha256_bytes(rejects_bytes),
        "skipped_sha256": sha256_bytes(skipped_bytes),
        "policy": "authoritative_played_target_exclusions_bullpen_history_v1",
        "schedule_resolution_stats": stats,
    }
    manifest_bytes = canonical_bytes(manifest)
    (args.output_dir / "manifest.json").write_bytes(manifest_bytes)
    (args.output_dir / "manifest.sha256").write_text(sha256_bytes(manifest_bytes) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if not rejects and manifest["bullpen_blocked_records"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
