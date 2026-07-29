"""FastMCP tool registration for the Doctore personal research server."""
from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from .context_agents import ContextGateInput, ContextGateOutput, run_context_agent
from .decision_adapter import (
    calculate_edge_and_stake,
    check_data_quality,
    evaluate,
    load_model_prediction,
)
from .ledger import log_bet, portfolio_status
from .pinnacle_parser import parse_pinnacle_table
from .runtime import parse_time
from .schemas import (
    DecisionInput,
    EdgeAndStakeOutput,
    EvaluateOutput,
    LoadPredictionInput,
    LoadPredictionOutput,
    LogBetInput,
    LogBetOutput,
    ParsePinnacleInput,
    ParsePinnacleOutput,
    PortfolioStatusInput,
    PortfolioStatusOutput,
    QualityGateInput,
    QualityGateOutput,
    SettleBetInput,
    SettleBetOutput,
)
from .settlement import settle_bet

mcp = FastMCP("doctore_mcp")


@mcp.tool(name="doctore_parse_pinnacle_table", annotations={"title": "Parse Pinnacle table", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_parse_pinnacle_table(params: ParsePinnacleInput) -> ParsePinnacleOutput:
    """Parse a copied Pinnacle table into canonical selected-side market snapshots."""
    snapshots, diagnostics = parse_pinnacle_table(
        params.raw_table, params.sport.value, event_date=params.event_date,
        captured_at=parse_time(params.captured_at), timezone_name=params.timezone_name,
        competition=params.competition,
    )
    serialized = [
        {"row_number": item.row_number, "status": item.status, "reason": item.reason, "raw_row": item.raw_row}
        for item in diagnostics
    ]
    return ParsePinnacleOutput(
        parsed_game_count=sum(item.status == "PARSED" for item in diagnostics),
        snapshot_count=len(snapshots), rejected_row_count=sum(item.status == "REJECTED" for item in diagnostics),
        skipped_row_count=sum(item.status == "SKIPPED" for item in diagnostics),
        snapshots=snapshots, diagnostics=serialized,
    )


@mcp.tool(name="doctore_check_data_quality", annotations={"title": "Check data freshness and contradictions", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_check_data_quality(params: QualityGateInput) -> QualityGateOutput:
    """Block stale, future-dated, malformed, or materially contradictory odds data."""
    return check_data_quality(params)


@mcp.tool(name="doctore_load_model_prediction", annotations={"title": "Load canonical model prediction", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_load_model_prediction(params: LoadPredictionInput) -> LoadPredictionOutput:
    """Load a versioned prediction artifact and adapt it to doctore.model-output.v1."""
    return load_model_prediction(params)


@mcp.tool(name="doctore_calculate_edge_and_stake", annotations={"title": "Calculate canonical no-vig, EV and stake", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_calculate_edge_and_stake(params: DecisionInput) -> EdgeAndStakeOutput:
    """Delegate no-vig, EV, edge, Kelly and caps to src/bet_decision_core.py."""
    return calculate_edge_and_stake(params)


@mcp.tool(name="doctore_evaluate_bet", annotations={"title": "Evaluate canonical bet decision", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_evaluate_bet(params: DecisionInput, ctx: Context | None = None) -> EvaluateOutput:
    """Run exact-domain validation, no-vig, economics and risk through the canonical core."""
    if ctx is not None:
        try:
            await ctx.report_progress(0.2, "Validating canonical inputs")
        except (RuntimeError, ValueError):
            pass
    result = evaluate(params)
    if ctx is not None:
        try:
            await ctx.report_progress(1.0, "Decision complete")
        except (RuntimeError, ValueError):
            pass
    return result


@mcp.tool(name="doctore_run_context_gate", annotations={"title": "Run sport-specific context gate", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def doctore_run_context_gate(params: ContextGateInput) -> ContextGateOutput:
    """Return only CLEAR/WATCH/BLOCKED/UNCERTAIN plus evidence; never modify probability or stake."""
    return run_context_agent(params)


@mcp.tool(name="doctore_log_bet", annotations={"title": "Log a human-approved canonical bet", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
async def doctore_log_bet(params: LogBetInput) -> LogBetOutput:
    """Log only a canonical BET decision; approval may reduce but never increase stake."""
    return log_bet(params)


@mcp.tool(name="doctore_settle_bet", annotations={"title": "Settle bet with closing-line snapshot", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_settle_bet(params: SettleBetInput) -> SettleBetOutput:
    """Settle one logged decision and append a content-addressed closing snapshot."""
    return settle_bet(params)


@mcp.tool(name="doctore_portfolio_status", annotations={"title": "Read portfolio exposure and settlement metrics", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def doctore_portfolio_status(params: PortfolioStatusInput) -> PortfolioStatusOutput:
    """Calculate open exposure, realized P/L, win rate and CLV from the canonical log."""
    return portfolio_status(params)
