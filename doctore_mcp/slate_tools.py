"""FastMCP registration for the slate-level orchestrator."""
from __future__ import annotations

from .orchestrator import SlateOrchestrator, SlateRunInput, SlateRunOutput
from .tools import (
    doctore_calculate_edge_and_stake,
    doctore_check_data_quality,
    doctore_evaluate_bet,
    doctore_load_model_prediction,
    doctore_log_bet,
    doctore_parse_pinnacle_table,
    doctore_portfolio_status,
    doctore_settle_bet,
    mcp,
)


@mcp.tool(
    name="doctore_run_slate",
    annotations={
        "title": "Run full Doctore slate",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def doctore_run_slate(params: SlateRunInput) -> SlateRunOutput:
    """Run the existing eight-tool pipeline for a complete slate.

    The tool adds no prediction logic. BET decisions are never logged unless an
    explicit matching human approval is supplied in the request.
    """
    orchestrator = SlateOrchestrator(
        parse_pinnacle_table=doctore_parse_pinnacle_table,
        check_data_quality=doctore_check_data_quality,
        load_model_prediction=doctore_load_model_prediction,
        calculate_edge_and_stake=doctore_calculate_edge_and_stake,
        evaluate_bet=doctore_evaluate_bet,
        log_bet=doctore_log_bet,
        settle_bet=doctore_settle_bet,
        portfolio_status=doctore_portfolio_status,
    )
    return await orchestrator.run(params)
