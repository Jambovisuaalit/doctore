#!/usr/bin/env python3
"""Create an immutable personal-research review packet from market and model JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODEL_VALIDATOR = ROOT / "skills" / "model-probability" / "scripts" / "validate_model_output.py"

EVENT_REQUIRED = (
    "event_id",
    "sport",
    "competition",
    "event_start_at",
    "status",
    "participants",
    "source",
    "retrieved_at",
)
MARKET_REQUIRED = (
    "market_id",
    "book",
    "market_type",
    "period",
    "line",
    "selection",
    "odds_decimal",
    "snapshot_at",
    "outcomes",
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_market_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    event = snapshot.get("event")
    market = snapshot.get("market")
    if not isinstance(event, dict):
        return ["event must be an object"]
    if not isinstance(market, dict):
        return ["market must be an object"]

    for key in EVENT_REQUIRED:
        if key not in event:
            errors.append(f"missing event.{key}")
    for key in MARKET_REQUIRED:
        if key not in market:
            errors.append(f"missing market.{key}")

    participants = event.get("participants")
    if not isinstance(participants, list) or len(participants) != 2:
        errors.append("event.participants must contain exactly two participants")

    odds = market.get("odds_decimal")
    if not isinstance(odds, (int, float)) or isinstance(odds, bool) or odds <= 1:
        errors.append("market.odds_decimal must be greater than 1")

    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        errors.append("market.outcomes must contain at least two outcomes")

    if event.get("event_id") != snapshot.get("event_id", event.get("event_id")):
        errors.append("top-level event_id conflicts with event.event_id")
    return errors


def run_model_validator(path: Path) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(MODEL_VALIDATOR), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if not result.stdout:
        raise RuntimeError(result.stderr or "model validator produced no output")
    return result.returncode, json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-snapshot", required=True, type=Path)
    parser.add_argument("--model-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--analysis-notes", type=Path)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"create-only output already exists: {args.output}")

    market_snapshot = load_object(args.market_snapshot)
    model_output = load_object(args.model_output)
    market_errors = validate_market_snapshot(market_snapshot)
    validator_code, model_validation = run_model_validator(args.model_output)

    model_decision = model_validation.get("decision", "BLOCKED")
    gate = (
        "HUMAN_REVIEW_REQUIRED"
        if not market_errors and validator_code == 0 and model_decision in {"VALIDATED", "UNCALIBRATED"}
        else "BLOCKED"
    )

    notes = None
    if args.analysis_notes:
        notes = args.analysis_notes.read_text(encoding="utf-8")

    packet: dict[str, Any] = {
        "packet_version": "doctore.personal-review.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gate": gate,
        "market_snapshot_sha256": digest(market_snapshot),
        "model_output_sha256": digest(model_output),
        "market_snapshot": market_snapshot,
        "model_output": model_output,
        "validation": {
            "market_valid": not market_errors,
            "market_errors": market_errors,
            "model": model_validation,
        },
        "analysis": {
            "notes": notes,
            "system_decision": None,
            "proposed_stake": None,
            "price_threshold": None,
            "risk_binding_cap": None,
        },
        "human_review": {
            "status": "pending",
            "allowed_decisions": ["approved", "rejected", "watch", "refresh_required"],
            "model_probability_may_be_changed": False,
            "automatic_execution": False,
        },
    }
    packet["packet_sha256"] = digest(packet)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical(packet) + "\n", encoding="utf-8", newline="\n")
    return 0 if gate == "HUMAN_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
