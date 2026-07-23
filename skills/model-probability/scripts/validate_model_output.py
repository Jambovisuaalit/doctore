#!/usr/bin/env python3
"""Validate a Doctore model-output JSON document against its canonical schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA = ROOT / "contracts" / "model-output.schema.json"
DOMAIN_FIELDS = (
    "sport",
    "competition",
    "market_type",
    "target_market",
    "period",
    "line",
    "settlement_rules",
)


def _json_path(parts: Any) -> str:
    tokens = [str(part) for part in parts]
    return ".".join(tokens) if tokens else "$"


def _schema_errors(instance: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, str]]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[dict[str, str]] = []
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        path = _json_path(error.absolute_path)
        errors.append(
            {
                "code": f"schema.{path}.{error.validator}",
                "path": path,
                "message": error.message,
            }
        )
    return errors


def _domain_errors(instance: dict[str, Any]) -> list[dict[str, str]]:
    validation_domain = instance.get("validation_domain")
    if not isinstance(validation_domain, dict):
        return []

    errors: list[dict[str, str]] = []
    for field in DOMAIN_FIELDS:
        target_value = instance.get(field)
        validated_value = validation_domain.get(field)
        if target_value != validated_value:
            errors.append(
                {
                    "code": f"domain_mismatch.{field}",
                    "path": f"validation_domain.{field}",
                    "message": (
                        f"Validation domain value {validated_value!r} does not exactly match "
                        f"the prediction target value {target_value!r}."
                    ),
                }
            )
    return errors


def validate_document(instance: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    errors = _schema_errors(instance, schema)
    errors.extend(_domain_errors(instance))

    calibration_status = instance.get("calibration_status")
    if calibration_status == "unknown":
        errors.append(
            {
                "code": "calibration_status.unknown",
                "path": "calibration_status",
                "message": "Unknown calibration provenance is blocked from staking.",
            }
        )

    if errors:
        decision = "BLOCKED"
    elif calibration_status == "validated":
        decision = "VALIDATED"
    elif calibration_status == "uncalibrated":
        decision = "UNCALIBRATED"
    else:
        decision = "BLOCKED"

    return {
        "valid": decision in {"VALIDATED", "UNCALIBRATED"},
        "decision": decision,
        "schema_version": instance.get("schema_version"),
        "model_name": instance.get("model_name"),
        "model_version": instance.get("model_version"),
        "calibration_status": calibration_status,
        "domain_match": not any(error["code"].startswith("domain_mismatch.") for error in errors),
        "errors": errors,
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Top-level JSON value must be an object.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Model-output JSON file to validate.")
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"JSON Schema path (default: {DEFAULT_SCHEMA}).",
    )
    args = parser.parse_args()

    try:
        schema = _load_json(args.schema)
        Draft202012Validator.check_schema(schema)
        instance = _load_json(args.input)
    except (OSError, json.JSONDecodeError, ValueError, SchemaError) as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "decision": "BLOCKED",
                    "errors": [
                        {
                            "code": "validator.input_error",
                            "path": "$",
                            "message": str(exc),
                        }
                    ],
                },
                separators=(",", ":"),
            )
        )
        return 2

    result = validate_document(instance, schema)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
