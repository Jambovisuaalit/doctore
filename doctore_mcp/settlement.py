"""Closing-line validation, CLV computation and settlement persistence."""
from __future__ import annotations

from typing import Any, Mapping
import json
import os

from .runtime import CLOSING_SNAPSHOT_PATH, content_sha256, now_iso, parse_time
from market_probability import calculate_market_probabilities
from tennis_context import evaluate_tennis_settlement
from .ledger import line_from_csv, log_lock, read_bet_rows, write_bet_rows
from .schemas import SettleBetInput, SettleBetOutput, SettlementResult, schema_errors


def closing_records() -> list[dict[str, Any]]:
    if not CLOSING_SNAPSHOT_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    with CLOSING_SNAPSHOT_PATH.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid closing snapshot JSONL at line {line_number}: {exc}") from exc
    return records


def append_closing_record(record: dict[str, Any]) -> bool:
    existing = [item for item in closing_records() if item.get("decision_id") == record["decision_id"]]
    if existing:
        same = (
            len(existing) == 1
            and existing[0].get("closing_snapshot_sha256") == record["closing_snapshot_sha256"]
            and existing[0].get("result") == record["result"]
            and existing[0].get("settlement_status", "settled") == record["settlement_status"]
        )
        if same:
            return False
        raise ValueError(f"conflicting closing snapshot already exists for {record['decision_id']}")
    CLOSING_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CLOSING_SNAPSHOT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def profit_loss(result: SettlementResult, stake: float, odds: float) -> float:
    if result == SettlementResult.WIN:
        return stake * (odds - 1)
    if result == SettlementResult.LOSS:
        return -stake
    if result in {SettlementResult.PUSH, SettlementResult.VOID}:
        return 0.0
    if result == SettlementResult.HALF_WIN:
        return stake * 0.5 * (odds - 1)
    return -stake * 0.5


