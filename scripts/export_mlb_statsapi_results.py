#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_statsapi_results import export_seasons
from mlb_dataset_v1 import RESULT_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export final MLB regular-season results to the dataset-v1 result contract."
    )
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.end_year < args.start_year:
        raise ValueError("end-year must be >= start-year")
    if args.output.exists():
        raise FileExistsError(f"create-only output already exists: {args.output}")
    rows = export_seasons(range(args.start_year, args.end_year + 1))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RESULT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} final MLB games to {args.output}")


if __name__ == "__main__":
    main()
