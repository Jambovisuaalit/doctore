#!/usr/bin/env python3
"""Calculate basic ROI, Brier score, log loss, and price CLV from a CSV bet log."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("csv",type=Path); a=ap.parse_args(); rows=list(csv.DictReader(a.csv.open(encoding="utf-8")))
    settled=[r for r in rows if r.get("result") in {"WIN","LOSS"}]; stake=sum(float(r.get("stake_eur") or r.get("stake") or 0) for r in settled); pnl=sum(float(r.get("profit_loss_eur") or r.get("profit_loss") or 0) for r in settled)
    b=[]; ll=[]; clv=[]
    for r in settled:
        p=float(r.get("model_probability") or 0); y=1 if r["result"]=="WIN" else 0
        if 0<p<1: b.append((p-y)**2); ll.append(-(y*math.log(p)+(1-y)*math.log(1-p)))
        try: clv.append(float(r["odds_taken_decimal"])/float(r["closing_odds_decimal"])-1)
        except Exception: pass
    out={"bets":len(settled),"stake":stake,"profit":pnl,"roi":pnl/stake if stake else None,"brier":sum(b)/len(b) if b else None,"log_loss":sum(ll)/len(ll) if ll else None,"avg_price_clv":sum(clv)/len(clv) if clv else None}
    print(json.dumps(out,separators=(",",":"))); return 0
if __name__=="__main__": raise SystemExit(main())
