#!/usr/bin/env python3
"""Mechanical validation for a Doctore candidate JSON payload."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

def parse_ts(v: str) -> datetime:
    dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("input",type=Path); ap.add_argument("--now"); ap.add_argument("--max-price-age",type=int,default=300); a=ap.parse_args()
    data=json.loads(a.input.read_text(encoding="utf-8")); errors=[]; warnings=[]
    event=data.get("event",data); market=data.get("market",{}); model=data.get("model",{})
    now=parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if event.get("status") != "scheduled": errors.append("event_not_scheduled")
    try:
        age=(now-parse_ts(market["snapshot_at"])).total_seconds()
        if age < -5: errors.append("price_timestamp_in_future")
        elif age > a.max_price_age: errors.append(f"stale_price:{int(age)}s")
    except Exception: errors.append("invalid_or_missing_price_timestamp")
    outcomes=market.get("outcomes",[])
    if len(outcomes)<2: errors.append("incomplete_outcome_set")
    if any(o.get("odds_decimal",0)<=1 for o in outcomes): errors.append("invalid_outcome_odds")
    p=model.get("probability_calibrated")
    if not isinstance(p,(int,float)) or not 0<p<1: errors.append("invalid_model_probability")
    if model.get("selection") != market.get("selection"): errors.append("model_selection_mismatch")
    status="BLOCKED" if errors else ("WATCH" if warnings else "VALID")
    print(json.dumps({"status":status,"errors":errors,"warnings":warnings},separators=(",",":")))
    return 0 if status=="VALID" else 1
if __name__=="__main__": raise SystemExit(main())
