"""Closing-line validation, CLV computation and settlement persistence."""
from __future__ import annotations

from typing import Any, Mapping
import json
import os

from .runtime import CLOSING_SNAPSHOT_PATH, content_sha256, now_iso, parse_time
from market_probability import calculate_market_probabilities
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
            and existing[0].get("closing_missing_reason") == record.get("closing_missing_reason")
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
    closing_fair = closing_odds = snapshot_hash = None
    settled_at = params.settled_at or now_iso()
    if snapshot is None:
        if not params.closing_missing_reason or not params.closing_missing_reason.strip():
            raise ValueError("closing_missing_reason is required without closing data")
    else:
        if params.closing_missing_reason is not None:
            raise ValueError("closing_missing_reason cannot accompany closing data")
        errors = schema_errors("market", snapshot)
        if errors:
            raise ValueError("invalid closing market snapshot: " + "; ".join(errors))
        if parse_time(snapshot["captured_at"]) > parse_time(snapshot["event_start_at"]):
            raise ValueError("closing snapshot was captured after event start")
        if parse_time(snapshot["captured_at"]) > parse_time(settled_at):
            raise ValueError("closing snapshot was captured after settlement")
        closing_fair = calculate_market_probabilities(snapshot)["no_vig_probability"]
        closing_odds = float(snapshot["decimal_odds"])
        snapshot_hash = content_sha256(snapshot)

    with log_lock():
        rows = read_bet_rows()
        indexes = [index for index, row in enumerate(rows) if row["decision_id"] == params.decision_id]
        if len(indexes) != 1:
            raise ValueError(f"expected exactly one logged row for {params.decision_id}; found {len(indexes)}")
        index = indexes[0]
        row = rows[index]
        if row["placement_status"] != "PLACED":
            raise ValueError("actual placement must be confirmed before settlement")
        # New records bind timing to the original market, not caller-supplied closing data.
        event_start = row.get("event_start_at")
        if snapshot is not None:
            mismatches = settlement_domain_mismatches(row, snapshot)
            if event_start and parse_time(event_start) != parse_time(snapshot["event_start_at"]):
                mismatches.append("event_start_at")
            if mismatches:
                raise ValueError("closing snapshot domain mismatch: " + ", ".join(mismatches))
            event_start = event_start or snapshot["event_start_at"]
        if snapshot is not None and parse_time(snapshot["captured_at"]) < parse_time(row["placed_at"]):
            raise ValueError("closing snapshot cannot precede actual placement")
        if not event_start:
            raise ValueError("legacy bet lacks event_start_at; provide exact-domain closing data")
        if parse_time(settled_at) < parse_time(row["placed_at"]):
            raise ValueError("settled_at cannot be before actual placement")
        if parse_time(settled_at) < parse_time(event_start):
            raise ValueError("settled_at cannot be before event start")

        if row.get("result"):
            same = (
                row["result"] == params.result.value
                and (row.get("closing_snapshot_sha256") or None) == snapshot_hash
                and (row.get("closing_missing_reason") or None) == params.closing_missing_reason
            )
            if not same:
                raise ValueError("bet is already settled with different closing data")
            optional_number = lambda key: float(row[key]) if row.get(key) else None
            return SettleBetOutput(
                settled=True, idempotent_replay=True, decision_id=params.decision_id,
                closing_odds=optional_number("closing_odds"),
                closing_no_vig_probability=optional_number("closing_no_vig_probability"),
                price_clv_pct=optional_number("price_clv_pct"),
                clv_probability_points=optional_number("clv_probability_points"),
                profit_loss=float(row["profit_loss"]), closing_snapshot_sha256=snapshot_hash,
                closing_missing_reason=params.closing_missing_reason,
                closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
            )

        odds_taken = float(row["odds_taken"])
        no_vig_at_bet = float(row["market_no_vig_at_bet"])
        approved_stake = float(row["actual_stake"])
        price_clv = odds_taken / closing_odds - 1 if closing_odds is not None else None
        probability_clv = closing_fair - no_vig_at_bet if closing_fair is not None else None
        pnl = profit_loss(params.result, approved_stake, odds_taken)
        closing_record = {
            "schema_version": "doctore.closing-snapshot.v1", "decision_id": params.decision_id,
            "recorded_at": settled_at, "result": params.result.value,
            "closing_snapshot_sha256": snapshot_hash,
            "closing_no_vig_probability": closing_fair, "price_clv_pct": price_clv,
            "clv_probability_points": probability_clv, "market_snapshot": snapshot,
            "closing_missing_reason": params.closing_missing_reason,
        }
        appended = append_closing_record(closing_record)
        row.update({
            "closing_odds": closing_odds, "closing_no_vig_probability": closing_fair,
            "price_clv_pct": price_clv, "clv_probability_points": probability_clv,
            "result": params.result.value, "profit_loss": pnl,
            "closing_snapshot_sha256": snapshot_hash, "settled_at": settled_at,
            "event_start_at": event_start, "closing_missing_reason": params.closing_missing_reason,
        })
        rows[index] = row
        write_bet_rows(rows)

    optional_round = lambda value: round(value, 12) if value is not None else None
    return SettleBetOutput(
        settled=True, idempotent_replay=not appended, decision_id=params.decision_id,
        closing_odds=closing_odds, closing_no_vig_probability=optional_round(closing_fair),
        price_clv_pct=optional_round(price_clv), clv_probability_points=optional_round(probability_clv),
        profit_loss=round(pnl, 2), closing_snapshot_sha256=snapshot_hash,
        closing_missing_reason=params.closing_missing_reason,
        closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
    )
