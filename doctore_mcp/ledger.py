"""Canonical bet ledger persistence and portfolio aggregation."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
import csv
import json
import os
import tempfile

from .decision_adapter import run_decision
from .runtime import BET_LOG_PATH, content_sha256, now_iso
from .schemas import (
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
        return []
    with BET_LOG_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != BET_LOG_FIELDS:
            raise ValueError(
                "DOCTORE_BET_LOG uses an incompatible legacy schema; migrate it before using this server"
            )
        return list(reader)


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
    }
    with log_lock():
        try:
            append_bet_row(row)
        except ValueError as exc:
            return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason=str(exc), log_path=str(BET_LOG_PATH))
    return LogBetOutput(logged=True, decision_id=decision_id, approved_stake=approved, log_path=str(BET_LOG_PATH))


def portfolio_status(params: PortfolioStatusInput) -> PortfolioStatusOutput:
    with log_lock():
        rows = read_bet_rows()
    open_rows = [row for row in rows if not row.get("result")]
    settled = [row for row in rows if row.get("result")]
    decisive = [row for row in settled if row["result"] in {"win", "loss", "half_win", "half_loss"}]
    wins = sum(row["result"] in {"win", "half_win"} for row in decisive)
    price_clv = [float(row["price_clv_pct"]) for row in settled if row.get("price_clv_pct")]
    probability_clv = [float(row["clv_probability_points"]) for row in settled if row.get("clv_probability_points")]
    counts: dict[str, int] = {}
    for row in settled:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    exposure = sum(float(row["approved_stake"]) for row in open_rows)
    return PortfolioStatusOutput(
        open_bet_count=len(open_rows), open_exposure=round(exposure, 2),
        exposure_pct_of_bankroll=round(exposure / params.bankroll * 100, 4),
        settled_bet_count=len(settled), decisive_bet_count=len(decisive),
        win_rate=round(wins / len(decisive), 6) if decisive else None,
        realized_profit_loss=round(sum(float(row["profit_loss"]) for row in settled if row.get("profit_loss")), 2),
        avg_price_clv_pct=round(sum(price_clv) / len(price_clv), 6) if price_clv else None,
        avg_clv_probability_points=round(sum(probability_clv) / len(probability_clv), 6) if probability_clv else None,
        result_counts=counts,
    )
