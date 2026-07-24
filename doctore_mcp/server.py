"""Personal stdio MCP server for the canonical Doctore decision pipeline."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from jsonschema import Draft202012Validator, FormatChecker
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

DOCTORE_REPO_PATH = os.environ.get("DOCTORE_REPO_PATH", "").strip()
DOCTORE_BET_LOG_RAW = os.environ.get("DOCTORE_BET_LOG", "").strip()
if not DOCTORE_REPO_PATH:
    raise RuntimeError("DOCTORE_REPO_PATH is required and must point to the doctore repository root")
if not DOCTORE_BET_LOG_RAW:
    raise RuntimeError("DOCTORE_BET_LOG is required; no sample-log fallback is permitted")

REPO = Path(DOCTORE_REPO_PATH).expanduser().resolve()
SRC = REPO / "src"
if not (SRC / "bet_decision_core.py").exists():
    raise RuntimeError(f"canonical decision core not found: {SRC / 'bet_decision_core.py'}")
if not (SRC / "model_output_adapter.py").exists():
    raise RuntimeError(f"model output adapter not found: {SRC / 'model_output_adapter.py'}")

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO))

from bet_decision_core import _no_vig, evaluate_bet_decision  # noqa: E402
from model_output_adapter import to_model_output_contract  # noqa: E402

try:
    from .pinnacle_parser import parse_pinnacle_table
except ImportError:
    from pinnacle_parser import parse_pinnacle_table

BET_LOG_PATH = Path(DOCTORE_BET_LOG_RAW).expanduser().resolve()
CLOSING_SNAPSHOT_PATH = Path(
    os.environ.get(
        "DOCTORE_CLOSING_SNAPSHOT_LOG",
        str(BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".closing.jsonl")),
    )
).expanduser().resolve()
MAX_SNAPSHOT_AGE_MINUTES = float(os.environ.get("DOCTORE_MAX_SNAPSHOT_AGE_MIN", "5"))

SCHEMA_VALIDATORS = {
    name: Draft202012Validator(
        json.loads((REPO / "contracts" / filename).read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    for name, filename in {
        "model": "model-output.schema.json",
        "market": "market-snapshot.schema.json",
        "portfolio": "portfolio-state.schema.json",
        "policy": "risk-policy.schema.json",
        "decision": "decision-output.schema.json",
    }.items()
}

mcp = FastMCP("doctore_mcp")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _minutes_since(value: str) -> float:
    return (datetime.now(timezone.utc) - _parse_time(value).astimezone(timezone.utc)).total_seconds() / 60


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_errors(name: str, payload: Mapping[str, Any]) -> list[str]:
    errors = sorted(
        SCHEMA_VALIDATORS[name].iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return [
        f"{name}.{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in errors
    ]


def _line_to_csv(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _line_from_csv(value: str) -> Any:
    return json.loads(value)


try:
    import fcntl
except ImportError:
    fcntl = None


@contextmanager
def _log_lock() -> Iterator[None]:
    lock_path = BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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


def _read_bet_rows() -> list[dict[str, str]]:
    if not BET_LOG_PATH.exists():
        return []
    with BET_LOG_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != BET_LOG_FIELDS:
            raise ValueError(
                "DOCTORE_BET_LOG uses an incompatible legacy schema; migrate it before using this server"
            )
        return list(reader)


def _write_bet_rows(rows: list[dict[str, Any]]) -> None:
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


def _append_bet_row(row: dict[str, Any]) -> None:
    rows = _read_bet_rows()
    if any(existing["decision_id"] == row["decision_id"] for existing in rows):
        raise ValueError(f"decision_id already logged: {row['decision_id']}")
    rows.append(row)
    _write_bet_rows(rows)


def _closing_records() -> list[dict[str, Any]]:
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


def _append_closing_record(record: dict[str, Any]) -> bool:
    existing = [item for item in _closing_records() if item.get("decision_id") == record["decision_id"]]
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


class Sport(str, Enum):
    MLB = "mlb"
    KBO = "kbo"
    NPB = "npb"
    WNBA = "wnba"
    NBA = "nba"


class ParsePinnacleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    raw_table: str = Field(..., min_length=10)
    sport: Sport
    event_date: date
    timezone_name: str = "Europe/Helsinki"
    competition: Optional[str] = None
    captured_at: Optional[str] = None


class ParsePinnacleOutput(BaseModel):
    schema_version: str = "doctore.pinnacle-parse-result.v2"
    parsed_game_count: int
    snapshot_count: int
    rejected_row_count: int
    skipped_row_count: int
    snapshots: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]


class QualityGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_at: str
    max_age_minutes: Optional[float] = Field(default=None, gt=0)
    reference_odds: Optional[dict[str, float]] = None
    current_odds: Optional[dict[str, float]] = None
    contradiction_threshold_pct: float = Field(default=5.0, ge=0)


class QualityGateOutput(BaseModel):
    status: str
    reasons: list[str]
    age_minutes: Optional[float]


class LoadPredictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_path: str
    market_id: str
    competition: str
    target_market: str
    settlement_rules: str = "standard"


class LoadPredictionOutput(BaseModel):
    ok: bool
    model_output: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_output: dict[str, Any]
    market_snapshot: dict[str, Any]
    portfolio_state: dict[str, Any]
    risk_policy: dict[str, Any]
    evaluated_at: str
    sport_context: Optional[dict[str, Any]] = None


class EdgeAndStakeOutput(BaseModel):
    schema_version: str = "doctore.edge-and-stake.v2"
    decision_id: str
    decision: str
    reason_codes: list[str]
    no_vig_probability: Optional[float]
    overround: Optional[float]
    ev: Optional[float]
    edge_vs_market_pp: Optional[float]
    full_kelly: Optional[float]
    recommended_stake: float
    staking: dict[str, Any]
    human_approval_required: bool


class EvaluateOutput(BaseModel):
    schema_version: str = "doctore.mcp-evaluation.v2"
    decision_output: dict[str, Any]
    recommended_stake: float


class HumanDecision(str, Enum):
    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"


class LogBetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation: DecisionInput
    decision_output: dict[str, Any]
    human_decision: HumanDecision
    approved_stake: Optional[float] = Field(default=None, gt=0)


class LogBetOutput(BaseModel):
    logged: bool
    decision_id: str
    approved_stake: Optional[float]
    reason: Optional[str] = None
    log_path: str


class SettlementResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    VOID = "void"
    HALF_WIN = "half_win"
    HALF_LOSS = "half_loss"


class SettleBetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    closing_market_snapshot: dict[str, Any]
    result: SettlementResult
    settled_at: Optional[str] = None


class SettleBetOutput(BaseModel):
    settled: bool
    idempotent_replay: bool
    decision_id: str
    closing_odds: float
    closing_no_vig_probability: float
    price_clv_pct: float
    clv_probability_points: float
    profit_loss: float
    closing_snapshot_sha256: str
    closing_snapshot_log_path: str


class PortfolioStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bankroll: float = Field(..., gt=0)


class PortfolioStatusOutput(BaseModel):
    open_bet_count: int
    open_exposure: float
    exposure_pct_of_bankroll: float
    settled_bet_count: int
    decisive_bet_count: int
    win_rate: Optional[float]
    realized_profit_loss: float
    avg_price_clv_pct: Optional[float]
    avg_clv_probability_points: Optional[float]
    result_counts: dict[str, int]


def _run_decision(params: DecisionInput) -> dict[str, Any]:
    return evaluate_bet_decision(
        model_output=params.model_output,
        market_snapshot=params.market_snapshot,
        portfolio_state=params.portfolio_state,
        risk_policy=params.risk_policy,
        evaluated_at=params.evaluated_at,
        sport_context=params.sport_context,
    )


@mcp.tool(
    name="doctore_parse_pinnacle_table",
    annotations={"title": "Parse Pinnacle table", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_parse_pinnacle_table(params: ParsePinnacleInput) -> ParsePinnacleOutput:
    """Parse a copied Pinnacle table into canonical selected-side market snapshots."""
    captured = _parse_time(params.captured_at) if params.captured_at else datetime.now(timezone.utc)
    snapshots, diagnostics = parse_pinnacle_table(
        params.raw_table,
        params.sport.value,
        event_date=params.event_date,
        captured_at=captured,
        timezone_name=params.timezone_name,
        competition=params.competition,
    )
    serialized_diagnostics = [
        {"row_number": item.row_number, "status": item.status, "reason": item.reason, "raw_row": item.raw_row}
        for item in diagnostics
    ]
    return ParsePinnacleOutput(
        parsed_game_count=sum(item.status == "PARSED" for item in diagnostics),
        snapshot_count=len(snapshots),
        rejected_row_count=sum(item.status == "REJECTED" for item in diagnostics),
        skipped_row_count=sum(item.status == "SKIPPED" for item in diagnostics),
        snapshots=snapshots,
        diagnostics=serialized_diagnostics,
    )


@mcp.tool(
    name="doctore_check_data_quality",
    annotations={"title": "Check data freshness and contradictions", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_check_data_quality(params: QualityGateInput) -> QualityGateOutput:
    """Block stale, future-dated, malformed, or materially contradictory odds data."""
    reasons: list[str] = []
    age: Optional[float]
    try:
        age = _minutes_since(params.snapshot_at)
    except (TypeError, ValueError) as exc:
        return QualityGateOutput(status="BLOCKED", reasons=[f"invalid snapshot_at: {exc}"], age_minutes=None)
    limit = params.max_age_minutes or MAX_SNAPSHOT_AGE_MINUTES
    if age < 0:
        reasons.append(f"snapshot timestamp is {-age:.1f} minutes in the future")
    elif age > limit:
        reasons.append(f"snapshot is {age:.1f} minutes old; limit is {limit:.1f}")

    if (params.reference_odds is None) != (params.current_odds is None):
        reasons.append("reference_odds and current_odds must be supplied together")
    elif params.reference_odds is not None and params.current_odds is not None:
        for selection, reference in params.reference_odds.items():
            if selection not in params.current_odds:
                reasons.append(f"current odds missing selection {selection!r}")
                continue
            current = params.current_odds[selection]
            if reference <= 1 or current <= 1:
                reasons.append(f"{selection!r}: decimal odds must be greater than 1")
                continue
            difference = abs(current - reference) / reference * 100
            if difference > params.contradiction_threshold_pct:
                reasons.append(
                    f"{selection!r}: reference {reference} vs current {current} "
                    f"({difference:.1f}% difference; limit {params.contradiction_threshold_pct:.1f}%)"
                )
    return QualityGateOutput(
        status="BLOCKED" if reasons else "PASS",
        reasons=reasons,
        age_minutes=round(age, 3),
    )


@mcp.tool(
    name="doctore_load_model_prediction",
    annotations={"title": "Load canonical model prediction", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_load_model_prediction(params: LoadPredictionInput) -> LoadPredictionOutput:
    """Load a versioned prediction artifact and adapt it to doctore.model-output.v1."""
    path = Path(params.prediction_path).expanduser().resolve()
    try:
        prediction = json.loads(path.read_text(encoding="utf-8"))
        canonical = to_model_output_contract(
            prediction,
            market_id=params.market_id,
            competition=params.competition,
            target_market=params.target_market,
            settlement_rules=params.settlement_rules,
        )
        errors = _schema_errors("model", canonical)
        if errors:
            return LoadPredictionOutput(ok=False, error="; ".join(errors))
        return LoadPredictionOutput(ok=True, model_output=canonical)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LoadPredictionOutput(ok=False, error=str(exc))


@mcp.tool(
    name="doctore_calculate_edge_and_stake",
    annotations={"title": "Calculate canonical no-vig, EV and stake", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_calculate_edge_and_stake(params: DecisionInput) -> EdgeAndStakeOutput:
    """Delegate no-vig, EV, edge, Kelly and caps to src/bet_decision_core.py."""
    decision = _run_decision(params)
    recommended = decision["staking"]["final_stake"] if decision["decision"] == "BET" else 0.0
    return EdgeAndStakeOutput(
        decision_id=decision["decision_id"],
        decision=decision["decision"],
        reason_codes=decision["reason_codes"],
        no_vig_probability=decision["market"]["no_vig_probability"],
        overround=decision["market"]["overround"],
        ev=decision["economics"]["ev"],
        edge_vs_market_pp=decision["economics"]["edge_vs_market_pp"],
        full_kelly=decision["economics"]["full_kelly"],
        recommended_stake=float(recommended or 0.0),
        staking=decision["staking"],
        human_approval_required=decision["human_approval_required"],
    )


@mcp.tool(
    name="doctore_evaluate_bet",
    annotations={"title": "Evaluate canonical bet decision", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_evaluate_bet(params: DecisionInput, ctx: Context | None = None) -> EvaluateOutput:
    """Run exact-domain validation, no-vig, economics and risk through the canonical core."""
    if ctx is not None:
        try:
            await ctx.report_progress(0.2, "Validating canonical inputs")
        except (RuntimeError, ValueError):
            pass
    decision = _run_decision(params)
    if ctx is not None:
        try:
            await ctx.report_progress(1.0, "Decision complete")
        except (RuntimeError, ValueError):
            pass
    recommended = decision["staking"]["final_stake"] if decision["decision"] == "BET" else 0.0
    return EvaluateOutput(decision_output=decision, recommended_stake=float(recommended or 0.0))


@mcp.tool(
    name="doctore_log_bet",
    annotations={"title": "Log a human-approved canonical bet", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def doctore_log_bet(params: LogBetInput) -> LogBetOutput:
    """Log only a canonical BET decision; approval may reduce but never increase stake."""
    decision = params.decision_output
    errors = _schema_errors("decision", decision)
    decision_id = str(decision.get("decision_id", ""))
    if errors:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="; ".join(errors), log_path=str(BET_LOG_PATH))
    recomputed = _run_decision(params.evaluation)
    if recomputed != decision:
        return LogBetOutput(
            logged=False,
            decision_id=decision_id,
            approved_stake=None,
            reason="decision output does not match the canonical decision recomputed from evaluation inputs",
            log_path=str(BET_LOG_PATH),
        )
    market_snapshot = params.evaluation.market_snapshot
    market_errors = _schema_errors("market", market_snapshot)
    if market_errors:
        return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=None, reason="; ".join(market_errors), log_path=str(BET_LOG_PATH))
    if _sha256(market_snapshot) != decision["audit"]["market_snapshot_sha256"]:
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
        "logged_at": _now_iso(),
        "decision_id": decision_id,
        "event_id": decision["event_id"],
        "market_id": decision["market_id"],
        "sport": decision["sport"],
        "competition": decision["competition"],
        "market_type": market_snapshot["market_type"],
        "target_market": market_snapshot["target_market"],
        "period": market_snapshot["period"],
        "line_json": _line_to_csv(market_snapshot["line"]),
        "settlement_rules": market_snapshot["settlement_rules"],
        "selection": decision["selection"],
        "book": decision["book"],
        "odds_taken": decision["decimal_odds"],
        "market_no_vig_at_bet": decision["market"]["no_vig_probability"],
        "recommended_stake": recommended,
        "approved_stake": approved,
        "human_decision": params.human_decision.value,
        "model_name": decision["model"]["model_name"],
        "model_version": decision["model"]["model_version"],
        "calibration_status": decision["model"]["calibration_status"],
        "ev_at_bet": decision["economics"]["ev"],
        "edge_vs_market_pp": decision["economics"]["edge_vs_market_pp"],
        "closing_odds": "",
        "closing_no_vig_probability": "",
        "price_clv_pct": "",
        "clv_probability_points": "",
        "result": "",
        "profit_loss": "",
        "closing_snapshot_sha256": "",
        "settled_at": "",
    }
    with _log_lock():
        try:
            _append_bet_row(row)
        except ValueError as exc:
            return LogBetOutput(logged=False, decision_id=decision_id, approved_stake=approved, reason=str(exc), log_path=str(BET_LOG_PATH))
    return LogBetOutput(logged=True, decision_id=decision_id, approved_stake=approved, log_path=str(BET_LOG_PATH))


def _profit_loss(result: SettlementResult, stake: float, odds: float) -> float:
    if result == SettlementResult.WIN:
        return stake * (odds - 1)
    if result == SettlementResult.LOSS:
        return -stake
    if result in {SettlementResult.PUSH, SettlementResult.VOID}:
        return 0.0
    if result == SettlementResult.HALF_WIN:
        return stake * 0.5 * (odds - 1)
    return -stake * 0.5


def _settlement_domain_mismatches(row: Mapping[str, str], snapshot: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("event_id", "market_id", "sport", "competition", "selection", "book"):
        expected = row.get(key, "")
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    optional = {
        "market_type": row.get("market_type", ""),
        "target_market": row.get("target_market", ""),
        "period": row.get("period", ""),
        "settlement_rules": row.get("settlement_rules", ""),
    }
    for key, expected in optional.items():
        if expected and snapshot.get(key) != expected:
            mismatches.append(key)
    if row.get("line_json"):
        expected_line = _line_from_csv(row["line_json"])
        if snapshot.get("line") != expected_line:
            mismatches.append("line")
    return mismatches


@mcp.tool(
    name="doctore_settle_bet",
    annotations={"title": "Settle bet with closing-line snapshot", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_settle_bet(params: SettleBetInput) -> SettleBetOutput:
    """Settle one logged decision and append a content-addressed closing snapshot."""
    snapshot = params.closing_market_snapshot
    errors = _schema_errors("market", snapshot)
    if errors:
        raise ValueError("invalid closing market snapshot: " + "; ".join(errors))
    if _parse_time(snapshot["captured_at"]) > _parse_time(snapshot["event_start_at"]):
        raise ValueError("closing snapshot was captured after event start")
    raw, closing_fair, _, _ = _no_vig(snapshot)
    del raw
    closing_odds = float(snapshot["decimal_odds"])
    snapshot_hash = _sha256(snapshot)
    settled_at = params.settled_at or _now_iso()
    settled_time = _parse_time(settled_at)
    if settled_time < _parse_time(snapshot["event_start_at"]):
        raise ValueError("settled_at cannot be before event start")

    with _log_lock():
        rows = _read_bet_rows()
        indexes = [index for index, row in enumerate(rows) if row["decision_id"] == params.decision_id]
        if len(indexes) != 1:
            raise ValueError(f"expected exactly one logged row for {params.decision_id}; found {len(indexes)}")
        index = indexes[0]
        row = rows[index]
        mismatches = _settlement_domain_mismatches(row, snapshot)
        if mismatches:
            raise ValueError("closing snapshot domain mismatch: " + ", ".join(mismatches))

        already_settled = bool(row.get("result"))
        if already_settled:
            same = row["result"] == params.result.value and row["closing_snapshot_sha256"] == snapshot_hash
            if not same:
                raise ValueError("bet is already settled with different closing data")
            return SettleBetOutput(
                settled=True,
                idempotent_replay=True,
                decision_id=params.decision_id,
                closing_odds=float(row["closing_odds"]),
                closing_no_vig_probability=float(row["closing_no_vig_probability"]),
                price_clv_pct=float(row["price_clv_pct"]),
                clv_probability_points=float(row["clv_probability_points"]),
                profit_loss=float(row["profit_loss"]),
                closing_snapshot_sha256=snapshot_hash,
                closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
            )

        odds_taken = float(row["odds_taken"])
        no_vig_at_bet = float(row["market_no_vig_at_bet"])
        approved_stake = float(row["approved_stake"])
        price_clv = odds_taken / closing_odds - 1
        probability_clv = closing_fair - no_vig_at_bet
        pnl = _profit_loss(params.result, approved_stake, odds_taken)
        closing_record = {
            "schema_version": "doctore.closing-snapshot.v1",
            "decision_id": params.decision_id,
            "recorded_at": settled_at,
            "result": params.result.value,
            "closing_snapshot_sha256": snapshot_hash,
            "closing_no_vig_probability": closing_fair,
            "price_clv_pct": price_clv,
            "clv_probability_points": probability_clv,
            "market_snapshot": snapshot,
        }
        appended = _append_closing_record(closing_record)
        row.update({
            "closing_odds": closing_odds,
            "closing_no_vig_probability": closing_fair,
            "price_clv_pct": price_clv,
            "clv_probability_points": probability_clv,
            "result": params.result.value,
            "profit_loss": pnl,
            "closing_snapshot_sha256": snapshot_hash,
            "settled_at": settled_at,
        })
        rows[index] = row
        _write_bet_rows(rows)

    return SettleBetOutput(
        settled=True,
        idempotent_replay=not appended,
        decision_id=params.decision_id,
        closing_odds=closing_odds,
        closing_no_vig_probability=round(closing_fair, 12),
        price_clv_pct=round(price_clv, 12),
        clv_probability_points=round(probability_clv, 12),
        profit_loss=round(pnl, 2),
        closing_snapshot_sha256=snapshot_hash,
        closing_snapshot_log_path=str(CLOSING_SNAPSHOT_PATH),
    )


@mcp.tool(
    name="doctore_portfolio_status",
    annotations={"title": "Read portfolio exposure and settlement metrics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def doctore_portfolio_status(params: PortfolioStatusInput) -> PortfolioStatusOutput:
    """Calculate open exposure, realized P/L, win rate and CLV from the canonical log."""
    with _log_lock():
        rows = _read_bet_rows()
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
        open_bet_count=len(open_rows),
        open_exposure=round(exposure, 2),
        exposure_pct_of_bankroll=round(exposure / params.bankroll * 100, 4),
        settled_bet_count=len(settled),
        decisive_bet_count=len(decisive),
        win_rate=round(wins / len(decisive), 6) if decisive else None,
        realized_profit_loss=round(sum(float(row["profit_loss"]) for row in settled if row.get("profit_loss")), 2),
        avg_price_clv_pct=round(sum(price_clv) / len(price_clv), 6) if price_clv else None,
        avg_clv_probability_points=round(sum(probability_clv) / len(probability_clv), 6) if probability_clv else None,
        result_counts=counts,
    )


if __name__ == "__main__":
    mcp.run()
