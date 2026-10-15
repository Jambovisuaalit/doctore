#!/usr/bin/env python3
"""Evaluate a frozen binary OOS holdout; never register or approve a model."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from model_evidence import build_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_evidence(args.csv, json.loads(args.metadata.read_text()))
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"status": report["status"], "reason_codes": report["reason_codes"],
                      "production_approved": False}))
    return 0 if report["status"] == "STATISTICAL_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
