#!/usr/bin/env python3
"""One opt-in EU/h2h odds read; expected provider cost one credit. No retries."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from doctore_mcp.tennis_odds import fetch_once,import_quotes,OddsError


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sport-key",required=True)
    p.add_argument("--allow-one-credit",action="store_true")
    args=p.parse_args()
    try:
        payload,quota=fetch_once(args.sport_key,allow_one_credit=args.allow_one_credit)
        tour="atp" if args.sport_key.startswith("tennis_atp_") else "wta"
        data=import_quotes(payload,tour,datetime.now(timezone.utc))
        print(json.dumps({"status":"OK" if data["snapshots"] else "BLOCKED","quota":quota,"data":data},allow_nan=False))
        return 0 if data["snapshots"] else 2
    except OddsError as exc:
        print(json.dumps({"status":"BLOCKED","reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
