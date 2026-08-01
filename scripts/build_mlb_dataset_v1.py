#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_dataset_v1 import build_dataset_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a content-locked MLB full-game totals research dataset."
    )
    parser.add_argument("--odds", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--close-proxy-seconds", type=int, default=60)
    parser.add_argument("--created-at")
    args = parser.parse_args()
    result = build_dataset_files(
        odds_path=args.odds,
        results_path=args.results,
        output_dir=args.output_dir,
        dataset_version=args.dataset_version,
        close_proxy_seconds=args.close_proxy_seconds,
        created_at=args.created_at,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
