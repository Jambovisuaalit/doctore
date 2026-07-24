#!/usr/bin/env python3
"""Run all Doctore tools through MCP Inspector CLI over stdio."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

INSPECTOR_PACKAGE = "@modelcontextprotocol/inspector@0.21.2"
EXPECTED_TOOLS = {
    "doctore_parse_pinnacle_table",
    "doctore_check_data_quality",
    "doctore_load_model_prediction",
    "doctore_calculate_edge_and_stake",
    "doctore_evaluate_bet",
    "doctore_log_bet",
    "doctore_settle_bet",
    "doctore_portfolio_status",
}


def _run(base: list[str], *, method: str, tool: str | None = None, params: dict | None = None) -> str:
    command = [*base, "--method", method]
    if tool is not None:
        command.extend(["--tool-name", tool])
    if params is not None:
        command.extend([
            "--tool-arg",
            "params=" + json.dumps(params, separators=(",", ":")),
        ])
    completed = subprocess.run(command, text=True, capture_output=True, timeout=180)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"Inspector failed for {tool or method}:\n{output}")
    print(f"PASS {tool or method}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    repo = args.repo.resolve()
    fixtures = runpy.run_path(str(repo / "tests" / "test_doctore_mcp.py"))
    model = fixtures["model_output"]()
    market = fixtures["market_snapshot"]()
    portfolio = fixtures["portfolio_state"]()
    policy = fixtures["risk_policy"]()
    evaluated_at = "2026-07-24T11:00:00+03:00"
    evaluation = {
        "model_output": model,
        "market_snapshot": market,
        "portfolio_state": portfolio,
        "risk_policy": policy,
        "evaluated_at": evaluated_at,
        "sport_context": None,
    }
    sys.path.insert(0, str(repo / "src"))
    from bet_decision_core import evaluate_bet_decision
    decision = evaluate_bet_decision(
        model_output=model,
        market_snapshot=market,
        portfolio_state=portfolio,
        risk_policy=policy,
        evaluated_at=evaluated_at,
        sport_context=None,
    )

    rich_prediction = {
        "output_schema_version": "doctore.probability-prediction.v1",
        "event_id": model["event_id"],
        "sport": model["sport"],
        "market": {
            "market_type": model["market_type"],
            "period": model["period"],
            "line": model["line"],
            "selection": model["selection"],
        },
        "model": {
            "model_name": model["model_name"],
            "model_version": model["model_version"],
            "prediction_generated_at": model["prediction_generated_at"],
            "feature_cutoff_at": model["feature_cutoff_at"],
            "training_cutoff_at": model["training_cutoff_at"],
            "feature_schema_version": model["feature_schema_version"],
            "model_artifact_sha256": "a" * 64,
        },
        "calibration": {
            "status": "validated",
            "probability_selected_raw": model["probability_raw"],
            "probability_selected_calibrated": model["probability_calibrated"],
            "calibration_artifact_sha256": "b" * 64,
        },
        "validation": {
            "validation_period_start": "2025-05-01",
            "validation_period_end": "2026-07-20",
            "sample_size": model["validation_sample_size"],
            "model_brier_score": model["brier_score"],
            "model_log_loss": model["log_loss"],
            "model_ece": model["expected_calibration_error"],
        },
    }

    with tempfile.TemporaryDirectory(prefix="doctore-inspector-") as temp_dir:
        temp = Path(temp_dir)
        bet_log = temp / "bet_log.csv"
        prediction_path = temp / "prediction.json"
        prediction_path.write_text(json.dumps(rich_prediction), encoding="utf-8")
        server_path = repo / "doctore_mcp" / "server.py"
        base = [
            "npx", "--yes", INSPECTOR_PACKAGE, "--cli",
            "-e", f"DOCTORE_REPO_PATH={repo}",
            "-e", f"DOCTORE_BET_LOG={bet_log}",
            args.python, str(server_path),
        ]

        listed = _run(base, method="tools/list")
        missing = sorted(name for name in EXPECTED_TOOLS if name not in listed)
        if missing:
            raise RuntimeError("Inspector tools/list omitted: " + ", ".join(missing))

        raw_table = (
            "away\thome\ttime\tml_away\tml_home\trl_away_label\trl_away_price\t"
            "rl_home_label\trl_home_price\ttotal_line\ttotal_over\ttotal_under\tbtn\thref\n"
            "Minnesota Twins\tCleveland Guardians\t20:10\t2.10\t1.80\t+1.5\t1.85\t"
            "-1.5\t2.05\t8.5\t1.91\t1.99\t+10\t"
            "https://www.pinnacle.com/fi/baseball/mlb/1632715441/"
        )
        _run(base, method="tools/call", tool="doctore_parse_pinnacle_table", params={
            "raw_table": raw_table,
            "sport": "mlb",
            "event_date": "2026-07-24",
            "timezone_name": "Europe/Helsinki",
            "captured_at": "2026-07-24T10:00:00+03:00",
        })
        _run(base, method="tools/call", tool="doctore_check_data_quality", params={
            "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_odds": {"Minnesota": 2.28},
            "current_odds": {"Minnesota": 2.08},
            "contradiction_threshold_pct": 5.0,
        })
        _run(base, method="tools/call", tool="doctore_load_model_prediction", params={
            "prediction_path": str(prediction_path),
            "market_id": model["market_id"],
            "competition": model["competition"],
            "target_market": model["target_market"],
            "settlement_rules": model["settlement_rules"],
        })
        _run(base, method="tools/call", tool="doctore_calculate_edge_and_stake", params=evaluation)
        _run(base, method="tools/call", tool="doctore_evaluate_bet", params=evaluation)
        _run(base, method="tools/call", tool="doctore_log_bet", params={
            "evaluation": evaluation,
            "decision_output": decision,
            "human_decision": "APPROVE",
            "approved_stake": None,
        })
        closing = fixtures["market_snapshot"](
            odds=1.80,
            captured_at="2026-07-24T19:59:00+03:00",
        )
        _run(base, method="tools/call", tool="doctore_settle_bet", params={
            "decision_id": decision["decision_id"],
            "closing_market_snapshot": closing,
            "result": "win",
            "settled_at": "2026-07-24T22:00:00+03:00",
        })
        _run(base, method="tools/call", tool="doctore_portfolio_status", params={
            "bankroll": 50000,
        })
        print(f"Inspector smoke suite passed: {len(EXPECTED_TOOLS)}/{len(EXPECTED_TOOLS)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