def settlement_domain_mismatches(row: Mapping[str, str], snapshot: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("event_id", "market_id", "sport", "competition", "selection", "book"):
        expected = row.get(key, "")
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    for key in ("market_type", "target_market", "period", "settlement_rules"):
        expected = row.get(key, "")
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    if row.get("line_json") and snapshot.get("line") != line_from_csv(row["line_json"]):
        mismatches.append("line")
    return mismatches


def _optional_float(value: Any) -> float | None:
    return float(value) if value not in {None, ""} else None


def _settlement_policy(row: Mapping[str, str], params: SettleBetInput) -> dict[str, Any]:
    if row.get("sport") == "TENNIS":
        if params.tennis_settlement_context is None:
            raise ValueError("tennis_settlement_context with actual match_status is required")
        policy = evaluate_tennis_settlement(params.tennis_settlement_context)
        if policy["settlement_status"] == "void_retirement" and params.result != SettlementResult.VOID:
            raise ValueError("tennis retirement or walkover settlement must use result=void")
        return policy
    if params.tennis_settlement_context is not None:
        raise ValueError("tennis_settlement_context is only valid for TENNIS settlements")
    return {
        "settlement_status": "settled",
        "exclude_from_clv_aggregation": False,
        "exclude_from_brier_aggregation": False,
        "keep_in_raw_audit_log": True,
        "reason_codes": [],
        "diagnostics": [],
    }


def settle_bet(params: SettleBetInput) -> SettleBetOutput:
    snapshot = params.closing_market_snapshot
    errors = schema_errors("market", snapshot)
    if errors:
        raise ValueError("invalid closing market snapshot: " + "; ".join(errors))
    if parse_time(snapshot["captured_at"]) > parse_time(snapshot["event_start_at"]):
        raise ValueError("closing snapshot was captured after event start")
    market_probabilities = calculate_market_probabilities(snapshot)
    closing_fair = market_probabilities["no_vig_probability"]
    closing_odds = float(snapshot["decimal_odds"])
    snapshot_hash = content_sha256(snapshot)
    settled_at = params.settled_at or now_iso()
    if parse_time(settled_at) < parse_time(snapshot["event_start_at"]):
        raise ValueError("settled_at cannot be before event start")

    with log_lock():
        rows = read_bet_rows()
        indexes = [index for index, row in enumerate(rows) if row["decision_id"] == params.decision_id]
        if len(indexes) != 1:
            raise ValueError(f"expected exactly one logged row for {params.decision_id}; found {len(indexes)}")
        index = indexes[0]
        row = rows[index]
        mismatches = settlement_domain_mismatches(row, snapshot)
        if mismatches:
            raise ValueError("closing snapshot domain mismatch: " + ", ".join(mismatches))

        policy = _settlement_policy(row, params)

        if row.get("result"):
            record = next(
                (item for item in closing_records() if item.get("decision_id") == params.decision_id),
                None,
            )
            settlement_status = "settled" if record is None else record.get("settlement_status", "settled")
            same = (
                row["result"] == params.result.value
                and row["closing_snapshot_sha256"] == snapshot_hash
                and settlement_status == policy["settlement_status"]
            )
            if not same:
                raise ValueError("bet is already settled with different closing data")
            return SettleBetOutput(
                settled=True,
                idempotent_replay=True,
                decision_id=params.decision_id,
                settlement_status=settlement_status,
                exclude_from_clv_aggregation=policy["exclude_from_clv_aggregation"],
                exclude_from_brier_aggregation=policy["exclude_from_brier_aggregation"],
                closing_odds=float(row["closing_odds"]),
                closing_no_vig_probability=float(row["closing_no_vig_probability"]),
                price_clv_pct=_optional_float(row["price_clv_pct"]),
                clv_probability_points=_optional_float(row["clv_probability_points"]),
                profit_loss=float(row["profit_loss"]),
                closing_snapshot_sha256=snapshot_hash,
                closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
            )

        odds_taken = float(row["odds_taken"])
        no_vig_at_bet = float(row["market_no_vig_at_bet"])
        approved_stake = float(row["approved_stake"])
        raw_price_clv = odds_taken / closing_odds - 1
        raw_probability_clv = closing_fair - no_vig_at_bet
        excluded = policy["exclude_from_clv_aggregation"]
        price_clv = None if excluded else raw_price_clv
        probability_clv = None if excluded else raw_probability_clv
        pnl = profit_loss(params.result, approved_stake, odds_taken)
        closing_record = {
            "schema_version": "doctore.closing-snapshot.v1",
            "decision_id": params.decision_id,
            "recorded_at": settled_at,
            "result": params.result.value,
            "settlement_status": policy["settlement_status"],
            "exclude_from_clv_aggregation": policy["exclude_from_clv_aggregation"],
            "exclude_from_brier_aggregation": policy["exclude_from_brier_aggregation"],
            "keep_in_raw_audit_log": policy["keep_in_raw_audit_log"],
            "settlement_reason_codes": policy["reason_codes"],
            "settlement_diagnostics": policy["diagnostics"],
            "tennis_settlement_context": params.tennis_settlement_context,
            "closing_snapshot_sha256": snapshot_hash,
            "closing_no_vig_probability": closing_fair,
            "raw_price_clv_pct": raw_price_clv,
            "raw_clv_probability_points": raw_probability_clv,
            "price_clv_pct": price_clv,
            "clv_probability_points": probability_clv,
            "market_snapshot": snapshot,
        }
        appended = append_closing_record(closing_record)
        row.update({
            "closing_odds": closing_odds,
            "closing_no_vig_probability": closing_fair,
            "price_clv_pct": "" if price_clv is None else price_clv,
            "clv_probability_points": "" if probability_clv is None else probability_clv,
            "result": params.result.value,
            "profit_loss": pnl,
            "closing_snapshot_sha256": snapshot_hash,
            "settled_at": settled_at,
        })
        rows[index] = row
        write_bet_rows(rows)

    return SettleBetOutput(
        settled=True,
        idempotent_replay=not appended,
        decision_id=params.decision_id,
        settlement_status=policy["settlement_status"],
        exclude_from_clv_aggregation=policy["exclude_from_clv_aggregation"],
        exclude_from_brier_aggregation=policy["exclude_from_brier_aggregation"],
        closing_odds=closing_odds,
        closing_no_vig_probability=round(closing_fair, 12),
        price_clv_pct=None if price_clv is None else round(price_clv, 12),
        clv_probability_points=None if probability_clv is None else round(probability_clv, 12),
        profit_loss=round(pnl, 2),
        closing_snapshot_sha256=snapshot_hash,
        closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
    )
