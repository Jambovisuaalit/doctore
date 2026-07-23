#!/usr/bin/env python3
"""Validate the minimum Doctore event, market, and model snapshot contract."""
from __future__ import annotations
import argparse, json
from datetime import datetime
from pathlib import Path

REQUIRED_EVENT = ["event_id", "sport", "competition", "event_start_at", "status", "participants"]
REQUIRED_MARKET = ["market_id", "book", "market_type", "period", "selection", "odds_decimal", "snapshot_at", "outcomes"]
REQUIRED_MODEL = ["model_name", "model_version", "target_market", "selection", "probability_calibrated", "prediction_generated_at"]

def iso(value: object) -> bool:
    if not isinstance(value, str): return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00")); return True
    except ValueError: return False

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("input", type=Path); args=ap.parse_args()
    try: data=json.loads(args.input.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"valid":False,"errors":[f"invalid_json: {exc}"]})); return 2
    errors=[]
    event=data.get("event", data)
    market=data.get("market", {})
    model=data.get("model", {})
    for key in REQUIRED_EVENT:
        if key not in event: errors.append(f"missing_event.{key}")
    for key in REQUIRED_MARKET:
        if key not in market: errors.append(f"missing_market.{key}")
    for key in REQUIRED_MODEL:
        if key not in model: errors.append(f"missing_model.{key}")
    if market.get("odds_decimal", 0) <= 1: errors.append("invalid_market.odds_decimal")
    p=model.get("probability_calibrated")
    if not isinstance(p,(int,float)) or not 0 < p < 1: errors.append("invalid_model.probability_calibrated")
    for path, value in [("event.event_start_at",event.get("event_start_at")),("market.snapshot_at",market.get("snapshot_at")),("model.prediction_generated_at",model.get("prediction_generated_at"))]:
        if value is not None and not iso(value): errors.append(f"invalid_timestamp.{path}")
    outcomes=market.get("outcomes", [])
    if not isinstance(outcomes,list) or len(outcomes)<2: errors.append("invalid_market.outcomes")
    result={"valid":not errors,"errors":errors}
    print(json.dumps(result, separators=(",",":")))
    return 0 if not errors else 1
if __name__ == "__main__": raise SystemExit(main())
