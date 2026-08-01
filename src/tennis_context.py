"""Deterministic tennis context and settlement validation for Doctore."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
import json

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "skills"
    / "sport-specific"
    / "tennis"
    / "contracts"
    / "tennis-context.schema.json"
)


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


VALIDATOR = Draft202012Validator(_load_schema(), format_checker=FormatChecker())


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _normalize_identity(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())


def validate_tennis_context_schema(context: Mapping[str, Any]) -> list[str]:
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


def evaluate_tennis_context(
    context: Mapping[str, Any],
    *,
    market_snapshot: Mapping[str, Any],
    evaluated_at: str,
    max_age_seconds: int,
) -> dict[str, Any]:
    """Gate an ATP main-tour best-of-three singles moneyline candidate.

    This function never reads or mutates probability, EV, edge, or Kelly fields.
    It returns only a post-hoc context status, reason codes, and diagnostics.
    """
    schema_errors = validate_tennis_context_schema(context)
    if schema_errors:
        return {
            "status": "BLOCKED",
            "reason_codes": ["INPUT_SCHEMA_INVALID"],
            "diagnostics": schema_errors,
        }

    blocked: list[str] = []
    watch: list[str] = []
    diagnostics: list[str] = []

    if context["event_id"] != market_snapshot.get("event_id"):
        blocked.append("TENNIS_CONTEXT_EVENT_MISMATCH")

    evaluated = _parse_datetime(evaluated_at)
    captured = _parse_datetime(str(context["captured_at"]))
    age_seconds = (evaluated - captured).total_seconds()
    if age_seconds < 0:
        blocked.append("TIMESTAMP_IN_FUTURE")
    elif age_seconds > max_age_seconds:
        watch.append("TENNIS_CONTEXT_STALE")

    if context["scheduled_start_at"] != market_snapshot.get("event_start_at"):
        blocked.append("TENNIS_START_TIME_MISMATCH")

    if context["tour"] != "ATP":
        blocked.append("TENNIS_TOUR_MISMATCH")
    if context["tier"] != "main_tour":
        blocked.append("TENNIS_TIER_MISMATCH")
    if context["market"] != "match_moneyline":
        blocked.append("TENNIS_MARKET_SCOPE_MISMATCH")
    if context["discipline"] != "singles":
        blocked.append("TENNIS_DOUBLES_EXCLUDED")
    if context["draw_stage"] != "main_draw":
        blocked.append("TENNIS_QUALIFYING_EXCLUDED")
    if context["match_format"] != "best_of_3":
        blocked.append("TENNIS_BEST_OF_FIVE_EXCLUDED")
    if context["validation_policy"]["retirements"] != "excluded_from_initial_validation":
        blocked.append("TENNIS_RETIREMENT_POLICY_MISMATCH")

    expected_market_scope = {
        "sport": "TENNIS",
        "competition": "ATP",
        "market_type": "moneyline",
        "target_market": "match_moneyline",
        "period": "full_match",
        "line": None,
    }
    market_scope_mismatches = [
        key
        for key, expected in expected_market_scope.items()
        if market_snapshot.get(key) != expected
    ]
    if market_scope_mismatches:
        blocked.append("TENNIS_MARKET_SCOPE_MISMATCH")
        diagnostics.append(
            "tennis market scope mismatch: " + ", ".join(market_scope_mismatches)
        )

    players = context["players"]
    player_ids = {
        players["player_one"]["player_id"],
        players["player_two"]["player_id"],
    }
    context_names = {
        _normalize_identity(players["player_one"]["name"]),
        _normalize_identity(players["player_two"]["name"]),
    }
    market_names = {
        _normalize_identity(item.get("selection"))
        for item in market_snapshot.get("outcomes", [])
        if item.get("selection")
    }
    selected_name = _normalize_identity(market_snapshot.get("selection", ""))
    if len(player_ids) != 2 or len(context_names) != 2:
        blocked.append("TENNIS_PLAYER_IDENTITY_MISMATCH")
    elif context_names != market_names or selected_name not in context_names:
        blocked.append("TENNIS_PLAYER_IDENTITY_MISMATCH")
        diagnostics.append("market outcomes do not match the two context players")

    court = context["court"]
    if court["surface_status"] == "changed" or court["environment_status"] == "changed":
        blocked.append("TENNIS_COURT_CONDITION_CHANGED")
    else:
        if court["surface_status"] != "confirmed":
            watch.append("TENNIS_SURFACE_UNCONFIRMED")
        if court["environment_status"] != "confirmed":
            watch.append("TENNIS_ENVIRONMENT_UNCONFIRMED")

    event_status = context["event_status"]
    if event_status in {"in_progress", "completed"}:
        blocked.append("EVENT_ALREADY_STARTED")
    elif event_status != "scheduled":
        blocked.append("TENNIS_EVENT_NOT_ACTIONABLE")

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
        "status": status,
        "reason_codes": reasons,
        "diagnostics": diagnostics,
    }


def evaluate_tennis_settlement(
    actual_match_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify tennis settlement without changing the pre-bet context gate.

    Retirement and walkover records remain in the raw audit trail but are
    explicitly excluded from CLV and Brier aggregation for the initial model.
    """
    status = actual_match_result.get("match_status")
    if status not in {"completed", "retirement", "walkover"}:
        raise ValueError("tennis settlement match_status must be completed, retirement, or walkover")

    excluded = status in {"retirement", "walkover"}
    return {
        "settlement_status": "void_retirement" if excluded else "settled",
        "exclude_from_clv_aggregation": excluded,
        "exclude_from_brier_aggregation": excluded,
        "keep_in_raw_audit_log": True,
        "reason_codes": ["TENNIS_RETIREMENT_OR_WALKOVER"] if excluded else [],
        "diagnostics": [f"actual_match_status={status}"],
    }
