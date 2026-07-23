#!/usr/bin/env python3
"""Calculate proportional no-vig probabilities from decimal odds."""
from __future__ import annotations
import argparse, json

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--odds",nargs="+",type=float,required=True); a=ap.parse_args()
    if len(a.odds)<2 or any(x<=1 for x in a.odds):
        print(json.dumps({"error":"provide at least two decimal odds greater than 1.0"})); return 2
    implied=[1/x for x in a.odds]; total=sum(implied); fair=[q/total for q in implied]
    print(json.dumps({"odds":a.odds,"raw_implied":implied,"market_sum":total,"overround":total-1,"no_vig":fair},separators=(",",":")))
    return 0
if __name__=="__main__": raise SystemExit(main())
