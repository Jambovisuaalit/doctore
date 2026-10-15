#!/usr/bin/env python3
"""One explicitly authorized provider read; never places or approves bets."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import json
from doctore_mcp.tennis_verification import acquire, VerificationError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--book", required=True)
    p.add_argument("--book-market-id", required=True)
    p.add_argument("--allow-live-fetch", action="store_true")
    args = p.parse_args()
    try:
        result = acquire(args.book, args.book_market_id, allow_live_fetch=args.allow_live_fetch)
        print(json.dumps({"status": "STORED", "freshness_basis": result["freshness_basis"],
                          "source_snapshot_sha256": result["source_snapshot_sha256"]}))
        return 0
    except VerificationError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
