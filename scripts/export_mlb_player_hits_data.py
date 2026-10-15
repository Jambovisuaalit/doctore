#!/usr/bin/env python3
"""Export canonical MLB plate appearances and optional pregame context."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mlb_player_hits_data import (  # noqa: E402
    build_bundle,
    extract_pregame_context,
    fetch_game_feed,
    write_json_create_only,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--feed-json", type=Path, action="append")
    source.add_argument("--game-pk", type=int, action="append")
    parser.add_argument("--timecode")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--extraction-generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--feature-cutoff-at")
    args = parser.parse_args()

    if args.feed_json:
        feeds = [_load(path) for path in args.feed_json]
    else:
        feeds = [fetch_game_feed(game_pk, timecode=args.timecode) for game_pk in args.game_pk]

    extraction = args.extraction_generated_at or datetime.now(timezone.utc).isoformat()
    bundle = build_bundle(feeds, extraction_generated_at=extraction)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    rows_sha = write_json_create_only(output / "plate-appearances.json", bundle["rows"])
    bundle["manifest"]["plate_appearances_sha256"] = rows_sha
    write_json_create_only(output / "manifest.json", bundle["manifest"])

    if args.observed_at or args.feature_cutoff_at:
        if not (args.observed_at and args.feature_cutoff_at):
            parser.error("--observed-at and --feature-cutoff-at must be supplied together")
        contexts = [
            extract_pregame_context(
                feed,
                observed_at=args.observed_at,
                feature_cutoff_at=args.feature_cutoff_at,
            )
            for feed in feeds
        ]
        write_json_create_only(output / "pregame-context.json", contexts)

    print(json.dumps({
        "status": "DATA_ONLY",
        "row_count": bundle["manifest"]["row_count"],
        "event_count": bundle["manifest"]["event_count"],
        "production_eligible": False,
        "output_dir": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
