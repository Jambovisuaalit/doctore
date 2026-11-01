"""Fail-closed, research-only NHL total quote normalization and cross-book scanning.

This scanner intentionally does not create canonical executable market snapshots,
model probabilities, bet recommendations, or placement instructions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

_SCOPE = {"REGULATION_60", "REGULATION_OT", "REGULATION_OT_SO"}
_CAPTURE = {"provider_api", "instrumented_manual_capture"}
_REQUIRED = (
    "canonical_event_id", "event_identity_verified", "provider_event_id",
    "provider_quote_id", "book", "source_observed_at", "captured_at",
    "source_capture_method", "scheduled_start_at", "market_state",
    "quote_status", "sport", "competition", "market_type", "period",
    "line", "line_role", "over_odds", "under_odds", "settlement_scope",
    "settlement_rule_url", "settlement_rule_verified_at",
    "settlement_rule_verified", "commission_fraction",
)


class ScanNhlTotalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, Any]] = Field(..., min_length=1, max_length=2000)
    evaluated_at: str
    max_age_seconds: int = Field(default=300, gt=0, le=3600)


class ScanNhlTotalsOutput(BaseModel):
    schema_version: Literal["doctore.nhl-total-scan.v1"] = "doctore.nhl-total-scan.v1"
    execution_mode: Literal["SHADOW"] = "SHADOW"
    recommended_stake_eur: Literal[0] = 0
    input_count: int
    eligible_quote_count: int
    candidate_count: int
    candidates: list[dict[str, Any]]
    rejections: list[dict[str, Any]]
    pair_exclusions: list[dict[str, Any]]


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_NO_TIMEZONE")
    # Date-only, or date+zero-offset without a clock, must not imply a valid quote time.
    if "T" not in value and " " not in value:
        raise ValueError("TIMESTAMP_NO_CLOCK")
    return parsed.astimezone(timezone.utc)


def _price(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("ODDS_INVALID")
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ODDS_INVALID") from exc
    if not isfinite(price) or price <= 1.0:
        raise ValueError("ODDS_INVALID")
    return price


def _url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _verified_row(row: dict[str, Any], now: datetime, freshness: int) -> dict[str, Any]:
    missing = [name for name in _REQUIRED if name not in row or row[name] is None or row[name] == ""]
    if missing:
        raise ValueError("MISSING_FIELDS:" + ",".join(missing))
    if row["sport"] != "NHL" or row["competition"] != "NHL":
        raise ValueError("OUT_OF_SPORT_DOMAIN")
    if row["market_type"] != "total" or row["period"] != "full_game":
        raise ValueError("MARKET_DOMAIN_MISMATCH")
    if row["line_role"] not in {"main", "alternate"}:
        raise ValueError("LINE_ROLE_UNKNOWN")
    if row["market_state"] != "pregame" or row["quote_status"] != "open":
        raise ValueError("NOT_OPEN_PREGAME")
    if row["event_identity_verified"] is not True:
        raise ValueError("EVENT_ID_UNVERIFIED")
    event_id = row["canonical_event_id"]
    if not isinstance(event_id, str) or not event_id.startswith("nhl:") or not event_id[4:].isdigit():
        raise ValueError("CANONICAL_EVENT_ID_INVALID")
    for name in ("provider_event_id", "provider_quote_id", "book"):
        if not isinstance(row[name], str) or not row[name].strip():
            raise ValueError(name.upper() + "_INVALID")
    if row["source_capture_method"] not in _CAPTURE:
        raise ValueError("CAPTURE_PROVENANCE_UNVERIFIED")
    if row["settlement_scope"] not in _SCOPE:
        raise ValueError("SETTLEMENT_SCOPE_UNKNOWN")
    if row["settlement_rule_verified"] is not True or not _url(row["settlement_rule_url"]):
        raise ValueError("SETTLEMENT_RULE_UNVERIFIED")
    line = row["line"]
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not isfinite(line) or line <= 0:
        raise ValueError("LINE_INVALID")
    over, under = _price(row["over_odds"]), _price(row["under_odds"])
    commission = row["commission_fraction"]
    if isinstance(commission, bool) or not isinstance(commission, (int, float)) or not isfinite(commission) or not (0 <= commission < 1):
        raise ValueError("COMMISSION_UNVERIFIED")
    source_at = _utc(row["source_observed_at"])
    capture_at = _utc(row["captured_at"])
    start_at = _utc(row["scheduled_start_at"])
    verified_at = _utc(row["settlement_rule_verified_at"])
    if not (source_at <= capture_at <= now):
        raise ValueError("TIMESTAMP_ORDER_INVALID")
    if not (source_at < start_at and capture_at < start_at and now < start_at):
        raise ValueError("NOT_PREGAME_AT_EVALUATION")
    if (now - source_at).total_seconds() > freshness or (now - capture_at).total_seconds() > freshness:
        raise ValueError("SOURCE_QUOTE_STALE")
    if verified_at > now:
        raise ValueError("RULE_VERIFICATION_IN_FUTURE")
    return {
        "canonical_event_id": event_id, "scheduled_start_at": start_at.isoformat(),
        "book": row["book"].strip(), "provider_event_id": row["provider_event_id"],
        "provider_quote_id": row["provider_quote_id"],
        "source_observed_at": source_at.isoformat(),
        "captured_at": capture_at.isoformat(),
        "market_type": "total", "period": "full_game",
        "line": float(line), "line_role": row["line_role"],
        "settlement_scope": row["settlement_scope"],
        "settlement_rule_url": row["settlement_rule_url"],
        "over_odds": over, "under_odds": under,
        "commission_fraction": float(commission),
    }


def _effective_odds(odds: float, commission: float) -> float:
    # Conservative per-winning-leg fee proxy; market-netting may require a stricter rule.
    return 1.0 + (odds - 1.0) * (1.0 - commission)


def scan_nhl_totals(rows: list[dict[str, Any]], evaluated_at: str, max_age_seconds: int = 300) -> ScanNhlTotalsOutput:
    """Produce SHADOW candidates only when two independently sourced quotes match exactly."""
    now = _utc(evaluated_at)
    good: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            good.append(_verified_row(row, now, max_age_seconds))
        except (TypeError, ValueError) as exc:
            rejected.append({"row_index": index, "reason_code": str(exc)})
    # Never pool stale duplicate quotes with current quotes for one bookmaker/domain.
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in good:
        key = (row["canonical_event_id"], row["book"], row["line"],
               row["line_role"], row["settlement_scope"], row["period"])
        old = latest.get(key)
        if old is None or (row["source_observed_at"], row["captured_at"]) > (
                old["source_observed_at"], old["captured_at"]):
            latest[key] = row
    good = list(latest.values())

    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in good:
        by_event.setdefault(row["canonical_event_id"], []).append(row)
    matches: dict[tuple[Any, ...], dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    for event, quotes in by_event.items():
        for left in quotes:
            for right in quotes:
                if left["book"] == right["book"]:
                    continue
                if left["scheduled_start_at"] != right["scheduled_start_at"]:
                    reason = "EVENT_START_MISMATCH"
                elif left["settlement_scope"] != right["settlement_scope"]:
                    reason = "SETTLEMENT_MISMATCH"
                elif left["line"] != right["line"] or left["line_role"] != right["line_role"]:
                    reason = "ALTERNATE_LINE_MISMATCH"
                else:
                    reason = ""
                if reason:
                    exclusions.append({"event_id": event, "over_book": left["book"],
                                       "under_book": right["book"], "reason_code": reason})
                    continue
                net_over = _effective_odds(left["over_odds"], left["commission_fraction"])
                net_under = _effective_odds(right["under_odds"], right["commission_fraction"])
                implied_sum = 1 / net_over + 1 / net_under
                if implied_sum >= 1:
                    continue
                key = (event, left["scheduled_start_at"], left["line"],
                       left["line_role"], left["settlement_scope"])
                candidate = {
                    "event_id": event, "event_start_at": left["scheduled_start_at"],
                    "line": left["line"], "line_role": left["line_role"],
                    "settlement_scope": left["settlement_scope"],
                    "over": {"book": left["book"], "odds": left["over_odds"],
                             "source_observed_at": left["source_observed_at"],
                             "quote_id": left["provider_quote_id"],
                             "rule_source": left["settlement_rule_url"]},
                    "under": {"book": right["book"], "odds": right["under_odds"],
                              "source_observed_at": right["source_observed_at"],
                              "quote_id": right["provider_quote_id"],
                              "rule_source": right["settlement_rule_url"]},
                    "theoretical_net_margin_pct": round(100 * (1 / implied_sum - 1), 4),
                    "status": "SHADOW_CANDIDATE",
                    "execution_verified": False, "recommended_stake_eur": 0,
                    "reason_codes": ["EXECUTABLE_PRICES_NOT_VERIFIED", "MARKET_LIQUIDITY_NOT_VERIFIED"],
                }
                if key not in matches or candidate["theoretical_net_margin_pct"] > matches[key]["theoretical_net_margin_pct"]:
                    matches[key] = candidate
    candidates = sorted(matches.values(), key=lambda x: (-x["theoretical_net_margin_pct"], x["event_id"]))
    return ScanNhlTotalsOutput(
        input_count=len(rows), eligible_quote_count=len(good), candidate_count=len(candidates),
        candidates=candidates, rejections=rejected, pair_exclusions=exclusions,
    )
