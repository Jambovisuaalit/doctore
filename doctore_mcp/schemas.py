"""Pydantic MCP tool contracts and canonical JSON Schema validation."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Mapping, Optional
import json

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field

from .runtime import REPO

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


def schema_errors(name: str, payload: Mapping[str, Any]) -> list[str]:
    errors = sorted(
        SCHEMA_VALIDATORS[name].iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return [
        f"{name}.{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in errors
    ]


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
    captured_at: str = Field(..., description="Required ISO-8601 capture time for idempotent parsing")


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
