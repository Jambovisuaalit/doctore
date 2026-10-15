"""Canonical bet ledger persistence and portfolio aggregation."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator
import csv
import json
import os
import tempfile

from .decision_adapter import run_decision
from .runtime import BET_LOG_PATH, content_sha256, now_iso, parse_time
from .schemas import (
    ConfirmPlacementInput,
    ConfirmPlacementOutput,
    HumanDecision,
    LogBetInput,
    LogBetOutput,
    PortfolioStatusInput,
    PortfolioStatusOutput,
    schema_errors,
)

BET_LOG_FIELDS = [
    "logged_at", "decision_id", "event_id", "market_id", "sport",
    "competition", "market_type", "target_market", "period", "line_json",
    "settlement_rules", "selection", "book", "odds_taken",
    "market_no_vig_at_bet", "recommended_stake", "approved_stake",
    "human_decision", "model_name", "model_version", "calibration_status",
    "ev_at_bet", "edge_vs_market_pp", "closing_odds",
    "closing_no_vig_probability", "price_clv_pct", "clv_probability_points",
    "result", "profit_loss", "closing_snapshot_sha256", "settled_at",
    "event_start_at", "closing_missing_reason",
]

# Read both historical headers without silently claiming actual placement.
PRE_PLACEMENT_LOG_FIELDS = BET_LOG_FIELDS.copy()
BET_LOG_FIELDS += [
    "placement_status", "actual_stake", "actual_odds", "placed_at",
    "bookmaker_reference", "placement_sha256", "placement_policy_warnings",
    "evaluation_at", "max_placement_age_seconds", "currency", "approved_odds", "price_captured_at",
]

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


@contextmanager
def log_lock() -> Iterator[None]:
    lock_path = BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def line_to_csv(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def line_from_csv(value: str) -> Any:
    return json.loads(value)


def read_bet_rows() -> list[dict[str, str]]:
    if not BET_LOG_PATH.exists():
        from .settlement_store import path as settlement_db_path
        if settlement_db_path().exists():
            raise ValueError("settlement database exists but CSV ledger is missing; restore ledger")
        return []
    with BET_LOG_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        legacy_fields = PRE_PLACEMENT_LOG_FIELDS[:-2]
        if reader.fieldnames not in (BET_LOG_FIELDS, PRE_PLACEMENT_LOG_FIELDS, legacy_fields):
            raise ValueError(
                "DOCTORE_BET_LOG uses an incompatible legacy schema; migrate it before using this server"
            )
        rows = list(reader)
        for row in rows:
            for key in BET_LOG_FIELDS:
                row.setdefault(key, "")
            if not row["placement_status"]:
                row["placement_status"] = "LEGACY_UNCONFIRMED"
        from .settlement_store import overlay
        return overlay(rows)


def write_bet_rows(rows: list[dict[str, Any]]) -> None:
    BET_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=BET_LOG_PATH.name + ".", dir=BET_LOG_PATH.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BET_LOG_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, BET_LOG_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def append_bet_row(row: dict[str, Any]) -> None:
    rows = read_bet_rows()
    if any(existing["decision_id"] == row["decision_id"] for existing in rows):
        raise ValueError(f"decision_id already logged: {row['decision_id']}")
    rows.append(row)
    write_bet_rows(rows)


def approval_time() -> datetime:
    """Server clock; historical evaluation timestamps never authorize a live write."""
    return datetime.now(timezone.utc)


def current_approval_evaluation(params: LogBetInput, rows, now):
    """Conservatively reserve ledger liabilities in addition to external state.

    The snapshot has no ledger watermark/position identities. Subtracting presumed
    overlap would be unsafe. Pending approvals reserve capacity but are never
    reported as actual exposure. Unknown correlation is reserved across groups.
    """
    now = now.astimezone(timezone.utc)
    journal = BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".placements.jsonl")
    if journal.exists():
        for record in map(json.loads, filter(str.strip, journal.read_text(encoding="utf-8").splitlines())):
            if not any(row["decision_id"] == record["decision_id"] and
                       row.get("placement_sha256") == record["placement_sha256"] for row in rows):
                raise ValueError("APPROVAL_PLACEMENT_REPLAY_REQUIRED: repair journal/state before approval")
    evaluation = params.evaluation.model_copy(deep=True)
    portfolio = evaluation.portfolio_state
    captured = parse_time(portfolio["captured_at"])
    maximum = evaluation.risk_policy["freshness_seconds"]["portfolio_state"]
    age = (now - captured).total_seconds()
    if age < 0 or age > maximum:
        raise ValueError("APPROVAL_PORTFOLIO_STALE: refresh external bankroll and balance")
    amounts = {key: 0.0 for key in portfolio["exposures"]}
    for row in rows:
        if row.get("currency") and row["currency"] != portfolio["currency"]:
            raise ValueError("APPROVAL_CURRENCY_MISMATCH: ledger must have one currency")
        pending = row["placement_status"] == "APPROVED"
        stake = float(row.get("actual_stake") or row["approved_stake"])
        if not row.get("result"):
            amounts["open_amount"] += stake
            # Old ledger rows lack correlation IDs: reserve against every group.
            amounts["correlation_group_amount"] += stake
            if row["competition"] == portfolio["league"]:
                amounts["league_amount"] += stake
        at = parse_time(row.get("placed_at") or row["logged_at"])
        if pending or at.astimezone(timezone.utc).date() == now.date():
            amounts["daily_turnover_amount"] += stake
        if pending or at >= now - timedelta(days=3):
            amounts["rolling_3d_turnover_amount"] += stake
    for key, amount in amounts.items():
        portfolio["exposures"][key] += amount
    portfolio["available_balance"] = max(0, portfolio["available_balance"] - amounts["open_amount"])
    # Keep the original timestamp: freshness must not be fabricated.
    evaluation.evaluated_at = now.isoformat()
    return evaluation


def log_bet(params: LogBetInput) -> LogBetOutput:
    decision = params.decision_output
    errors = schema_errors("decision", decision)
    decision_id = str(decision.get("decision_id", ""))
    if errors:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="; ".join(errors), log_path=str(BET_LOG_PATH))
    recomputed = run_decision(params.evaluation)
    if recomputed != decision:
        return LogBetOutput(
            logged=False, decision_id=decision_id, approved_stake=None,
            reason="decision output does not match the canonical decision recomputed from evaluation inputs",
            log_path=str(BET_LOG_PATH),
        )
    market_snapshot = params.evaluation.market_snapshot
    market_errors = schema_errors("market", market_snapshot)
    if market_errors:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="; ".join(market_errors), log_path=str(BET_LOG_PATH))
    if content_sha256(market_snapshot) != decision["audit"]["market_snapshot_sha256"]:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="market snapshot hash does not match canonical decision audit", log_path=str(BET_LOG_PATH))
    if decision["decision"] != "BET":
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason=f"only BET decisions can be logged; received {decision['decision']}", log_path=str(BET_LOG_PATH))
    if params.human_decision == HumanDecision.REJECT:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="human decision rejected the bet", log_path=str(BET_LOG_PATH))

    recommended = float(decision["staking"]["final_stake"])
    approved = recommended if params.approved_stake is None else float(params.approved_stake)
    if approved > recommended + 1e-12:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason="approved stake cannot exceed canonical recommended stake", log_path=str(BET_LOG_PATH))
    if params.human_decision == HumanDecision.APPROVE and abs(approved - recommended) > 1e-12:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason="APPROVE must use the canonical stake; use REDUCE for a smaller stake", log_path=str(BET_LOG_PATH))
    if params.human_decision == HumanDecision.REDUCE and not approved < recommended:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason="REDUCE must use a stake below the canonical recommendation", log_path=str(BET_LOG_PATH))

    row = {
        "logged_at": now_iso(), "decision_id": decision_id,
        "event_id": decision["event_id"], "market_id": decision["market_id"],
        "sport": decision["sport"], "competition": decision["competition"],
        "market_type": market_snapshot["market_type"], "target_market": market_snapshot["target_market"],
        "period": market_snapshot["period"], "line_json": line_to_csv(market_snapshot["line"]),
        "settlement_rules": market_snapshot["settlement_rules"], "selection": decision["selection"],
        "book": decision["book"], "odds_taken": decision["decimal_odds"],
        "market_no_vig_at_bet": decision["market"]["no_vig_probability"],
        "recommended_stake": recommended, "approved_stake": approved,
        "human_decision": params.human_decision.value,
        "model_name": decision["model"]["model_name"], "model_version": decision["model"]["model_version"],
        "calibration_status": decision["model"]["calibration_status"],
        "ev_at_bet": decision["economics"]["ev"], "edge_vs_market_pp": decision["economics"]["edge_vs_market_pp"],
        "closing_odds": "", "closing_no_vig_probability": "", "price_clv_pct": "",
        "clv_probability_points": "", "result": "", "profit_loss": "",
        "closing_snapshot_sha256": "", "settled_at": "",
        "event_start_at": market_snapshot["event_start_at"], "closing_missing_reason": "",
        "placement_status": "APPROVED", "actual_stake": "", "actual_odds": "",
        "placed_at": "", "bookmaker_reference": "", "placement_sha256": "",
        "placement_policy_warnings": "", "evaluation_at": params.evaluation.evaluated_at,
        "max_placement_age_seconds": params.evaluation.risk_policy["freshness_seconds"]["market_snapshot"],
        "currency": params.evaluation.portfolio_state["currency"],
        "approved_odds": decision["decimal_odds"], "price_captured_at": market_snapshot["captured_at"],
    }
    with log_lock():
        try:
            rows = read_bet_rows()
            if any(existing["decision_id"] == decision_id for existing in rows):
                raise ValueError(f"decision_id already logged: {decision_id}")
            live_evaluation = current_approval_evaluation(params, rows, approval_time())
            live_decision = run_decision(live_evaluation)
            if live_decision["decision"] != "BET":
                raise ValueError("APPROVAL_REVALIDATION_BLOCKED: " + ", ".join(live_decision["reason_codes"]))
            if approved > float(live_decision["staking"]["final_stake"]) + 1e-12:
                raise ValueError("APPROVAL_RISK_CHANGED: refresh decision and human approval")
            row["logged_at"] = live_evaluation.evaluated_at
            rows.append(row)
            write_bet_rows(rows)
        except ValueError as exc:
            return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason=str(exc), log_path=str(BET_LOG_PATH))
    return LogBetOutput(logged=True, decision_id=decision_id, approved_stake=approved, placement_status="APPROVED", log_path=str(BET_LOG_PATH))


def confirm_placement(params: ConfirmPlacementInput) -> ConfirmPlacementOutput:
    """Record a user-confirmed external fact, never execute or authorize a bet.

    Actual policy breaches are retained with warnings rather than hidden by
    rejecting liabilities that already exist at the bookmaker.
    """
    placed_at = parse_time(params.placed_at)
    if placed_at > datetime.now(timezone.utc):
        raise ValueError("placed_at cannot be in the future")
    with log_lock():
        rows = read_bet_rows()
        matching = [row for row in rows if row["decision_id"] == params.decision_id]
        if len(matching) != 1:
            raise ValueError("expected exactly one approved decision")
        row = matching[0]
        payload = {
            "decision_id": params.decision_id,
            "actual_stake": params.actual_stake, "actual_odds": params.actual_odds,
            "placed_at": placed_at.astimezone(timezone.utc).isoformat(),
            "bookmaker_reference": params.bookmaker_reference, "book": row["book"],
            "currency": row.get("currency") or None,
        }
        digest = content_sha256(payload)
        if row.get("placement_sha256"):
            if row["placement_sha256"] != digest:
                raise ValueError("placement already confirmed with different facts")
            return ConfirmPlacementOutput(
                confirmed=True, idempotent_replay=True, decision_id=params.decision_id,
                actual_stake=params.actual_stake, actual_odds=params.actual_odds,
                placement_sha256=digest,
                policy_warnings=json.loads(row["placement_policy_warnings"]),
            )
        if row.get("result"):
            raise ValueError("legacy settled records require an explicit migration/revision")
        if any(other["book"] == row["book"] and other.get("bookmaker_reference") == params.bookmaker_reference
               for other in rows if other["decision_id"] != params.decision_id):
            raise ValueError("bookmaker reference is already attached to another decision")
        warnings = []
        if params.actual_stake > float(row["approved_stake"]) + 1e-12:
            warnings.append("ACTUAL_STAKE_EXCEEDS_APPROVAL")
        approved_odds = float(row.get("approved_odds") or row["odds_taken"])
        if params.actual_odds < approved_odds:
            warnings.append("ACTUAL_ODDS_BELOW_APPROVAL")
        if row.get("event_start_at") and placed_at >= parse_time(row["event_start_at"]):
            warnings.append("PLACED_AT_OR_AFTER_EVENT_START")
        if row.get("evaluation_at") and placed_at < parse_time(row["evaluation_at"]):
            warnings.append("PLACED_BEFORE_EVALUATION")
        if row.get("price_captured_at") and row.get("max_placement_age_seconds"):
            age = (placed_at - parse_time(row["price_captured_at"])).total_seconds()
            if age > float(row["max_placement_age_seconds"]):
                warnings.append("APPROVED_PRICE_EXPIRED_AT_PLACEMENT")
        if row["placement_status"] == "LEGACY_UNCONFIRMED":
            warnings.append("LEGACY_APPROVAL_PROVENANCE_INCOMPLETE")
        journal = BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".placements.jsonl")
        records = []
        if journal.exists():
            records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        existing = [record for record in records if record["decision_id"] == params.decision_id]
        if existing and (len(existing) != 1 or existing[0]["placement_sha256"] != digest):
            raise ValueError("conflicting placement journal entry")
        if any(record.get("book") == row["book"] and record.get("bookmaker_reference") == params.bookmaker_reference
               for record in records if record["decision_id"] != params.decision_id):
            raise ValueError("bookmaker reference is already journaled for another decision")
        if not existing:
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**payload, "placement_sha256": digest,
                                         "confirmed_at": now_iso(), "policy_warnings": warnings}, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        else:
            warnings = existing[0]["policy_warnings"]
        row.update({
            "placement_status": "PLACED", "actual_stake": params.actual_stake,
            "actual_odds": params.actual_odds, "odds_taken": params.actual_odds,
            "approved_odds": approved_odds, "placed_at": payload["placed_at"],
            "bookmaker_reference": params.bookmaker_reference,
            "placement_sha256": digest, "placement_policy_warnings": json.dumps(warnings),
        })
        write_bet_rows(rows)
        return ConfirmPlacementOutput(
            confirmed=True, idempotent_replay=bool(existing), decision_id=params.decision_id,
            actual_stake=params.actual_stake, actual_odds=params.actual_odds,
            placement_sha256=digest, policy_warnings=warnings,
        )


def portfolio_status(params: PortfolioStatusInput) -> PortfolioStatusOutput:
    with log_lock():
        rows = read_bet_rows()
    pending = [row for row in rows if row["placement_status"] == "APPROVED"]
    legacy = [row for row in rows if row["placement_status"] == "LEGACY_UNCONFIRMED"]
    open_rows = [row for row in rows if not row.get("result") and row["placement_status"] != "APPROVED"]
    settled = [row for row in rows if row.get("result")]
    decisive = [row for row in settled if row["result"] in {"win", "loss", "half_win", "half_loss"}]
    wins = sum(row["result"] in {"win", "half_win"} for row in decisive)
    price_clv = [float(row["price_clv_pct"]) for row in settled if row.get("price_clv_pct")]
    probability_clv = [float(row["clv_probability_points"]) for row in settled if row.get("clv_probability_points")]
    counts: dict[str, int] = {}
    for row in settled:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    exposure = sum(float(row.get("actual_stake") or row["approved_stake"]) for row in open_rows)
    return PortfolioStatusOutput(
        pending_approval_count=len(pending),
        approved_unplaced_amount=round(sum(float(row["approved_stake"]) for row in pending), 2),
        legacy_unconfirmed_count=len(legacy),
        open_bet_count=len(open_rows), open_exposure=round(exposure, 2),
        exposure_pct_of_bankroll=round(exposure / params.bankroll * 100, 4),
        settled_bet_count=len(settled), decisive_bet_count=len(decisive),
        win_rate=round(wins / len(decisive), 6) if decisive else None,
        realized_profit_loss=round(sum(float(row["profit_loss"]) for row in settled if row.get("profit_loss")), 2),
        avg_price_clv_pct=round(sum(price_clv) / len(price_clv), 6) if price_clv else None,
        avg_clv_probability_points=round(sum(probability_clv) / len(probability_clv), 6) if probability_clv else None,
        result_counts=counts,
    )
