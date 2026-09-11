"""Fail-closed adapter from selection-level odds records to Doctore market snapshots.

The adapter deliberately ignores generic placeholder domain fields from upstream
records. A record becomes a canonical ``doctore.market-snapshot.v1`` document only
when the sport, competition, market semantics, and settlement rule are explicitly
resolved by this module. Otherwise the result is ``DOMAIN_UNVERIFIED`` and no
canonical snapshot is emitted.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MARKET_SCHEMA_PATH = ROOT / "contracts" / "market-snapshot.schema.json"
MODEL_SCHEMA_PATH = ROOT / "contracts" / "model-output.schema.json"

MARKET_SCHEMA = Draft202012Validator(
    json.loads(MARKET_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
MODEL_SCHEMA = Draft202012Validator(
    json.loads(MODEL_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

CANONICAL_SPORTS = {"MLB", "KBO", "NPB", "TENNIS", "SOCCER", "NBA", "WNBA", "NFL"}
DIRECT_LEAGUE_SPORTS = {"MLB", "KBO", "NPB", "NBA", "WNBA", "NFL"}

# Explicit allow-list from the current source family. Unknown titles fail closed
# instead of being guessed to be soccer.
SOCCER_SOURCE_TITLES = {
    "Argentina",
    "Austrian Football Bundesliga",
    "Belgium First Div",
    "Brazil Série A",
    "Brazil Série B",
    "Championship",
    "Chile",
    "China",
    "Copa Libertadores",
    "Copa Sudamericana",
    "Denmark Superliga",
    "Dutch Eredivisie",
    "EFL Cup",
    "EPL",
    "Finland",
    "France",
    "Frauen-Bundesliga",
    "Germany",
    "Greece",
    "Italy",
    "J League",
    "K League 1",
    "League 1",
    "League 2",
    "League of Ireland",
    "Liga MX",
    "MLS",
    "Norway",
    "Poland",
    "Portugal",
    "Russia",
    "Saudi Pro League",
    "Scotland",
    "Spain",
    "Sweden",
    "Swiss Superleague",
    "Turkey Super League",
    "UEFA Champions League",
    "UEFA Europa Conference League",
    "UEFA Europa League",
    "UEFA Nations League",
}

PLACEHOLDER_VALUES = {
    "generic",
    "generic_h2h",
    "generic_spreads",
    "generic_totals",
    "moneyline_or_equivalent",
    "spreads",
    "totals",
    "full_time",
    "standard_rule_v1",
}

DOMAIN_FIELDS = (
    "sport",
    "competition",
    "market_type",
    "target_market",
    "period",
    "line",
    "settlement_rules",
)
JOIN_FIELDS = (
    "event_id",
    "market_id",
    "sport",
    "competition",
    "market_type",
    "target_market",
    "period",
    "line",
    "settlement_rules",
    "selection",
)


def _schema_errors(validator: Draft202012Validator, payload: Mapping[str, Any]) -> list[str]:
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in errors
    ]


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return result or "unknown"


def _line_token(line: Any) -> str:
    if line is None:
        return "pk"
    return str(float(line)).replace("-", "m").replace(".", "p")


def _canonical_market_id(
    *, event_id: str, market_type: str, selection: str, line: float | None,
) -> str:
    """Create a book-independent, selection-specific canonical market identity."""
    return "-".join([
        event_id,
        market_type,
        _slug(selection),
        _line_token(line),
    ])


def _normalize_sport_competition(record: Mapping[str, Any]) -> tuple[str, str]:
    raw_sport = str(record.get("sport") or "").strip()
    raw_competition = str(record.get("competition") or "").strip()
    competition_is_generic = not raw_competition or raw_competition.casefold() == "generic"

    if raw_sport in DIRECT_LEAGUE_SPORTS:
        return raw_sport, raw_sport if competition_is_generic else raw_competition
    if raw_sport in {"TENNIS", "SOCCER"}:
        if competition_is_generic:
            raise ValueError("COMPETITION_UNVERIFIED")
        return raw_sport, raw_competition
    if raw_sport.startswith(("ATP ", "WTA ", "ITF ")):
        return "TENNIS", raw_sport if competition_is_generic else raw_competition
    if raw_sport in SOCCER_SOURCE_TITLES:
        return "SOCCER", raw_sport if competition_is_generic else raw_competition
    raise ValueError("SPORT_UNVERIFIED")


def _parse_outcomes(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("outcomes_vector_json")
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("OUTCOMES_JSON_INVALID") from exc
    elif isinstance(raw, list):
        values = raw
    else:
        raise ValueError("OUTCOMES_MISSING")
    if not isinstance(values, list) or len(values) not in {2, 3}:
        raise ValueError("OUTCOME_CARDINALITY_INVALID")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            raise ValueError("OUTCOME_INVALID")
        name = str(item.get("name") or "").strip()
        if not name or name.casefold() in seen:
            raise ValueError("OUTCOME_NAME_INVALID")
        seen.add(name.casefold())
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or float(price) <= 1:
            raise ValueError("OUTCOME_PRICE_INVALID")
        output = {"name": name, "price": float(price)}
        if "point" in item and item.get("point") is not None:
            point = item.get("point")
            if isinstance(point, bool) or not isinstance(point, (int, float)):
                raise ValueError("OUTCOME_POINT_INVALID")
            output["point"] = float(point)
        normalized.append(output)
    return normalized


def _validate_raw_selection(record: Mapping[str, Any], outcomes: list[dict[str, Any]]) -> None:
    event_id = str(record.get("event_id") or "").strip()
    source_event_id = str(record.get("source_event_id") or "").strip()
    source = str(record.get("source") or "").strip()
    book = str(record.get("bookmaker") or "").strip()
    market_key = str(record.get("market_key") or "").strip()
    selection = str(record.get("selection_name") or "").strip()
    status = str(record.get("market_status") or "").strip()
    if not all((event_id, source_event_id, source, book, market_key, selection)):
        raise ValueError("REQUIRED_IDENTITY_MISSING")
    if status not in {"open", "suspended", "closed"}:
        raise ValueError("MARKET_STATUS_INVALID")

    price = record.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or float(price) <= 1:
        raise ValueError("SELECTED_PRICE_INVALID")

    captured = _parse_time(record.get("captured_at"))
    start = _parse_time(record.get("event_start_at"))
    if captured >= start:
        raise ValueError("QUOTE_NOT_PREGAME")

    selected = [item for item in outcomes if item["name"].casefold() == selection.casefold()]
    if len(selected) != 1:
        raise ValueError("SELECTION_NOT_IN_OUTCOMES")
    if abs(selected[0]["price"] - float(price)) > 1e-12:
        raise ValueError("SELECTED_PRICE_MISMATCH")

    point = record.get("point")
    if point is not None:
        if isinstance(point, bool) or not isinstance(point, (int, float)):
            raise ValueError("SELECTED_POINT_INVALID")
        if "point" not in selected[0] or abs(selected[0]["point"] - float(point)) > 1e-12:
            raise ValueError("SELECTED_POINT_MISMATCH")


def _baseball_domain(
    sport: str, market_key: str, line: float | None,
) -> dict[str, Any] | None:
    if sport not in {"MLB", "KBO", "NPB"}:
        return None
    if market_key == "h2h":
        if line is not None:
            return None
        return {
            "market_type": "moneyline",
            "target_market": "full_game_moneyline",
            "period": "full_game",
            "line": None,
            "settlement_rules": "action_including_extra_innings",
        }
    if market_key == "spreads":
        if line is None:
            return None
        return {
            "market_type": "run_line",
            "target_market": "full_game_run_line",
            "period": "full_game",
            "line": line,
            "settlement_rules": "full_game_including_extra_innings",
        }
    if market_key == "totals":
        if line is None:
            return None
        return {
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "line": line,
            "settlement_rules": "full_game_including_extra_innings",
        }
    return None


def _basketball_domain(
    sport: str, market_key: str, line: float | None,
) -> dict[str, Any] | None:
    if sport not in {"NBA", "WNBA"}:
        return None
    if market_key == "h2h" and line is None:
        market_type, target = "moneyline", "full_game_moneyline"
    elif market_key == "spreads" and line is not None:
        market_type, target = "spread", "full_game_spread"
    elif market_key == "totals" and line is not None:
        market_type, target = "total", "full_game_total"
    else:
        return None
    return {
        "market_type": market_type,
        "target_market": target,
        "period": "full_game",
        "line": line,
        "settlement_rules": "full_game_including_overtime",
    }


def _unverified_domain_candidate(
    sport: str, market_key: str, line: float | None, outcomes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Return useful normalized diagnostics without promoting them to canonical."""
    if sport == "SOCCER":
        if market_key == "h2h" and len(outcomes) == 3 and any(
            item["name"].casefold() == "draw" for item in outcomes
        ):
            return {
                "market_type": "1x2",
                "target_market": "full_time_1x2",
                "period": "regulation_time",
                "line": None,
                "settlement_rules": None,
            }, "SOCCER_SETTLEMENT_RULE_UNVERIFIED"
        if market_key == "spreads":
            return {
                "market_type": "spread",
                "target_market": "full_time_spread",
                "period": "regulation_time",
                "line": line,
                "settlement_rules": None,
            }, "SOCCER_SETTLEMENT_RULE_UNVERIFIED"
        if market_key == "totals":
            return {
                "market_type": "total",
                "target_market": "full_time_total",
                "period": "regulation_time",
                "line": line,
                "settlement_rules": None,
            }, "SOCCER_SETTLEMENT_RULE_UNVERIFIED"
    if sport == "TENNIS":
        if market_key == "h2h":
            market_type, target, candidate_line = "match_moneyline", "full_match_moneyline", None
        elif market_key == "spreads":
            market_type, target, candidate_line = "game_spread", "full_match_game_spread", line
        elif market_key == "totals":
            market_type, target, candidate_line = "game_total", "full_match_game_total", line
        else:
            return None, "TENNIS_DOMAIN_UNVERIFIED"
        return {
            "market_type": market_type,
            "target_market": target,
            "period": "full_match",
            "line": candidate_line,
            "settlement_rules": None,
        }, "TENNIS_RETIREMENT_SETTLEMENT_UNVERIFIED"
    return None, "DOMAIN_UNVERIFIED"


