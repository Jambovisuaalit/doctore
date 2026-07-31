"""Sport-specific context gates for Doctore.

These agents never modify probability, EV, Kelly, stake, or canonical model output.
They return only a gate status plus evidence and reason codes.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


GateStatus = Literal["CLEAR", "WATCH", "BLOCKED", "UNCERTAIN"]


class ContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_ref: str
    observed_at: str
    summary: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ContextGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sport: str
    event_id: str
    market_id: str
    competition: str
    participants: list[str]
    scheduled_start_at: str
    evaluated_at: str
    evidence: list[ContextEvidence] = Field(default_factory=list)
    structured_signals: dict[str, Any] = Field(default_factory=dict)


class ContextGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "doctore.context-gate.v1"
    agent: str
    status: GateStatus
    reason_codes: list[str]
    evidence: list[ContextEvidence]
    notes: list[str] = Field(default_factory=list)


def _require_sport(params: ContextGateInput, expected: str, agent: str) -> ContextGateOutput | None:
    if params.sport.lower() != expected:
        return ContextGateOutput(
            agent=agent,
            status="BLOCKED",
            reason_codes=["CONTEXT_AGENT_SPORT_MISMATCH"],
            evidence=params.evidence,
            notes=[f"expected sport={expected}; received sport={params.sport.lower()}"],
        )
    return None


def evaluate_mlb_context(params: ContextGateInput) -> ContextGateOutput:
    mismatch = _require_sport(params, "mlb", "mlb_context")
    if mismatch:
        return mismatch

    s = params.structured_signals
    reasons: list[str] = []
    status: GateStatus = "CLEAR"

    if s.get("game_status") in {"POSTPONED", "CANCELLED", "SUSPENDED"}:
        return ContextGateOutput(agent="mlb_context", status="BLOCKED", reason_codes=["MLB_GAME_NOT_ACTIVE"], evidence=params.evidence)
    if s.get("market_state") == "IN_PLAY":
        return ContextGateOutput(agent="mlb_context", status="BLOCKED", reason_codes=["MLB_MARKET_IN_PLAY"], evidence=params.evidence)
    if s.get("starting_pitcher_status") in {"SCRATCHED", "UNCONFIRMED"}:
        status = "WATCH"
        reasons.append("MLB_STARTER_UNCONFIRMED_OR_SCRATCHED")
    if s.get("lineup_status") != "CONFIRMED":
        status = "WATCH"
        reasons.append("MLB_LINEUP_NOT_CONFIRMED")
    if s.get("weather_risk") in {"HIGH", "SEVERE"}:
        status = "WATCH"
        reasons.append("MLB_WEATHER_RISK")
    if s.get("roof_status_required") and not s.get("roof_status"):
        status = "UNCERTAIN"
        reasons.append("MLB_ROOF_STATUS_UNKNOWN")
    if not reasons:
        reasons.append("MLB_CONTEXT_CLEAR")

    return ContextGateOutput(agent="mlb_context", status=status, reason_codes=reasons, evidence=params.evidence)


def evaluate_kbo_context(params: ContextGateInput) -> ContextGateOutput:
    mismatch = _require_sport(params, "kbo", "kbo_context")
    if mismatch:
        return mismatch

    s = params.structured_signals
    reasons: list[str] = []
    status: GateStatus = "CLEAR"

    if s.get("game_status") in {"POSTPONED", "CANCELLED", "SUSPENDED"}:
        return ContextGateOutput(agent="kbo_context", status="BLOCKED", reason_codes=["KBO_GAME_NOT_ACTIVE"], evidence=params.evidence)
    if s.get("market_state") == "IN_PLAY":
        return ContextGateOutput(agent="kbo_context", status="BLOCKED", reason_codes=["KBO_MARKET_IN_PLAY"], evidence=params.evidence)
    if s.get("starting_pitcher_status") in {"SCRATCHED", "UNCONFIRMED"}:
        status = "WATCH"
        reasons.append("KBO_STARTER_UNCONFIRMED_OR_SCRATCHED")
    if s.get("lineup_status") != "CONFIRMED":
        status = "WATCH"
        reasons.append("KBO_LINEUP_NOT_CONFIRMED")
    if s.get("weather_risk") in {"HIGH", "SEVERE"}:
        status = "WATCH"
        reasons.append("KBO_WEATHER_RISK")
    if s.get("travel_stress_status") == "UNKNOWN":
        status = "UNCERTAIN"
        reasons.append("KBO_TRAVEL_STRESS_UNKNOWN")
    elif s.get("travel_stress_status") == "HIGH":
        status = "WATCH"
        reasons.append("KBO_HIGH_TRAVEL_STRESS")
    if not reasons:
        reasons.append("KBO_CONTEXT_CLEAR")

    return ContextGateOutput(agent="kbo_context", status=status, reason_codes=reasons, evidence=params.evidence)


def evaluate_tennis_withdrawal_risk(params: ContextGateInput) -> ContextGateOutput:
    mismatch = _require_sport(params, "tennis", "tennis_withdrawal_risk")
    if mismatch:
        return mismatch

    s = params.structured_signals
    reasons: list[str] = []

    if s.get("official_withdrawal") is True:
        return ContextGateOutput(agent="tennis_withdrawal_risk", status="BLOCKED", reason_codes=["TENNIS_OFFICIAL_WITHDRAWAL"], evidence=params.evidence)
    if s.get("recent_retirement") is True:
        reasons.append("TENNIS_RECENT_RETIREMENT")
    if s.get("recent_medical_timeout") is True:
        reasons.append("TENNIS_RECENT_MEDICAL_TIMEOUT")
    if s.get("fitness_statement") in {"NEGATIVE", "LIMITED", "DOUBTFUL"}:
        reasons.append("TENNIS_NEGATIVE_FITNESS_SIGNAL")
    if s.get("late_replacement") is True or s.get("recent_pullout") is True:
        reasons.append("TENNIS_RECENT_PULL_OUT_OR_LATE_REPLACEMENT")
    if s.get("recurring_injury_match") is True:
        reasons.append("TENNIS_RECURRING_INJURY_MATCH")

    if reasons:
        return ContextGateOutput(agent="tennis_withdrawal_risk", status="WATCH", reason_codes=reasons, evidence=params.evidence)
    if s.get("research_complete") is False:
        return ContextGateOutput(agent="tennis_withdrawal_risk", status="UNCERTAIN", reason_codes=["TENNIS_WITHDRAWAL_RESEARCH_INCOMPLETE"], evidence=params.evidence)
    return ContextGateOutput(agent="tennis_withdrawal_risk", status="CLEAR", reason_codes=["TENNIS_NO_WITHDRAWAL_SIGNAL_FOUND"], evidence=params.evidence)


def evaluate_future_context(params: ContextGateInput) -> ContextGateOutput:
    return ContextGateOutput(
        agent=f"{params.sport.lower()}_context",
        status="BLOCKED",
        reason_codes=["CONTEXT_AGENT_NOT_IMPLEMENTED"],
        evidence=params.evidence,
        notes=["NBA and soccer adapters are reserved but intentionally fail closed until implemented and validated."],
    )


def run_context_agent(params: ContextGateInput) -> ContextGateOutput:
    sport = params.sport.lower()
    if sport == "mlb":
        return evaluate_mlb_context(params)
    if sport == "kbo":
        return evaluate_kbo_context(params)
    if sport == "tennis":
        return evaluate_tennis_withdrawal_risk(params)
    if sport in {"nba", "soccer"}:
        return evaluate_future_context(params)
    return ContextGateOutput(
        agent=f"{sport}_context",
        status="BLOCKED",
        reason_codes=["CONTEXT_AGENT_UNSUPPORTED_SPORT"],
        evidence=params.evidence,
    )
