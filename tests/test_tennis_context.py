from __future__ import annotations

import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from bet_decision_core import evaluate_bet_decision
from tennis_context import evaluate_tennis_context, evaluate_tennis_settlement


EVALUATED_AT = "2026-07-25T12:00:00+03:00"
EVENT_ID = "TENNIS-ATP-KITZBUHEL-2026-R16-1001"
MARKET_ID = f"{EVENT_ID}-MATCH-ML-PLAYER-ONE"


def context_market_snapshot() -> dict:
    return {
        "event_id": EVENT_ID,
        "event_start_at": "2026-07-25T14:00:00+03:00",
        "selection": "Player One",
        "outcomes": [
            {"selection": "Player One", "decimal_odds": 1.90},
            {"selection": "Player Two", "decimal_odds": 2.00},
        ],
    }


def tennis_context() -> dict:
    return {
        "schema_version": "doctore.tennis-context.v1",
        "event_id": EVENT_ID,
        "captured_at": "2026-07-25T11:59:00+03:00",
        "scheduled_start_at": "2026-07-25T14:00:00+03:00",
        "sport": "TENNIS",
        "tour": "ATP",
        "tier": "main_tour",
        "market": "match_moneyline",
        "discipline": "singles",
        "draw_stage": "main_draw",
        "match_format": "best_of_3",
        "event_status": "scheduled",
        "players": {
            "player_one": {"player_id": "atp-1001", "name": "Player One"},
            "player_two": {"player_id": "atp-1002", "name": "Player Two"},
        },
        "court": {
            "surface": "clay",
            "surface_status": "confirmed",
            "environment": "outdoor",
            "environment_status": "confirmed",
        },
        "validation_policy": {"retirements": "excluded_from_initial_validation"},
    }


def evaluate_context(context: dict) -> dict:
    return evaluate_tennis_context(
        context,
        market_snapshot=context_market_snapshot(),
        evaluated_at=EVALUATED_AT,
        max_age_seconds=900,
    )


def model_output() -> dict:
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": EVENT_ID,
        "market_id": MARKET_ID,
        "model_name": "doctore-atp-match-moneyline",
        "model_version": "2026.07.25.1",
        "sport": "TENNIS",
        "competition": "ATP",
        "market_type": "moneyline",
        "target_market": "match_moneyline",
        "period": "full_match",
        "line": None,
        "settlement_rules": "void_on_retirement_or_walkover",
        "selection": "Player One",
        "probability_raw": 0.60,
        "probability_calibrated": 0.60,
        "calibration_status": "validated",
        "calibration_method": "sigmoid",
        "prediction_generated_at": "2026-07-25T11:50:00+03:00",
        "feature_cutoff_at": "2026-07-25T11:45:00+03:00",
        "training_cutoff_at": "2026-07-24T23:59:59+03:00",
        "feature_schema_version": "tennis.atp.match-moneyline.v1",
        "validation_domain": {
            "sport": "TENNIS",
            "competition": "ATP",
            "market_type": "moneyline",
            "target_market": "match_moneyline",
            "period": "full_match",
            "line": None,
            "settlement_rules": "void_on_retirement_or_walkover",
        },
        "validation_window": "2024-01-01/2026-07-20",
        "validation_sample_size": 500,
        "brier_score": 0.21,
        "log_loss": 0.61,
        "expected_calibration_error": 0.03,
    }


def canonical_market_snapshot(*, captured_at: str = "2026-07-25T11:59:00+03:00") -> dict:
    return {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": EVENT_ID,
        "market_id": MARKET_ID,
        "book": "Pinnacle",
        "book_market_id": "tennis-1001",
        "captured_at": captured_at,
        "event_start_at": "2026-07-25T14:00:00+03:00",
        "sport": "TENNIS",
        "competition": "ATP",
        "market_type": "moneyline",
        "target_market": "match_moneyline",
        "period": "full_match",
        "line": None,
        "settlement_rules": "void_on_retirement_or_walkover",
        "selection": "Player One",
        "decimal_odds": 1.90,
        "market_status": "open",
        "is_complete": True,
        "outcomes": [
            {"selection": "Player One", "decimal_odds": 1.90},
            {"selection": "Player Two", "decimal_odds": 2.00},
        ],
        "correlation_group": EVENT_ID,
        "source": "synthetic-test",
    }


