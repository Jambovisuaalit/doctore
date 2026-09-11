#!/usr/bin/env python3
"""Adapt selection-level odds records and optionally exact-join model outputs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_contract_adapter import (  # noqa: E402
    adapt_and_join_selection_record,
    adapt_selection_record,
)


def _load_array(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="selection-level market JSON array")
    parser.add_argument("--model-outputs", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    records = _load_array(args.input)
    models = _load_array(args.model_outputs) if args.model_outputs else None

    if models is None:
        results = [adapt_selection_record(record) for record in records]
    else:
        # Exact model join is intentionally downstream of canonical adaptation.
        results = [adapt_and_join_selection_record(record, models) for record in records]

    status_counts = Counter(result["status"] for result in results)
    reason_counts = Counter(
        reason
        for result in results
        for reason in result.get("reason_codes", [])
    )
    canonical_records = sum(
        1 for result in results
        if (result["status"] == "CANONICAL" if models is None else result["status"] == "MATCHED")
    )
    blocked_records = len(results) - canonical_records

    payload = {
        "schema_version": "doctore.market-contract-adapter-run.v1",
        "input_records": len(records),
        "model_join_requested": models is not None,
        "canonical_records": canonical_records,
        "blocked_records": blocked_records,
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    allowed = {"CANONICAL"} if models is None else {"MATCHED"}
    return 0 if set(status_counts).issubset(allowed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
