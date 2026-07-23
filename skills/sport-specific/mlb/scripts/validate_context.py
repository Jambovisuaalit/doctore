#!/usr/bin/env python3
"""Validate MLB context without altering model probability."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from mlb_context import evaluate_mlb_context


def _read_json(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--market-snapshot", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--max-age-seconds", type=int, required=True)
    args = parser.parse_args()
    try:
        result = evaluate_mlb_context(
            _read_json(args.context),
            market_snapshot=_read_json(args.market_snapshot),
            evaluated_at=args.evaluated_at,
            max_age_seconds=args.max_age_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, separators=(",", ":")))
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
