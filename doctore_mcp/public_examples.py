"""Generate documented synthetic input examples for all 14 public MCP tools.

This module is a PUBLIC contract example, not an independent blind test or a
source of expected answers. It does not call write tools or real providers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json


def build_examples(artifact_dir: Path) -> dict[str, dict]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda dt: dt.isoformat()
    event_id = "SYNTHETIC-WNBA-EXAMPLE-1"
    market_id = event_id + "-moneyline-home"
    domain = dict(sport="WNBA", competition="WNBA", market_type="moneyline",
                  target_market="full_game_moneyline", period="full_game",
                  line=None, settlement_rules="full_game_including_overtime")
    model = dict(schema_version="doctore.model-output.v1", event_id=event_id,
                 market_id=market_id, model_name="synthetic-demonstration",
                 model_version="1.0", **domain, selection="Example Home",
                 probability_raw=0.60, probability_calibrated=0.60,
                 calibration_status="validated", calibration_method="sigmoid",
                 prediction_generated_at=iso(now-timedelta(minutes=15)),
                 feature_cutoff_at=iso(now-timedelta(minutes=20)),
                 training_cutoff_at=iso(now-timedelta(days=30)),
                 feature_schema_version="synthetic.v1",
                 validation_domain=domain.copy(), validation_window="synthetic-only",
                 validation_sample_size=500, brier_score=0.20, log_loss=0.58,
                 expected_calibration_error=0.03)
    market = dict(schema_version="doctore.market-snapshot.v1", event_id=event_id,
                  market_id=market_id, book="Synthetic Book", book_market_id="example-1",
                  captured_at=iso(now-timedelta(seconds=20)),
                  event_start_at=iso(now+timedelta(hours=9)), **domain,
                  selection="Example Home", decimal_odds=1.90,
                  market_status="open", is_complete=True,
                  outcomes=[dict(selection="Example Home", decimal_odds=1.90),
                            dict(selection="Example Away", decimal_odds=1.95)],
                  correlation_group=event_id, source="synthetic-example")
    portfolio = dict(schema_version="doctore.portfolio-state.v1",
                     portfolio_id="synthetic-eur", captured_at=iso(now-timedelta(seconds=10)),
                     currency="EUR", bankroll=50000.0, available_balance=45000.0,
                     stake_increment=1.0, league="WNBA", correlation_group=event_id,
                     drawdown_fraction=0.02, open_positions_count=1,
                     exposures=dict(open_amount=500.0, daily_turnover_amount=1000.0,
                                    league_amount=500.0, rolling_3d_turnover_amount=2000.0,
                                    correlation_group_amount=0.0))
    policy = dict(schema_version="doctore.risk-policy.v1",
                  policy_id="synthetic-research-only", policy_version="1.0",
                  minimum_ev=0.03, minimum_edge_probability_points=0.015,
                  minimum_stake=1.0, allowed_calibration_statuses=["validated", "uncalibrated"],
                  kelly_fraction=dict(validated=0.25, uncalibrated=0.10, unknown=0),
                  sizing_model_weight=dict(validated=0.85, uncalibrated=0.35, unknown=0),
                  caps=dict(max_stake_fraction_per_bet=0.02,
                            max_open_exposure_fraction=0.10,
                            max_daily_turnover_fraction=0.25,
                            max_league_exposure_fraction=0.15,
                            max_rolling_3d_turnover_fraction=0.40,
                            max_correlation_group_fraction=0.04),
                  freshness_seconds=dict(market_snapshot=300, portfolio_state=60,
                                         model_output=1800, mlb_context=900),
                  drawdown=dict(warning_fraction=0.10, review_fraction=0.15,
                                pause_fraction=0.20),
                  human_approval_required=True, block_unknown_correlation=True)
    evaluation = dict(model_output=model, market_snapshot=market,
                      portfolio_state=portfolio, risk_policy=policy,
                      evaluated_at=iso(now), sport_context=None)

    # Only a local synthetic JSON artifact is created. No bet ledger is touched.
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = artifact_dir / "synthetic_prediction.json"
    rich = {
        "output_schema_version": "doctore.probability-prediction.v1",
        "event_id": event_id, "sport": "WNBA",
        "market": dict(market_type="moneyline", period="full_game", line=None,
                       selection="Example Home"),
        "model": dict(model_name=model["model_name"], model_version="1.0",
                      prediction_generated_at=model["prediction_generated_at"],
                      feature_cutoff_at=model["feature_cutoff_at"],
                      training_cutoff_at=model["training_cutoff_at"],
                      feature_schema_version="synthetic.v1",
                      model_artifact_sha256="a"*64),
        "calibration": dict(status="validated", probability_selected_raw=0.60,
                            probability_selected_calibrated=0.60,
                            calibration_artifact_sha256="b"*64),
        "validation": dict(validation_period_start="2025-01-01",
                           validation_period_end="2025-12-31", sample_size=500,
                           model_brier_score=0.20, model_log_loss=0.58,
                           model_ece=0.03),
    }
    prediction_path.write_text(json.dumps(rich, indent=2) + "\n", encoding="utf-8")

    # Build a decision output only to show the required shape for the *write*
    # tool's example. Generating the example never invokes a write tool.
    from doctore_mcp.runtime import REPO  # ensures canonical src import path
    from bet_decision_core import evaluate_bet_decision
    decision = evaluate_bet_decision(**evaluation)
    assert decision["economics"] is not None, "synthetic payload did not reach economics"
    assert decision["economics"]["ev"] is not None, "synthetic payload did not calculate EV"
    assert decision["market"]["no_vig_probability"] is not None, "no-vig not calculated"
    assert decision["decision"] == "BET", "synthetic example must support approval sequence"
    stake = decision["staking"]["final_stake"]
    assert isinstance(stake, (int, float)) and stake > 0

    header = ("away\thome\ttime\tml_away\tml_home\trl_away_label\trl_away_price\t"
              "rl_home_label\trl_home_price\ttotal_line\ttotal_over\ttotal_under\tbtn\thref")
    row = ("Example Away\tExample Home\t20:10\t2.10\t1.80\t+1.5\t1.85\t"
           "-1.5\t2.05\t8.5\t1.91\t1.99\t+10\t"
           "https://www.pinnacle.com/fi/baseball/mlb/1632715441/")
    raw_table = header + "\n" + row
    parse = dict(raw_table=raw_table, sport="mlb", event_date=now.date().isoformat(),
                 timezone_name="Europe/Helsinki", competition="MLB",
                 captured_at=iso(now-timedelta(seconds=20)))
    examples = {
        "doctore_parse_pinnacle_table": parse,
        "doctore_check_data_quality": dict(snapshot_at=iso(now-timedelta(seconds=20)),
                                           reference_odds={"home": 1.90},
                                           current_odds={"home": 1.91}),
        "doctore_load_model_prediction": dict(prediction_path=str(prediction_path),
                                              market_id=market_id, competition="WNBA",
                                              target_market="full_game_moneyline",
                                              settlement_rules="full_game_including_overtime"),
        "doctore_calculate_edge_and_stake": evaluation,
        "doctore_evaluate_bet": evaluation,
        "doctore_run_context_gate": dict(sport="wnba", event_id=event_id,
                                         market_id=market_id, competition="WNBA",
                                         participants=["Example Home", "Example Away"],
                                         scheduled_start_at=market["event_start_at"],
                                         evaluated_at=iso(now), evidence=[]),
        "doctore_log_bet": dict(evaluation=evaluation, decision_output=decision,
                                human_decision="APPROVE", approved_stake=None),
        "doctore_confirm_placement": dict(decision_id=decision["decision_id"],
                                           placement_confirmed=True, actual_stake=stake,
                                           actual_odds=1.90, placed_at=iso(now),
                                           bookmaker_reference="synthetic-receipt-1"),
        "doctore_settle_bet": dict(decision_id=decision["decision_id"], result="win",
                                   settled_at=iso(now+timedelta(hours=11)),
                                   closing_missing_reason="synthetic-no-closing-data"),
        "doctore_portfolio_status": dict(bankroll=50000.0),
        "doctore_run_slate": dict(**parse, bankroll=50000.0,
                                   portfolio_state=portfolio, risk_policy=policy,
                                   markets=[dict(market_id="synthetic-unmatched",
                                                 prediction_path=str(prediction_path),
                                                 competition="MLB",
                                                 target_market="full_game_moneyline",
                                                 market_snapshot={})],
                                   approvals=[], evaluated_at=iso(now)),
        "doctore_tennis_data": dict(command="get_capabilities", tour="atp"),
        "doctore_scan_nhl_totals": dict(evaluated_at=iso(now),
                                        rows=[dict(canonical_event_id="nhl:2026020177",
                                                   book="Synthetic Book",
                                                   source_observed_at=iso(now))]),
        "doctore_collect_nhl_totals": dict(regions="eu,us",
                                           target_event_pairs=["Anaheim Ducks|Ottawa Senators"]),
    }
    assert len(examples) == 14
    return examples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_examples(args.artifact_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
