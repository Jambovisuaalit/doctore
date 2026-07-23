#!/usr/bin/env python3
"""Evaluate a canonical Doctore betting decision from JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from bet_decision_core import evaluate_bet_decision


def _read_json(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--market-snapshot", required=True)
    parser.add_argument("--portfolio-state", required=True)
    parser.add_argument("--risk-policy", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--sport-context")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        sport_context = _read_json(args.sport_context) if args.sport_context else None
        output = evaluate_bet_decision(
            model_output=_read_json(args.model_output),
            market_snapshot=_read_json(args.market_snapshot),
            portfolio_state=_read_json(args.portfolio_state),
            risk_policy=_read_json(args.risk_policy),
            evaluated_at=args.evaluated_at,
            sport_context=sport_context,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, separators=(",", ":")))
        return 2

    print(
        json.dumps(
            output,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