def _canonical_outcomes(
    outcomes: list[dict[str, Any]], *, market_type: str,
) -> list[dict[str, Any]]:
    result = []
    for item in outcomes:
        selection = item["name"]
        if market_type == "total":
            selection = selection.casefold()
        result.append({"selection": selection, "decimal_odds": item["price"]})
    return result


def adapt_selection_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt one source selection record to a canonical market snapshot.

    Returns a wrapper with ``status``. Only ``status == 'CANONICAL'`` contains a
    non-null ``market_snapshot``. Placeholder domain fields in ``record`` are
    never copied into the canonical document.
    """
    source_identity = {
        "selection_id": record.get("selection_id"),
        "source_event_id": record.get("source_event_id"),
        "source_market_group_id": record.get("book_market_id"),
        "source_record_market_id": record.get("market_id"),
    }
    try:
        outcomes = _parse_outcomes(record)
        _validate_raw_selection(record, outcomes)
        sport, competition = _normalize_sport_competition(record)
    except (TypeError, ValueError) as exc:
        return {
            "status": "INVALID_INPUT",
            "reason_codes": [str(exc)],
            "normalized": None,
            "domain": None,
            "market_snapshot": None,
            "source_identity": source_identity,
        }

    market_key = str(record.get("market_key") or "").strip()
    raw_point = record.get("point")
    line = None if raw_point is None else float(raw_point)
    domain = _baseball_domain(sport, market_key, line) or _basketball_domain(sport, market_key, line)

    normalized = {"sport": sport, "competition": competition}
    if domain is None:
        candidate, reason = _unverified_domain_candidate(sport, market_key, line, outcomes)
        return {
            "status": "DOMAIN_UNVERIFIED",
            "reason_codes": [reason],
            "normalized": normalized,
            "domain": candidate,
            "market_snapshot": None,
            "source_identity": source_identity,
        }

    raw_selection = str(record["selection_name"]).strip()
    selection = raw_selection.casefold() if domain["market_type"] == "total" else raw_selection
    canonical_outcomes = _canonical_outcomes(outcomes, market_type=domain["market_type"])

    snapshot = {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": str(record["event_id"]),
        "market_id": _canonical_market_id(
            event_id=str(record["event_id"]),
            market_type=domain["market_type"],
            selection=selection,
            line=domain["line"],
        ),
        "book": str(record["bookmaker"]),
        "captured_at": str(record["captured_at"]),
        "event_start_at": str(record["event_start_at"]),
        "sport": sport,
        "competition": competition,
        "market_type": domain["market_type"],
        "target_market": domain["target_market"],
        "period": domain["period"],
        "line": domain["line"],
        "settlement_rules": domain["settlement_rules"],
        "selection": selection,
        "decimal_odds": float(record["price"]),
        "market_status": str(record["market_status"]),
        "is_complete": True,
        "outcomes": canonical_outcomes,
        "correlation_group": str(record["event_id"]),
        "source": str(record["source"]),
    }

    errors = _schema_errors(MARKET_SCHEMA, snapshot)
    if errors:
        return {
            "status": "INVALID_INPUT",
            "reason_codes": ["CANONICAL_SCHEMA_INVALID"],
            "diagnostics": errors,
            "normalized": normalized,
            "domain": {**normalized, **domain},
            "market_snapshot": None,
            "source_identity": source_identity,
        }

    return {
        "status": "CANONICAL",
        "reason_codes": [],
        "normalized": normalized,
        "domain": {**normalized, **domain},
        "market_snapshot": snapshot,
        "source_identity": source_identity,
    }


def adapt_selection_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [adapt_selection_record(record) for record in records]


def _exact_mismatches(model: Mapping[str, Any], market: Mapping[str, Any]) -> list[str]:
    mismatches = [key for key in JOIN_FIELDS if model.get(key) != market.get(key)]
    validation_domain = model.get("validation_domain")
    if isinstance(validation_domain, Mapping):
        for key in DOMAIN_FIELDS:
            if validation_domain.get(key) != market.get(key):
                mismatches.append(f"validation_domain.{key}")
    else:
        mismatches.append("validation_domain")
    return list(dict.fromkeys(mismatches))


def exact_model_output_join(
    market_snapshot: Mapping[str, Any],
    model_outputs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join a canonical market snapshot to exactly one model output.

    Book and price are intentionally excluded from the model-domain identity.
    Every event/market/domain/selection field must match exactly, including the
    model's ``validation_domain``. Ambiguous or invalid candidates fail closed.
    """
    market_errors = _schema_errors(MARKET_SCHEMA, market_snapshot)
    if market_errors:
        return {
            "status": "MARKET_SNAPSHOT_INVALID",
            "reason_codes": ["MARKET_SNAPSHOT_INVALID"],
            "diagnostics": market_errors,
            "market_snapshot": None,
            "model_output": None,
        }

    valid_models: list[Mapping[str, Any]] = []
    invalid_model_diagnostics: list[str] = []
    for index, model in enumerate(model_outputs):
        errors = _schema_errors(MODEL_SCHEMA, model)
        if errors:
            invalid_model_diagnostics.extend(f"model[{index}].{error}" for error in errors)
            continue
        valid_models.append(model)

    exact = [model for model in valid_models if not _exact_mismatches(model, market_snapshot)]
    if len(exact) == 1:
        return {
            "status": "MATCHED",
            "reason_codes": [],
            "diagnostics": [],
            "market_snapshot": dict(market_snapshot),
            "model_output": dict(exact[0]),
        }
    if len(exact) > 1:
        return {
            "status": "MODEL_OUTPUT_AMBIGUOUS",
            "reason_codes": ["MODEL_OUTPUT_AMBIGUOUS"],
            "diagnostics": [f"{len(exact)} exact model outputs matched"],
            "market_snapshot": dict(market_snapshot),
            "model_output": None,
        }

    related = [
        model for model in valid_models
        if model.get("event_id") == market_snapshot.get("event_id")
        and model.get("selection") == market_snapshot.get("selection")
    ]
    diagnostics = invalid_model_diagnostics
    reason = "MODEL_OUTPUT_NOT_FOUND"
    if related:
        reason = "MODEL_DOMAIN_MISMATCH"
        for index, model in enumerate(related):
            diagnostics.append(
                f"related_model[{index}] mismatches: {', '.join(_exact_mismatches(model, market_snapshot))}"
            )
    return {
        "status": reason,
        "reason_codes": [reason],
        "diagnostics": diagnostics,
        "market_snapshot": dict(market_snapshot),
        "model_output": None,
    }


def adapt_and_join_selection_record(
    record: Mapping[str, Any],
    model_outputs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    adapted = adapt_selection_record(record)
    if adapted["status"] != "CANONICAL":
        return {
            "status": adapted["status"],
            "reason_codes": adapted["reason_codes"],
            "diagnostics": adapted.get("diagnostics", []),
            "adapter_result": adapted,
            "market_snapshot": None,
            "model_output": None,
        }
    joined = exact_model_output_join(adapted["market_snapshot"], model_outputs)
    joined["adapter_result"] = adapted
    return joined
