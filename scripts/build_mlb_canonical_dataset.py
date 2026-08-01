#!/usr/bin/env python3
"""Resolve historical MLB odds to gamePk and create immutable training inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_canonical_dataset import (
    DatasetBuildError,
    join_odds_to_schedule,
    parse_odds_csv,
    parse_statsapi_schedule,
    write_dataset_bundle,
)
from mlb_canonical_dataset_history import build_canonical_rows_with_schedule


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--odds-csv", required=True, type=Path)
    parser.add_argument("--schedule-json", required=True, type=Path, nargs="+")
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    if source_manifest.get("odds_snapshot_provenance") not in {
        "row_timestamped_pre_game", "documented_pre_game_closing_line"
    }:
        raise DatasetBuildError(
            "source manifest must prove row_timestamped_pre_game or documented_pre_game_closing_line odds"
        )
    odds, odds_audit = parse_odds_csv(args.odds_csv)
    schedule = parse_statsapi_schedule(args.schedule_json)
    joined, join_audit = join_odds_to_schedule(odds, schedule)
    if join_audit["unmatched_odds_source_lines"]:
        raise DatasetBuildError(
            f"unmatched odds rows remain: {len(join_audit['unmatched_odds_source_lines'])}"
        )
    rows, feature_audit = build_canonical_rows_with_schedule(joined, schedule)
    created_at = datetime.now(timezone.utc).isoformat()
    result = write_dataset_bundle(
        rows=rows,
        output_dir=args.output_dir,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        created_at=created_at,
        source_manifest=source_manifest,
        audit={
            "schema_version": "doctore.mlb-leakage-audit.v1",
            "odds": odds_audit,
            "join": join_audit,
            "features": feature_audit,
            "same_day_result_policy": "excluded_until_next_official_date",
            "timestamp_group_policy": "all rows sharing cutoff_group_at are one OOS block",
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
