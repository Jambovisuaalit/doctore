"""Fail-closed adapter from selection-level odds records to Doctore market snapshots.

Upstream placeholder market semantics are never promoted to canonical truth. A
record becomes ``doctore.market-snapshot.v1`` only when identity, timestamps,
payoff structure and exact settlement policy are proven. Otherwise the adapter
returns an explicit blocked status and emits no canonical snapshot.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MARKET_SCHEMA_PATH = ROOT / "contracts" / "market-snapshot.schema.json"
MODEL_SCHEMA_PATH = ROOT / "contracts" / "model-output.schema.json"
SETTLEMENT_REGISTRY_PATH = ROOT / "governance" / "settlement-rule-registry.json"

MARKET_SCHEMA = Draft202012Validator(
    json.loads(MARKET_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
MODEL_SCHEMA = Draft202012Validator(
    json.loads(MODEL_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

DIRECT_LEAGUE_SPORTS = {"MLB", "KBO", "NPB", "NBA", "WNBA", "NFL"}
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


def _load_settlement_registry() -> tuple[dict[tuple[str, str, str], dict[str, Any]], str]:
    payload = json.loads(SETTLEMENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "doctore.settlement-rule-registry.v1":
        raise RuntimeError("SETTLEMENT_REGISTRY_SCHEMA_INVALID")
    verified_at = str(payload.get("verified_at") or "").strip()
    rules = payload.get("rules")
    if not verified_at or not isinstance(rules, list):
        raise RuntimeError("SETTLEMENT_REGISTRY_INVALID")

    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise RuntimeError("SETTLEMENT_REGISTRY_RULE_INVALID")
        if rule.get("status") != "VERIFIED":
            continue
        sport = str(rule.get("sport") or "").strip()
        book = str(rule.get("book") or "").strip()
        period = str(rule.get("period") or "").strip()
        settlement = str(rule.get("settlement_rules") or "").strip()
        rule_id = str(rule.get("rule_id") or "").strip()
        evidence_url = str(rule.get("evidence_url") or "").strip()
        evidence_checked_at = str(rule.get("evidence_checked_at") or "").strip()
        market_keys = rule.get("market_keys")
        if not all((sport, book, period, settlement, rule_id, evidence_url, evidence_checked_at)):
            raise RuntimeError("SETTLEMENT_REGISTRY_RULE_INVALID")
        if not isinstance(market_keys, list) or not market_keys:
            raise RuntimeError("SETTLEMENT_REGISTRY_RULE_INVALID")
        for market_key in market_keys:
            key = (sport, book, str(market_key))
            if key in index:
                raise RuntimeError("SETTLEMENT_REGISTRY_DUPLICATE_RULE")
            index[key] = dict(rule)
    return index, verified_at


SETTLEMENT_RULE_INDEX, SETTLEMENT_REGISTRY_VERIFIED_AT = _load_settlement_registry()


def _settlement_rule(sport: str, book: str, market_key: str) -> dict[str, Any] | None:
    return SETTLEMENT_RULE_INDEX.get((sport, book, market_key))


def _settlement_evidence(rule: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "rule_id": rule["rule_id"],
        "evidence_url": rule["evidence_url"],
        "evidence_checked_at": rule["evidence_checked_at"],
        "registry_verified_at": SETTLEMENT_REGISTRY_VERIFIED_AT,
    }


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


def _baseball_domain(sport: str, market_key: str, line: float | None) -> dict[str, Any] | None:
    if sport not in {"MLB", "KBO", "NPB"}:
        return None
    if market_key == "h2h" and line is None:
        return {
            "market_type": "moneyline",
            "target_market": "full_game_moneyline",
            "period": "full_game",
            "line": None,
            "settlement_rules": "action_including_extra_innings",
        }
    if market_key == "spreads" and line is not None:
        return {
            "market_type": "run_line",
            "target_market": "full_game_run_line",
            "period": "full_game",
            "line": line,
            "settlement_rules": "full_game_including_extra_innings",
        }
    if market_key == "totals" and line is not None:
        return {
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "line": line,
            "settlement_rules": "full_game_including_extra_innings",
        }
    return None


def _basketball_domain(sport: str, market_key: str, line: float | None) -> dict[str, Any] | None:
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


def _line_class(line: float | None) -> str:
    if line is None:
        return "missing"
    quarter_units = round(line * 4)
    if not math.isclose(line * 4, quarter_units, abs_tol=1e-9):
        return "other"
    modulo = abs(quarter_units) % 4
    if modulo == 0:
        return "integer"
    if modulo == 2:
        return "half"
    return "quarter"


def _total_structure_valid(outcomes: list[dict[str, Any]], line: float) -> bool:
    if len(outcomes) != 2:
        return False
    names = {item["name"].casefold() for item in outcomes}
    if names != {"over", "under"}:
        return False
    return all(
        "point" in item and math.isclose(float(item["point"]), line, abs_tol=1e-9)
        for item in outcomes
    )


def _blocked_domain(
    *, market_type: str, target_market: str, period: str, line: float | None,
) -> dict[str, Any]:
    return {
        "market_type": market_type,
        "target_market": target_market,
        "period": period,
        "line": line,
        "settlement_rules": None,
    }


def _soccer_domain(
    *, book: str, market_key: str, line: float | None, outcomes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    if market_key == "spreads":
        line_type = _line_class(line)
        candidate = _blocked_domain(
            market_type="asian_handicap" if line_type in {"quarter", "integer"} else "spread",
            target_market="full_time_handicap",
            period="regulation_time",
            line=line,
        )
        if line_type == "quarter":
            return None, "ASIAN_QUARTER_LINE_UNSUPPORTED", candidate
        if line_type == "integer":
            return None, "PUSH_SETTLEMENT_UNSUPPORTED", candidate
        return None, "SOCCER_HANDICAP_SETTLEMENT_UNVERIFIED", candidate

    rule = _settlement_rule("SOCCER", book, market_key)
    if market_key == "h2h":
        candidate = _blocked_domain(
            market_type="1x2", target_market="full_time_1x2",
            period="regulation_time", line=None,
        )
        if line is not None or len(outcomes) != 3 or not any(
            item["name"].casefold() == "draw" for item in outcomes
        ):
            return None, "SOCCER_1X2_STRUCTURE_INVALID", candidate
        if rule is None:
            return None, "BOOK_SETTLEMENT_RULE_UNVERIFIED", candidate
        return {
            "market_type": "1x2",
            "target_market": "full_time_1x2",
            "period": rule["period"],
            "line": None,
            "settlement_rules": rule["settlement_rules"],
        }, None, rule

    if market_key == "totals":
        candidate = _blocked_domain(
            market_type="total", target_market="full_time_total",
            period="regulation_time", line=line,
        )
        line_type = _line_class(line)
        if line_type == "quarter":
            return None, "ASIAN_QUARTER_LINE_UNSUPPORTED", candidate
        if line_type == "integer":
            return None, "PUSH_SETTLEMENT_UNSUPPORTED", candidate
        if line_type != "half" or line is None:
            return None, "LINE_SETTLEMENT_UNSUPPORTED", candidate
        if not _total_structure_valid(outcomes, line):
            return None, "SOCCER_TOTAL_STRUCTURE_INVALID", candidate
        if rule is None:
            return None, "BOOK_SETTLEMENT_RULE_UNVERIFIED", candidate
        return {
            "market_type": "total",
            "target_market": "full_time_total",
            "period": rule["period"],
            "line": line,
            "settlement_rules": rule["settlement_rules"],
        }, None, rule

    return None, "SOCCER_DOMAIN_UNVERIFIED", None


def _tennis_domain(
    *, book: str, market_key: str, line: float | None, outcomes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    if market_key != "h2h":
        market_type = "game_spread" if market_key == "spreads" else "game_total"
        target = "full_match_game_spread" if market_key == "spreads" else "full_match_game_total"
        return None, "TENNIS_NON_MONEYLINE_SETTLEMENT_UNVERIFIED", _blocked_domain(
            market_type=market_type, target_market=target, period="full_match", line=line,
        )
    candidate = _blocked_domain(
        market_type="match_moneyline", target_market="full_match_moneyline",
        period="full_match", line=None,
    )
    if line is not None or len(outcomes) != 2:
        return None, "TENNIS_MATCH_MONEYLINE_STRUCTURE_INVALID", candidate
    rule = _settlement_rule("TENNIS", book, market_key)
    if rule is None:
        return None, "BOOK_SETTLEMENT_RULE_UNVERIFIED", candidate
    return {
        "market_type": "match_moneyline",
        "target_market": "full_match_moneyline",
        "period": rule["period"],
        "line": None,
        "settlement_rules": rule["settlement_rules"],
    }, None, rule


def _canonical_outcomes(outcomes: list[dict[str, Any]], *, market_type: str) -> list[dict[str, Any]]:
    result = []
    for item in outcomes:
        selection = item["name"]
        if market_type == "total":
            selection = selection.casefold()
        result.append({"selection": selection, "decimal_odds": item["price"]})
    return result


def _adapter_wrapper(
    *, status: str, reason_codes: list[str], normalized: Mapping[str, Any] | None,
    domain: Mapping[str, Any] | None, market_snapshot: Mapping[str, Any] | None,
    source_identity: Mapping[str, Any], settlement_evidence: Mapping[str, Any] | None = None,
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "reason_codes": reason_codes,
        "normalized": dict(normalized) if normalized is not None else None,
        "domain": dict(domain) if domain is not None else None,
        "market_snapshot": dict(market_snapshot) if market_snapshot is not None else None,
        "source_identity": dict(source_identity),
        "settlement_evidence": dict(settlement_evidence) if settlement_evidence is not None else None,
    }
    if diagnostics is not None:
        result["diagnostics"] = diagnostics
    return result


def adapt_selection_record(record: Mapping[str, Any]) -> dict[str, Any]:
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
        return _adapter_wrapper(
            status="INVALID_INPUT", reason_codes=[str(exc)], normalized=None,
            domain=None, market_snapshot=None, source_identity=source_identity,
        )

    market_key = str(record.get("market_key") or "").strip()
    book = str(record.get("bookmaker") or "").strip()
    raw_point = record.get("point")
    line = None if raw_point is None else float(raw_point)
    normalized = {"sport": sport, "competition": competition}

    domain = _baseball_domain(sport, market_key, line) or _basketball_domain(sport, market_key, line)
    reason: str | None = None
    rule: Mapping[str, Any] | None = None
    candidate: Mapping[str, Any] | None = None

    if domain is None and sport == "SOCCER":
        domain, reason, aux = _soccer_domain(
            book=book, market_key=market_key, line=line, outcomes=outcomes,
        )
        if domain is None:
            candidate = aux
        else:
            rule = aux
    elif domain is None and sport == "TENNIS":
        domain, reason, aux = _tennis_domain(
            book=book, market_key=market_key, line=line, outcomes=outcomes,
        )
        if domain is None:
            candidate = aux
        else:
            rule = aux

    if domain is None:
        return _adapter_wrapper(
            status="DOMAIN_UNVERIFIED",
            reason_codes=[reason or "DOMAIN_UNVERIFIED"],
            normalized=normalized,
            domain=candidate,
            market_snapshot=None,
            source_identity=source_identity,
        )

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
        "book": book,
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
        return _adapter_wrapper(
            status="INVALID_INPUT", reason_codes=["CANONICAL_SCHEMA_INVALID"],
            diagnostics=errors, normalized=normalized,
            domain={**normalized, **domain}, market_snapshot=None,
            source_identity=source_identity, settlement_evidence=_settlement_evidence(rule),
        )

    return _adapter_wrapper(
        status="CANONICAL", reason_codes=[], normalized=normalized,
        domain={**normalized, **domain}, market_snapshot=snapshot,
        source_identity=source_identity, settlement_evidence=_settlement_evidence(rule),
    )


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
    """Join a canonical market snapshot to exactly one exact-domain model output."""
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
