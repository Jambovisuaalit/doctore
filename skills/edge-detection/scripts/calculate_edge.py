#!/usr/bin/env python3
"""Calculate EV, edges, Kelly, and price thresholds."""
from __future__ import annotations
import argparse, json

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--odds",type=float,required=True); ap.add_argument("--probability",type=float,required=True); ap.add_argument("--market-probability",type=float,required=True); ap.add_argument("--minimum-ev",type=float,default=.03); ap.add_argument("--minimum-edge",type=float,default=.015); a=ap.parse_args()
    if a.odds<=1 or not 0<a.probability<1 or not 0<a.market_probability<1:
        print(json.dumps({"error":"invalid odds or probability"})); return 2
    be=1/a.odds; ev=a.probability*a.odds-1; edge=a.probability-a.market_probability; k=max(0,(a.probability*a.odds-1)/(a.odds-1)); min_odds=(1+a.minimum_ev)/a.probability
    decision="QUALIFIES" if ev>=a.minimum_ev and edge>=a.minimum_edge else ("WATCH_PRICE" if a.odds<min_odds else "PASS")
    print(json.dumps({"break_even_probability":be,"ev":ev,"edge_vs_break_even_pp":a.probability-be,"edge_vs_market_pp":edge,"full_kelly":k,"break_even_odds":1/a.probability,"minimum_qualifying_odds":min_odds,"economic_status":decision},separators=(",",":")))
    return 0
if __name__=="__main__": raise SystemExit(main())
