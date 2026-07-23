#!/usr/bin/env python3
"""Validate and append a human decision to a SHA-256 chained JSONL log."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "research" / "human_review" / "review.schema.json"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def existing_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"invalid log object on line {line_number}")
        records.append(value)
    return records


def validate_chain(records: list[dict[str, Any]]) -> None:
    previous: str | None = None
    for index, record in enumerate(records, start=1):
        claimed = record.get("record_sha256")
        linked = record.get("previous_record_sha256")
        payload = {key: value for key, value in record.items() if key != "record_sha256"}
        calculated = sha256(canonical(payload).encode("utf-8")).hexdigest()
        if claimed != calculated:
            raise ValueError(f"hash mismatch on log record {index}")
        if linked != previous:
            raise ValueError(f"chain mismatch on log record {index}")
        previous = claimed


def enforce_policy(review: dict[str, Any]) -> None:
    proposed = float(review["proposed_stake"])
    approved = float(review["approved_stake"])
    human = review["human_decision"]
    system = review["system_decision"]

    if approved > proposed:
        raise ValueError("approved_stake may not exceed proposed_stake")
    if system == "BLOCKED" and human == "approved":
        raise ValueError("a BLOCKED system decision cannot be approved")
    if human == "approved":
        if system != "BET":
            raise ValueError("approved requires system_decision BET")
        if approved <= 0:
            raise ValueError("approved decision requires a positive approved_stake")
    elif approved != 0:
        raise ValueError("non-approved decisions require approved_stake 0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()

    review = load_object(args.review)
    schema = load_object(args.schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(review), key=lambda item: list(item.absolute_path))
    if errors:
        messages = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in errors]
        raise ValueError("review schema validation failed: " + "; ".join(messages))

    enforce_policy(review)
    records = existing_records(args.log)
    validate_chain(records)
    if any(record.get("review_id") == review["review_id"] for record in records):
        raise ValueError(f"duplicate review_id: {review['review_id']}")

    previous_hash = records[-1]["record_sha256"] if records else None
    chained = dict(review)
    chained["previous_record_sha256"] = previous_hash
    chained["record_sha256"] = sha256(canonical(chained).encode("utf-8")).hexdigest()

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(chained) + "\n")
        handle.flush()
    print(canonical({"appended": True, "review_id": review["review_id"], "record_sha256": chained["record_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