def portfolio_state() -> dict:
    return {
        "schema_version": "doctore.portfolio-state.v1",
        "portfolio_id": "primary-eur",
        "captured_at": "2026-07-25T11:59:30+03:00",
        "currency": "EUR",
        "bankroll": 50000.0,
        "available_balance": 45000.0,
        "stake_increment": 1.0,
        "league": "ATP",
        "correlation_group": EVENT_ID,
        "drawdown_fraction": 0.02,
        "open_positions_count": 1,
        "exposures": {
            "open_amount": 500.0,
            "daily_turnover_amount": 1000.0,
            "league_amount": 500.0,
            "rolling_3d_turnover_amount": 2000.0,
            "correlation_group_amount": 0.0,
        },
    }


def risk_policy() -> dict:
    return {
        "schema_version": "doctore.risk-policy.v1",
        "policy_id": "doctore-default",
        "policy_version": "2026.07.25",
        "minimum_ev": 0.03,
        "minimum_edge_probability_points": 0.015,
        "minimum_stake": 1.0,
        "allowed_calibration_statuses": ["validated", "uncalibrated"],
        "kelly_fraction": {"validated": 0.25, "uncalibrated": 0.10, "unknown": 0},
        "sizing_model_weight": {"validated": 0.85, "uncalibrated": 0.35, "unknown": 0},
        "caps": {
            "max_stake_fraction_per_bet": 0.02,
            "max_open_exposure_fraction": 0.10,
            "max_daily_turnover_fraction": 0.25,
            "max_league_exposure_fraction": 0.15,
            "max_rolling_3d_turnover_fraction": 0.40,
            "max_correlation_group_fraction": 0.04,
        },
        "freshness_seconds": {
            "market_snapshot": 300,
            "portfolio_state": 60,
            "model_output": 1800,
            "mlb_context": 900,
        },
        "drawdown": {
            "warning_fraction": 0.10,
            "review_fraction": 0.15,
            "pause_fraction": 0.20,
        },
        "human_approval_required": True,
        "block_unknown_correlation": True,
    }


def evaluate_decision(context: dict | None) -> dict:
    return evaluate_bet_decision(
        model_output=model_output(),
        market_snapshot=canonical_market_snapshot(),
        portfolio_state=portfolio_state(),
        risk_policy=risk_policy(),
        evaluated_at=EVALUATED_AT,
        sport_context=context,
    )


