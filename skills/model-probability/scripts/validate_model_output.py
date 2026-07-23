#!/usr/bin/env python3
"""Validate provenance and basic range constraints for model output JSON."""
from __future__ import annotations
import argparse, json
from pathlib import Path
REQ=["model_name","model_version","target_market","selection","probability_calibrated","prediction_generated_at","feature_cutoff_at","calibration_status"]
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("input",type=Path); a=ap.parse_args(); d=json.loads(a.input.read_text(encoding="utf-8")); errors=[]
    for k in REQ:
        if d.get(k) in (None,""): errors.append(f"missing.{k}")
    p=d.get("probability_calibrated")
    if not isinstance(p,(int,float)) or not 0<p<1: errors.append("invalid.probability_calibrated")
    if d.get("calibration_status") not in {"validated","calibrated","uncalibrated","unknown"}: errors.append("invalid.calibration_status")
    print(json.dumps({"valid":not errors,"errors":errors},separators=(",",":"))); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
