#!/usr/bin/env python3
"""Calculate capped fractional-Kelly stake."""
from __future__ import annotations
import argparse, json, math

def main()->int:
    ap=argparse.ArgumentParser();
    for n in ["odds","probability","bankroll","kelly_fraction","max_bet","open_exposure","max_open","daily_turnover","max_daily","league_exposure","max_league","rolling_turnover","max_rolling"]: ap.add_argument(f"--{n.replace('_','-')}",type=float,required=True)
    ap.add_argument("--increment",type=float,default=1.0); a=ap.parse_args(); d=vars(a)
    if d["odds"]<=1 or not 0<d["probability"]<1 or d["bankroll"]<=0: print(json.dumps({"error":"invalid inputs"})); return 2
    full=max(0,(d["probability"]*d["odds"]-1)/(d["odds"]-1)); provisional=d["bankroll"]*full*d["kelly_fraction"]
    caps={"per_bet":d["bankroll"]*d["max_bet"],"open":max(0,d["bankroll"]*d["max_open"]-d["open_exposure"]),"daily":max(0,d["bankroll"]*d["max_daily"]-d["daily_turnover"]),"league":max(0,d["bankroll"]*d["max_league"]-d["league_exposure"]),"rolling":max(0,d["bankroll"]*d["max_rolling"]-d["rolling_turnover"])}
    raw=min([provisional,*caps.values()]); stake=math.floor(raw/d["increment"])*d["increment"] if d["increment"]>0 else raw
    binding=min(caps,key=caps.get) if min(caps.values())<=provisional else "kelly"
    print(json.dumps({"full_kelly":full,"provisional_stake":provisional,"caps":caps,"final_stake":max(0,stake),"binding_cap":binding},separators=(",",":"))); return 0
if __name__=="__main__": raise SystemExit(main())
