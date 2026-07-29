"""Personal stdio MCP server for the canonical Doctore decision pipeline.

The implementation lives in focused modules. Re-exports below preserve the
Python import surface used by existing tests and local clients.
"""
from __future__ import annotations

if not __package__:  # direct `python doctore_mcp/server.py`
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doctore_mcp.context_agents import (  # noqa: E402,F401
    ContextEvidence,
    ContextGateInput,
    ContextGateOutput,
)
from doctore_mcp.schemas import (  # noqa: E402,F401
    DecisionInput,
    EdgeAndStakeOutput,
    EvaluateOutput,
    HumanDecision,
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
    SettlementResult,
    Sport,
)
from doctore_mcp.tools import (  # noqa: E402,F401
    doctore_calculate_edge_and_stake,
    doctore_check_data_quality,
    doctore_evaluate_bet,
    doctore_load_model_prediction,
    doctore_log_bet,
    doctore_parse_pinnacle_table,
    doctore_portfolio_status,
    doctore_run_context_gate,
    doctore_settle_bet,
    mcp,
)
from doctore_mcp.slate_tools import doctore_run_slate  # noqa: E402,F401


if __name__ == "__main__":
    mcp.run()