class TennisContextTests(unittest.TestCase):
    def test_correct_scope_passes(self) -> None:
        result = evaluate_context(tennis_context())
        self.assertEqual({"status", "reason_codes", "diagnostics"}, set(result))
        self.assertEqual("VALID", result["status"])
        self.assertEqual([], result["reason_codes"])

    def test_wrong_tier_is_rejected(self) -> None:
        context = tennis_context()
        context["tier"] = "challenger"
        result = evaluate_context(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("TENNIS_TIER_MISMATCH", result["reason_codes"])

    def test_best_of_five_is_rejected(self) -> None:
        context = tennis_context()
        context["match_format"] = "best_of_5"
        result = evaluate_context(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("TENNIS_BEST_OF_FIVE_EXCLUDED", result["reason_codes"])

    def test_in_progress_match_is_rejected(self) -> None:
        context = tennis_context()
        context["event_status"] = "in_progress"
        result = evaluate_context(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("EVENT_ALREADY_STARTED", result["reason_codes"])

    def test_retirement_settlement_is_excluded_but_audited(self) -> None:
        result = evaluate_tennis_settlement({"match_status": "retirement"})
        self.assertEqual("void_retirement", result["settlement_status"])
        self.assertTrue(result["exclude_from_clv_aggregation"])
        self.assertTrue(result["exclude_from_brier_aggregation"])
        self.assertTrue(result["keep_in_raw_audit_log"])

    def test_context_only_overrides_after_economics_are_computed(self) -> None:
        valid = evaluate_decision(tennis_context())
        wrong_tier = tennis_context()
        wrong_tier["tier"] = "challenger"
        blocked = evaluate_decision(wrong_tier)

        self.assertEqual("BET", valid["decision"])
        self.assertEqual("BLOCKED", blocked["decision"])
        self.assertIn("TENNIS_TIER_MISMATCH", blocked["reason_codes"])
        self.assertEqual(valid["model"], blocked["model"])
        self.assertEqual(valid["market"], blocked["market"])
        self.assertEqual(valid["economics"], blocked["economics"])
        self.assertIsNotNone(blocked["economics"]["full_kelly"])
        self.assertIsNone(blocked["staking"]["final_stake"])

    def test_missing_tennis_context_is_blocked(self) -> None:
        result = evaluate_decision(None)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("TENNIS_CONTEXT_MISSING", result["reason_codes"])
        self.assertIsNotNone(result["economics"]["ev"])


class TennisSettlementIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous_repo = os.environ.get("DOCTORE_REPO_PATH")
        self.previous_log = os.environ.get("DOCTORE_BET_LOG")
        os.environ["DOCTORE_REPO_PATH"] = str(ROOT)
        os.environ["DOCTORE_BET_LOG"] = str(Path(self.temp.name) / "bets.csv")
        for module_name in list(sys.modules):
            if module_name == "doctore_mcp" or module_name.startswith("doctore_mcp."):
                sys.modules.pop(module_name, None)
        self.ledger = importlib.import_module("doctore_mcp.ledger")
        self.schemas = importlib.import_module("doctore_mcp.schemas")
        self.settlement = importlib.import_module("doctore_mcp.settlement")

    def tearDown(self) -> None:
        for module_name in list(sys.modules):
            if module_name == "doctore_mcp" or module_name.startswith("doctore_mcp."):
                sys.modules.pop(module_name, None)
        if self.previous_repo is None:
            os.environ.pop("DOCTORE_REPO_PATH", None)
        else:
            os.environ["DOCTORE_REPO_PATH"] = self.previous_repo
        if self.previous_log is None:
            os.environ.pop("DOCTORE_BET_LOG", None)
        else:
            os.environ["DOCTORE_BET_LOG"] = self.previous_log
        self.temp.cleanup()

    def test_retirement_is_void_and_excluded_in_real_settlement_path(self) -> None:
        decision_id = "a" * 64
        row = dict.fromkeys(self.ledger.BET_LOG_FIELDS, "")
        row.update({
            "logged_at": "2026-07-25T12:01:00+03:00",
            "decision_id": decision_id,
            "event_id": EVENT_ID,
            "market_id": MARKET_ID,
            "sport": "TENNIS",
            "competition": "ATP",
            "market_type": "moneyline",
            "target_market": "match_moneyline",
            "period": "full_match",
            "line_json": "null",
            "settlement_rules": "void_on_retirement_or_walkover",
            "selection": "Player One",
            "book": "Pinnacle",
            "odds_taken": 1.90,
            "market_no_vig_at_bet": 0.50,
            "recommended_stake": 100.0,
            "approved_stake": 100.0,
            "human_decision": "APPROVE",
            "model_name": "doctore-atp-match-moneyline",
            "model_version": "2026.07.25.1",
            "calibration_status": "validated",
            "ev_at_bet": 0.14,
            "edge_vs_market_pp": 0.10,
        })
        self.ledger.write_bet_rows([row])

        closing = canonical_market_snapshot(captured_at="2026-07-25T13:59:00+03:00")
        result = self.settlement.settle_bet(self.schemas.SettleBetInput(
            decision_id=decision_id,
            closing_market_snapshot=closing,
            result="void",
            tennis_settlement_context={"match_status": "retirement"},
            settled_at="2026-07-25T16:00:00+03:00",
        ))

        self.assertEqual("void_retirement", result.settlement_status)
        self.assertTrue(result.exclude_from_clv_aggregation)
        self.assertTrue(result.exclude_from_brier_aggregation)
        self.assertIsNone(result.price_clv_pct)
        self.assertIsNone(result.clv_probability_points)

        raw_records = self.settlement.closing_records()
        self.assertEqual(1, len(raw_records))
        self.assertEqual("void_retirement", raw_records[0]["settlement_status"])
        self.assertIsNotNone(raw_records[0]["raw_price_clv_pct"])
        self.assertIsNotNone(raw_records[0]["raw_clv_probability_points"])
        self.assertEqual({"match_status": "retirement"}, raw_records[0]["tennis_settlement_context"])

        settled_row = self.ledger.read_bet_rows()[0]
        self.assertEqual("void", settled_row["result"])
        self.assertEqual("", settled_row["price_clv_pct"])
        self.assertEqual("", settled_row["clv_probability_points"])


if __name__ == "__main__":
    unittest.main()
