"""Closing-line validation, CLV computation and settlement persistence."""
from __future__ import annotations

from typing import Any, Mapping
import json
import os

from market_probability import calculate_market_probabilities

from .ledger import line_from_csv, log_lock, read_bet_rows, write_bet_rows
from .runtime import CLOSING_SNAPSHOT_PATH, content_sha256, now_iso, parse_time
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

        if row.get("result"):
            same = row["result"] == params.result.value and row["closing_snapshot_sha256"] == snapshot_hash
            if not same:
                raise ValueError("bet is already settled with different closing data")
            return SettleBetOutput(
                settled=True, idempotent_replay=True, decision_id=params.decision_id,
                closing_odds=float(row["closing_odds"]),
                closing_no_vig_probability=float(row["closing_no_vig_probability"]),
                price_clv_pct=float(row["price_clv_pct"]),
                clv_probability_points=float(row["clv_probability_points"]),
                profit_loss=float(row["profit_loss"]), closing_snapshot_sha256=snapshot_hash,
                closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
            )

        odds_taken = float(row["odds_taken"])
        no_vig_at_bet = float(row["market_no_vig_at_bet"])
        approved_stake = float(row["approved_stake"])
        price_clv = odds_taken / closing_odds - 1
        probability_clv = closing_fair - no_vig_at_bet
        pnl = profit_loss(params.result, approved_stake, odds_taken)
        closing_record = {
            "schema_version": "doctore.closing-snapshot.v1", "decision_id": params.decision_id,
            "recorded_at": settled_at, "result": params.result.value,
            "closing_snapshot_sha256": snapshot_hash,
            "closing_no_vig_probability": closing_fair, "price_clv_pct": price_clv,
            "clv_probability_points": probability_clv, "market_snapshot": snapshot,
        }
        appended = append_closing_record(closing_record)
        row.update({
            "closing_odds": closing_odds, "closing_no_vig_probability": closing_fair,
            "price_clv_pct": price_clv, "clv_probability_points": probability_clv,
            "result": params.result.value, "profit_loss": pnl,
            "closing_snapshot_sha256": snapshot_hash, "settled_at": settled_at,
        })
        rows[index] = row
        write_bet_rows(rows)

    return SettleBetOutput(
        settled=True, idempotent_replay=not appended, decision_id=params.decision_id,
        closing_odds=closing_odds, closing_no_vig_probability=round(closing_fair, 12),
        price_clv_pct=round(price_clv, 12), clv_probability_points=round(probability_clv, 12),
        profit_loss=round(pnl, 2), closing_snapshot_sha256=snapshot_hash,
        closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
    )
