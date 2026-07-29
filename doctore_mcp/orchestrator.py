"""Deterministic slate-level orchestration over the existing eight MCP tools.

This module adds no prediction logic. It sequences the canonical parser,
quality gate, model loader, decision core, portfolio read, human approval,
logging and settlement interfaces already exposed by doctore_mcp.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from .governance import (
    append_decision_bundle,
    build_decision_bundle,
    runtime_provenance,
    validate_market_governance,
)
from .runtime import content_sha256
from .schemas import (
    DecisionInput,
    HumanDecision,
    LoadPredictionInput,
    LogBetInput,
    ParsePinnacleInput,
    PortfolioStatusInput,
    QualityGateInput,
)


class SlateMarketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_id: str
    prediction_path: str
    competition: str
    target_market: str
    market_snapshot: dict[str, Any]
    reference_odds: Optional[dict[str, float]] = None
    current_odds: Optional[dict[str, float]] = None
    sport_context: Optional[dict[str, Any]] = None


class SlateApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    human_decision: HumanDecision
    approved_stake: Optional[float] = Field(default=None, gt=0)


class SlateRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_table: str
    sport: str
    event_date: str
    captured_at: str
    timezone_name: str = "Europe/Helsinki"
    competition: Optional[str] = None
    bankroll: float = Field(..., gt=0)
    portfolio_state: dict[str, Any]
    risk_policy: dict[str, Any]
    markets: list[SlateMarketInput]
    approvals: list[SlateApprovalInput] = Field(default_factory=list)
    max_age_minutes: Optional[float] = Field(default=None, gt=0)
    contradiction_threshold_pct: float = Field(default=5.0, ge=0)
    evaluated_at: Optional[str] = None


class SlateItemResult(BaseModel):
    schema_version: str = "doctore.slate-item.v2"
    market_id: str
    status: str
    reason_codes: list[str]
    parser_snapshot_found: bool
    governance: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    model: Optional[dict[str, Any]] = None
    edge_and_stake: Optional[dict[str, Any]] = None
    evaluation: Optional[dict[str, Any]] = None
    approval: Optional[dict[str, Any]] = None
    log_result: Optional[dict[str, Any]] = None
    decision_bundle: Optional[dict[str, Any]] = None


class SlateRunOutput(BaseModel):
    schema_version: str = "doctore.slate-run.v2"
    run_id: str
    run_status: str
    generated_at: str
    runtime_provenance: dict[str, Any]
    parser: dict[str, Any]
    portfolio_before: dict[str, Any]
    items: list[SlateItemResult]
    summary: dict[str, int]
    human_approval_required: bool


Tool = Callable[..., Awaitable[Any]]


class SlateOrchestrator:
    """Sequence existing MCP tools without modifying canonical calculations."""

    def __init__(
        self,
        *,
        parse_pinnacle_table: Tool,
        check_data_quality: Tool,
        load_model_prediction: Tool,
        calculate_edge_and_stake: Tool,
        evaluate_bet: Tool,
        log_bet: Tool,
        settle_bet: Tool,
        portfolio_status: Tool,
    ) -> None:
        self.parse_pinnacle_table = parse_pinnacle_table
        self.check_data_quality = check_data_quality
        self.load_model_prediction = load_model_prediction
        self.calculate_edge_and_stake = calculate_edge_and_stake
        self.evaluate_bet = evaluate_bet
        self.log_bet = log_bet
        self.settle_bet = settle_bet
        self.portfolio_status = portfolio_status

    async def run(self, params: SlateRunInput) -> SlateRunOutput:
        evaluated_at = params.evaluated_at or datetime.now(timezone.utc).isoformat()
        run_id = content_sha256(
            {
                "sport": params.sport,
                "event_date": params.event_date,
                "captured_at": params.captured_at,
                "evaluated_at": evaluated_at,
                "market_ids": [market.market_id for market in params.markets],
            }
        )
        approvals = {item.decision_id: item for item in params.approvals}
        provenance = runtime_provenance()

        parser_output = await self.parse_pinnacle_table(
            ParsePinnacleInput(
                raw_table=params.raw_table,
                sport=params.sport,
                event_date=params.event_date,
                timezone_name=params.timezone_name,
                competition=params.competition,
                captured_at=params.captured_at,
            )
        )
        portfolio_output = await self.portfolio_status(
            PortfolioStatusInput(bankroll=params.bankroll)
        )

        parser_dict = parser_output.model_dump(mode="json")
        portfolio_dict = portfolio_output.model_dump(mode="json")
        parser_market_ids = {
            str(snapshot.get("market_id"))
            for snapshot in parser_dict.get("snapshots", [])
            if snapshot.get("market_id") is not None
        }

        results: list[SlateItemResult] = []
        for market in params.markets:
            parser_snapshot_found = market.market_id in parser_market_ids
            if not parser_snapshot_found:
                results.append(
                    SlateItemResult(
                        market_id=market.market_id,
                        status="REJECTED",
                        reason_codes=["SLATE_MARKET_NOT_IN_PARSED_INPUT"],
                        parser_snapshot_found=False,
                    )
                )
                continue

            governance_result = validate_market_governance(
                prediction_path=market.prediction_path,
                sport=params.sport,
                competition=market.competition,
                target_market=market.target_market,
                market_snapshot=market.market_snapshot,
            )
            if not governance_result.ok:
                results.append(
                    SlateItemResult(
                        market_id=market.market_id,
                        status="REJECTED",
                        reason_codes=governance_result.reason_codes,
                        parser_snapshot_found=True,
                        governance=governance_result.governance,
                    )
                )
                continue

            quality_output = await self.check_data_quality(
                QualityGateInput(
                    snapshot_at=params.captured_at,
                    max_age_minutes=params.max_age_minutes,
                    reference_odds=market.reference_odds,
                    current_odds=market.current_odds,
                    contradiction_threshold_pct=params.contradiction_threshold_pct,
                )
            )
            quality_dict = quality_output.model_dump(mode="json")
            quality_status = str(quality_dict.get("status", "")).upper()
            if quality_status not in {"PASS", "OK", "ACCEPT"}:
                reasons = [str(reason) for reason in quality_dict.get("reasons", [])]
                results.append(
                    SlateItemResult(
                        market_id=market.market_id,
                        status="REJECTED",
                        reason_codes=reasons or ["DATA_QUALITY_GATE_FAILED"],
                        parser_snapshot_found=True,
                        governance=governance_result.governance,
                        quality=quality_dict,
                    )
                )
                continue

            model_output = await self.load_model_prediction(
                LoadPredictionInput(
                    prediction_path=market.prediction_path,
                    market_id=market.market_id,
                    competition=market.competition,
                    target_market=market.target_market,
                )
            )
            model_dict = model_output.model_dump(mode="json")
            if not model_dict.get("ok") or not model_dict.get("model_output"):
                results.append(
                    SlateItemResult(
                        market_id=market.market_id,
                        status="REJECTED",
                        reason_codes=["MODEL_PREDICTION_LOAD_FAILED"],
                        parser_snapshot_found=True,
                        governance=governance_result.governance,
                        quality=quality_dict,
                        model=model_dict,
                    )
                )
                continue

            decision_input = DecisionInput(
                model_output=model_dict["model_output"],
                market_snapshot=market.market_snapshot,
                portfolio_state=params.portfolio_state,
                risk_policy=params.risk_policy,
                evaluated_at=evaluated_at,
                sport_context=market.sport_context,
            )
            edge_output = await self.calculate_edge_and_stake(decision_input)
            evaluation_output = await self.evaluate_bet(decision_input)
            edge_dict = edge_output.model_dump(mode="json")
            evaluation_dict = evaluation_output.model_dump(mode="json")
            decision_output = evaluation_dict.get("decision_output", {})
            decision = str(decision_output.get("decision", "REJECTED")).upper()
            reason_codes = [
                str(code)
                for code in decision_output.get(
                    "reason_codes", edge_dict.get("reason_codes", [])
                )
            ]

            item = SlateItemResult(
                market_id=market.market_id,
                status=decision,
                reason_codes=reason_codes,
                parser_snapshot_found=True,
                governance=governance_result.governance,
                quality=quality_dict,
                model=model_dict,
                edge_and_stake=edge_dict,
                evaluation=evaluation_dict,
            )

            decision_id = str(decision_output.get("decision_id", edge_dict.get("decision_id", "")))
            approval = approvals.get(decision_id)
            if decision == "BET":
                if approval is None:
                    item.status = "AWAITING_HUMAN_APPROVAL"
                    item.reason_codes = [*reason_codes, "HUMAN_APPROVAL_REQUIRED"]
                elif approval.human_decision == HumanDecision.REJECT:
                    item.status = "HUMAN_REJECTED"
                    item.approval = approval.model_dump(mode="json")
                    item.reason_codes = [*reason_codes, "HUMAN_REJECTED"]
                else:
                    log_output = await self.log_bet(
                        LogBetInput(
                            evaluation=decision_input,
                            decision_output=decision_output,
                            human_decision=approval.human_decision,
                            approved_stake=approval.approved_stake,
                        )
                    )
                    item.approval = approval.model_dump(mode="json")
                    item.log_result = log_output.model_dump(mode="json")
                    item.status = "LOGGED" if item.log_result.get("logged") else "LOG_REJECTED"
                    if not item.log_result.get("logged"):
                        item.reason_codes = [
                            *reason_codes,
                            str(item.log_result.get("reason") or "LOGGING_REJECTED"),
                        ]

            bundle = build_decision_bundle(
                run_id=run_id,
                decision_input=decision_input.model_dump(mode="json"),
                decision_output=decision_output,
                governance=governance_result.governance,
                approval=item.approval,
                log_result=item.log_result,
            )
            append_decision_bundle(bundle)
            item.decision_bundle = {
                "schema_version": bundle["schema_version"],
                "bundle_sha256": bundle["bundle_sha256"],
            }
            results.append(item)

        summary: dict[str, int] = {}
        for item in results:
            summary[item.status] = summary.get(item.status, 0) + 1

        return SlateRunOutput(
            run_id=run_id,
            run_status="COMPLETED",
            generated_at=datetime.now(timezone.utc).isoformat(),
            runtime_provenance=provenance,
            parser=parser_dict,
            portfolio_before=portfolio_dict,
            items=results,
            summary=summary,
            human_approval_required=any(
                item.status == "AWAITING_HUMAN_APPROVAL" for item in results
            ),
        )
