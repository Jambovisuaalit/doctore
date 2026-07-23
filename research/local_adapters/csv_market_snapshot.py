#!/usr/bin/env python3
"""Convert one local CSV row into a Doctore event and market snapshot JSON."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "event_id",
    "sport",
    "competition",
    "event_start_at",
    "status",
    "participant_1",
    "participant_2",
    "source",
    "retrieved_at",
    "market_id",
    "book",
    "market_type",
    "period",
    "line",
    "selection",
    "odds_decimal",
    "snapshot_at",
    "outcome_1_selection",
    "outcome_1_odds_decimal",
    "outcome_2_selection",
    "outcome_2_odds_decimal",
}


def number_or_none(value: str) -> float | None:
    stripped = value.strip()
    return None if not stripped else float(stripped)


def nonempty(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} must be non-empty")
    return value


def snapshot(row: dict[str, str]) -> dict[str, Any]:
    odds = float(nonempty(row, "odds_decimal"))
    outcome_1_odds = float(nonempty(row, "outcome_1_odds_decimal"))
    outcome_2_odds = float(nonempty(row, "outcome_2_odds_decimal"))
    if min(odds, outcome_1_odds, outcome_2_odds) <= 1:
        raise ValueError("all decimal odds must be greater than 1")

    event_id = nonempty(row, "event_id")
    return {
        "event_id": event_id,
        "event": {
            "event_id": event_id,
            "sport": nonempty(row, "sport").upper(),
            "competition": nonempty(row, "competition"),
            "event_start_at": nonempty(row, "event_start_at"),
            "status": nonempty(row, "status"),
            "participants": [nonempty(row, "participant_1"), nonempty(row, "participant_2")],
            "venue": row.get("venue", "").strip() or None,
            "source": nonempty(row, "source"),
            "retrieved_at": nonempty(row, "retrieved_at"),
        },
        "market": {
            "market_id": nonempty(row, "market_id"),
            "book": nonempty(row, "book"),
            "market_type": nonempty(row, "market_type"),
            "period": nonempty(row, "period"),
            "line": number_or_none(row.get("line", "")),
            "selection": nonempty(row, "selection"),
            "odds_decimal": odds,
            "snapshot_at": nonempty(row, "snapshot_at"),
            "outcomes": [
                {
                    "selection": nonempty(row, "outcome_1_selection"),
                    "odds_decimal": outcome_1_odds,
                },
                {
                    "selection": nonempty(row, "outcome_2_selection"),
                    "odds_decimal": outcome_2_odds,
                },
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--row", type=int, default=1, help="1-based data row index")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.row < 1:
        raise ValueError("--row must be at least 1")
    if args.output.exists():
        raise FileExistsError(f"create-only output already exists: {args.output}")

    with args.csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        rows = list(reader)

    if args.row > len(rows):
        raise IndexError(f"row {args.row} does not exist; CSV contains {len(rows)} data rows")

    payload = snapshot(rows[args.row - 1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
