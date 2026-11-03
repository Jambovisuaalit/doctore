"""Pydantic MCP tool contracts and canonical JSON Schema validation."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal, Mapping, Optional
import json

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field

from .runtime import REPO
from .public_contracts import exposed_contract

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
        "artifact": "probability-prediction.schema.json",
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
    commence_time: Optional[str] = None
    last_update: Optional[str] = None
    live_verified: bool = False
    max_age_minutes: Optional[float] = Field(default=None, gt=0)
    reference_odds: Optional[dict[str, float]] = None
    current_odds: Optional[dict[str, float]] = None
    contradiction_threshold_pct: float = Field(default=5.0, ge=0)


class QualityGateOutput(BaseModel):
    status: str
    reasons: list[str]
    age_minutes: Optional[float]
    market_state: Optional[str] = None


class LoadPredictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_path: str = Field(..., description="Path inside the configured artifact root or repository examples. File contents follow x-doctore-artifact-schema; structural loading is not provenance authentication.", json_schema_extra={"x-doctore-artifact-schema": exposed_contract("artifact"), "x-doctore-artifact-schema-uri": "doctore://contracts/probability-prediction.schema.json"})
    market_id: str
    competition: str
    target_market: str
    settlement_rules: str = Field(default="standard", description="Exact payoff convention from the bound market snapshot. Legacy default standard is a structural artifact label only and is not supported canonical NBA/WNBA/MLB/soccer arithmetic. Read market_snapshot.settlement_rules schema description for sport-specific values; never infer or translate bookmaker rules.")
    registry_manifest_path: Optional[str] = None
    registry_calibration_path: Optional[str] = None
    registry_oos_path: Optional[str] = None
    registry_model_artifact_path: Optional[str] = None
    registry_calibrator_artifact_path: Optional[str] = None


class LoadPredictionOutput(BaseModel):
    ok: bool
    model_output: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_output: dict[str, Any] = Field(..., json_schema_extra=exposed_contract("model"))
    market_snapshot: dict[str, Any] = Field(..., json_schema_extra=exposed_contract("market"))
    portfolio_state: dict[str, Any] = Field(..., json_schema_extra=exposed_contract("portfolio"))
    risk_policy: dict[str, Any] = Field(..., json_schema_extra=exposed_contract("policy"))
    evaluated_at: str
    sport_context: Optional[dict[str, Any]] = None


class EdgeAndStakeOutput(BaseModel):
    schema_version: str = "doctore.edge-and-stake.v2"
    decision_id: str
    decision: str
    reason_codes: list[str]
    diagnostics: list[str] = Field(default_factory=list, description="Actionable canonical gate diagnostics; SETTLEMENT_RULES_UNSUPPORTED identifies the supplied rule and required explicit convention. Confirm source evidence and model-domain alignment; never auto-translate rules.")
    no_vig_probability: Optional[float]
    overround: Optional[float] = Field(..., description="Legacy excess fraction: sum(1/decimal_odds)-1. Ambiguous name retained for compatibility; prefer overround_excess or implied_probability_sum.")
    implied_probability_sum: Optional[float] = Field(default=None, description="Booksum B=sum(1/decimal_odds) across the complete outcome set, as a fraction (1.0238 means 102.38%). Not a model probability.")
    overround_excess: Optional[float] = Field(default=None, description="Excess fraction B-1; 0.0238 means 2.38 percentage points above 100%. Not realized profit or theoretical balanced hold.")
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
    placement_status: Optional[str] = None
    logged: bool
    decision_id: str
    approved_stake: Optional[float]
    reason: Optional[str] = None
    log_path: str


class ConfirmPlacementInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    decision_id: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    placement_confirmed: Literal[True]
    actual_stake: float = Field(..., gt=0)
    actual_odds: float = Field(..., gt=1)
    placed_at: str
    bookmaker_reference: str = Field(..., min_length=1)


class ConfirmPlacementOutput(BaseModel):
    confirmed: bool
    idempotent_replay: bool
    decision_id: str
    actual_stake: float
    actual_odds: float
    placement_sha256: str
    policy_warnings: list[str]


class SettlementResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    VOID = "void"
    HALF_WIN = "half_win"
    HALF_LOSS = "half_loss"


class SettlementRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confirmed: Literal[True]
    action: Literal["CORRECT_RESULT", "ADD_CLOSING"]
    request_id: str = Field(..., min_length=1)
    expected_settlement_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(..., min_length=1)
    reviewer: str = Field(..., min_length=1)
    source_reference: str = Field(..., min_length=1)


class SettleBetInput(BaseModel):
    revision: Optional[SettlementRevision] = None
    model_config = ConfigDict(extra="forbid")
    decision_id: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    closing_market_snapshot: Optional[dict[str, Any]] = None
    closing_missing_reason: Optional[str] = Field(default=None, min_length=1)
    result: SettlementResult
    settled_at: Optional[str] = None


class SettleBetOutput(BaseModel):
    settlement_sha256: Optional[str] = None
    audit_sha256: Optional[str] = None
    projection_warning: Optional[str] = None
    settled: bool
    idempotent_replay: bool
    decision_id: str
    closing_odds: Optional[float] = None
    closing_no_vig_probability: Optional[float] = None
    price_clv_pct: Optional[float] = None
    clv_probability_points: Optional[float] = None
    profit_loss: float
    closing_snapshot_sha256: Optional[str] = None
    closing_missing_reason: Optional[str] = None
    closing_snapshot_log_path: str


class PortfolioStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bankroll: float = Field(..., gt=0)


class PortfolioStatusOutput(BaseModel):
    pending_approval_count: int = 0
    approved_unplaced_amount: float = 0
    legacy_unconfirmed_count: int = 0
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
