"""Deterministic MLB context validation for Doctore betting decisions."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
import json

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "skills" / "sport-specific" / "mlb" / "contracts" / "mlb-context.schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


VALIDATOR = Draft202012Validator(_load_schema(), format_checker=FormatChecker())


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def validate_mlb_context_schema(context: Mapping[str, Any]) -> list[str]:
    """Return stable, human-readable schema errors."""
    errors = sorted(
        VALIDATOR.iter_errors(context),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    formatted: list[str] = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        formatted.append(f"{path}: {error.message}")
    return formatted


def evaluate_mlb_context(
    context: Mapping[str, Any],
    *,
    market_snapshot: Mapping[str, Any],
    evaluated_at: str,
    max_age_seconds: int,
) -> dict[str, Any]:
    """Return MLB context status without modifying the model probability.

    Status meanings:
    - VALID: all required assumptions remain compatible.
    - WATCH: required facts are projected, stale, or unconfirmed.
    - BLOCKED: a critical model or settlement assumption changed.
    """
    schema_errors = validate_mlb_context_schema(context)
    if schema_errors:
        return {
            "sport": "MLB",
            "status": "BLOCKED",
            "reason_codes": ["INPUT_SCHEMA_INVALID"],
            "diagnostics": schema_errors,
        }

    blocked: list[str] = []
    watch: list[str] = []
    diagnostics: list[str] = []

    if context["event_id"] != market_snapshot.get("event_id"):
        blocked.append("MLB_CONTEXT_EVENT_MISMATCH")

    evaluated = _parse_datetime(evaluated_at)
    captured = _parse_datetime(str(context["captured_at"]))
    age_seconds = (evaluated - captured).total_seconds()
    if age_seconds < 0:
        blocked.append("TIMESTAMP_IN_FUTURE")
    elif age_seconds > max_age_seconds:
        watch.append("MLB_CONTEXT_STALE")

    settlement = context["settlement"]
    if settlement["pitcher_rule"] == "listed" and settlement["listed_pitchers_match"] is not True:
        blocked.append("MLB_LISTED_PITCHER_MISMATCH")

    dependencies = context["model_dependencies"]
    starters = context["starters"]
    starter_statuses = [starters["home"]["status"], starters["away"]["status"]]
    if "changed" in starter_statuses:
        blocked.append("MLB_STARTER_CHANGED")
    elif dependencies["requires_confirmed_starters"] and any(
        status != "confirmed" for status in starter_statuses
    ):
        watch.append("MLB_STARTER_UNCONFIRMED")

    lineup_statuses = [context["lineups"]["home"], context["lineups"]["away"]]
    if "material_change" in lineup_statuses:
        blocked.append("MLB_LINEUP_CHANGED")
    elif dependencies["requires_lineup_compatibility"] and any(
        status != "confirmed_compatible" for status in lineup_statuses
    ):
        watch.append("MLB_LINEUP_UNCONFIRMED")

    period = str(market_snapshot.get("period", "")).lower()
    is_first_five = period in {"f5", "first_five", "first_5", "first-five"}
    if dependencies["requires_bullpen_state"] and not is_first_five:
        bullpen_statuses = [context["bullpen"]["home"], context["bullpen"]["away"]]
        if any(status != "current" for status in bullpen_statuses):
            watch.append("MLB_BULLPEN_UNAVAILABLE")

    environment = context["environment"]
    for dependency_name, value_name in (
        ("uses_roof", "roof_matches_model"),
        ("uses_weather", "weather_matches_model"),
        ("uses_umpire", "umpire_matches_model"),
    ):
        if not dependencies[dependency_name]:
            continue
        value = environment[value_name]
        if value is False:
            blocked.append("MLB_ENVIRONMENT_MISMATCH")
        elif value is None:
            watch.append("MLB_ENVIRONMENT_UNCONFIRMED")

    blocked = list(dict.fromkeys(blocked))
    watch = list(dict.fromkeys(watch))
    if blocked:
        status = "BLOCKED"
        reasons = blocked
    elif watch:
        status = "WATCH"
        reasons = watch
    else:
        status = "VALID"
        reasons = []

    return {
        "sport": "MLB",
        "status": status,
        "reason_codes": reasons,
        "diagnostics": diagnostics,
    }
