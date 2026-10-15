from __future__ import annotations

import asyncio
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def model_output(probability: float = 0.60) -> dict:
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": "WNBA-2026-07-24-MIN-NYL-1001",
        "market_id": "WNBA-2026-07-24-MIN-NYL-1001-moneyline-minnesota-lynx-pk",
        "model_name": "doctore-wnba-moneyline",
        "model_version": "2026.07.24.1",
        "sport": "WNBA",
        "competition": "WNBA",
        "market_type": "moneyline",
        "target_market": "full_game_moneyline",
        "period": "full_game",
        "line": None,
        "settlement_rules": "full_game_including_overtime",
        "selection": "Minnesota Lynx",
        "probability_raw": probability,
        "probability_calibrated": probability,
        "calibration_status": "validated",
        "calibration_method": "sigmoid",
        "prediction_generated_at": "2026-07-24T10:45:00+03:00",
        "feature_cutoff_at": "2026-07-24T10:40:00+03:00",
        "training_cutoff_at": "2026-07-23T23:59:59+03:00",
        "feature_schema_version": "wnba.moneyline.v1",
        "validation_domain": {
            "sport": "WNBA",
            "competition": "WNBA",
            "market_type": "moneyline",
            "target_market": "full_game_moneyline",
            "period": "full_game",
            "line": None,
            "settlement_rules": "full_game_including_overtime",
        },
        "validation_window": "2025-05-01/2026-07-20",
        "validation_sample_size": 500,
        "brier_score": 0.20,
        "log_loss": 0.58,
        "expected_calibration_error": 0.03,
    }


def market_snapshot(odds: float = 1.90, captured_at: str = "2026-07-24T10:59:00+03:00") -> dict:
    return {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": "WNBA-2026-07-24-MIN-NYL-1001",
        "market_id": "WNBA-2026-07-24-MIN-NYL-1001-moneyline-minnesota-lynx-pk",
        "book": "Pinnacle",
        "book_market_id": "1001",
        "captured_at": captured_at,
        "event_start_at": "2026-07-24T20:00:00+03:00",
        "sport": "WNBA",
        "competition": "WNBA",
        "market_type": "moneyline",
        "target_market": "full_game_moneyline",
        "period": "full_game",
        "line": None,
        "settlement_rules": "full_game_including_overtime",
        "selection": "Minnesota Lynx",
        "decimal_odds": odds,
        "market_status": "open",
        "is_complete": True,
        "outcomes": [
            {"selection": "Minnesota Lynx", "decimal_odds": odds},
            {"selection": "New York Liberty", "decimal_odds": 1.95},
        ],
        "correlation_group": "WNBA-2026-07-24-MIN-NYL-1001",
        "source": "test",
    }


def portfolio_state() -> dict:
    return {
        "schema_version": "doctore.portfolio-state.v1",
        "portfolio_id": "primary-eur",
        "captured_at": "2026-07-24T10:59:30+03:00",
        "currency": "EUR",
        "bankroll": 50000.0,
        "available_balance": 45000.0,
        "stake_increment": 1.0,
        "league": "WNBA",
        "correlation_group": "WNBA-2026-07-24-MIN-NYL-1001",
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
        "policy_version": "2026.07.24",
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


class ParserTests(unittest.TestCase):
    def test_header_spread_line_and_doubleheader_identity(self) -> None:
        from doctore_mcp.pinnacle_parser import BASEBALL_SCHEMA, parse_pinnacle_table
        raw = "\t".join(BASEBALL_SCHEMA) + "\n" + "\n".join([
            "Away\tHome\t18:00\t2.10\t1.80\t+1.5\t1.85\t-1.5\t2.05\t8.5\t1.91\t1.99\t+10\thttps://www.pinnacle.com/a/1632715441/",
            "Away\tHome\t18:00\t2.20\t1.75\t+1.5\t1.90\t-1.5\t2.00\t8.0\t1.95\t1.95\t+10\thttps://www.pinnacle.com/a/1632715442/",
        ])
        from datetime import date, datetime, timezone
        snapshots, diagnostics = parse_pinnacle_table(
            raw,
            "mlb",
            event_date=date(2026, 7, 24),
            captured_at=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(12, len(snapshots))
        self.assertEqual(2, len({item["event_id"] for item in snapshots}))
        self.assertEqual(1, sum(item.status == "SKIPPED" for item in diagnostics))
        lines = {item["line"] for item in snapshots if item["market_type"] == "run_line"}
        self.assertEqual({1.5, -1.5}, lines)


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["DOCTORE_REPO_PATH"] = str(ROOT)
        os.environ["DOCTORE_BET_LOG"] = str(Path(self.temp.name) / "bets.csv")
        for module_name in list(sys.modules):
            if module_name == "doctore_mcp.server" or module_name.startswith("doctore_mcp."):
                sys.modules.pop(module_name, None)
        self.server = importlib.import_module("doctore_mcp.server")
        self.evaluation = self.server.DecisionInput(
            model_output=model_output(),
            market_snapshot=market_snapshot(),
            portfolio_state=portfolio_state(),
            risk_policy=risk_policy(),
            evaluated_at="2026-07-24T11:00:00+03:00",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pass_has_zero_recommended_stake(self) -> None:
        params = self.evaluation.model_copy(deep=True)
        params.model_output["probability_raw"] = 0.45
        params.model_output["probability_calibrated"] = 0.45
        result = asyncio.run(self.server.doctore_calculate_edge_and_stake(params))
        self.assertEqual("PASS", result.decision)
        self.assertEqual(0.0, result.recommended_stake)
        self.assertIsNone(result.staking["final_stake"])

    def test_exact_domain_mismatch_is_blocked(self) -> None:
        params = self.evaluation.model_copy(deep=True)
        params.market_snapshot["line"] = 1.5
        result = asyncio.run(self.server.doctore_evaluate_bet(params))
        self.assertEqual("BLOCKED", result.decision_output["decision"])
        self.assertIn("DOMAIN_MISMATCH", result.decision_output["reason_codes"])
        self.assertEqual(0.0, result.recommended_stake)

    def test_log_recomputes_decision_and_prevents_stake_increase(self) -> None:
        evaluated = asyncio.run(self.server.doctore_evaluate_bet(self.evaluation))
        decision = evaluated.decision_output
        too_large = self.server.LogBetInput(
            evaluation=self.evaluation,
            decision_output=decision,
            human_decision="REDUCE",
            approved_stake=evaluated.recommended_stake + 1,
        )
        rejected = asyncio.run(self.server.doctore_log_bet(too_large))
        self.assertFalse(rejected.logged)

        valid = self.server.LogBetInput(
            evaluation=self.evaluation,
            decision_output=decision,
            human_decision="APPROVE",
        )
        logged = asyncio.run(self.server.doctore_log_bet(valid))
        self.assertTrue(logged.logged)
        duplicate = asyncio.run(self.server.doctore_log_bet(valid))
        self.assertFalse(duplicate.logged)
        self.assertIn("already logged", duplicate.reason)

    def confirm_fixture_bet(self, logged, **overrides):
        params = dict(decision_id=logged.decision_id, placement_confirmed=True,
                      actual_stake=logged.approved_stake, actual_odds=1.90,
                      placed_at="2026-07-24T11:01:00+03:00", bookmaker_reference="fixture-receipt-1")
        params.update(overrides)
        return asyncio.run(self.server.doctore_confirm_placement(self.server.ConfirmPlacementInput(**params)))

    def log_fixture_bet(self, confirm=True):
        evaluated = asyncio.run(self.server.doctore_evaluate_bet(self.evaluation))
        logged = asyncio.run(self.server.doctore_log_bet(self.server.LogBetInput(
            evaluation=self.evaluation, decision_output=evaluated.decision_output,
            human_decision="APPROVE",
        )))
        if confirm:
            self.confirm_fixture_bet(logged)
        return logged

    def test_approval_does_not_imply_placement_or_exposure(self):
        logged = self.log_fixture_bet(confirm=False)
        portfolio = asyncio.run(self.server.doctore_portfolio_status(
            self.server.PortfolioStatusInput(bankroll=50000)))
        self.assertEqual(1, portfolio.pending_approval_count)
        self.assertEqual(0, portfolio.open_bet_count)
        self.assertEqual(0, portfolio.open_exposure)
        self.assertEqual(logged.approved_stake, portfolio.approved_unplaced_amount)
        with self.assertRaisesRegex(ValueError, "placement must be confirmed"):
            asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
                decision_id=logged.decision_id, result="win", closing_missing_reason="Unavailable",
                settled_at="2026-07-24T22:00:00+03:00")))

    def test_actual_values_drive_exposure_pnl_and_policy_warnings(self):
        logged = self.log_fixture_bet(confirm=False)
        actual = logged.approved_stake + 10
        placed = self.confirm_fixture_bet(logged, actual_stake=actual, actual_odds=1.80,
                                          placed_at="2026-07-24T11:10:00+03:00")
        self.assertIn("ACTUAL_STAKE_EXCEEDS_APPROVAL", placed.policy_warnings)
        self.assertIn("ACTUAL_ODDS_BELOW_APPROVAL", placed.policy_warnings)
        self.assertIn("APPROVED_PRICE_EXPIRED_AT_PLACEMENT", placed.policy_warnings)
        portfolio = asyncio.run(self.server.doctore_portfolio_status(
            self.server.PortfolioStatusInput(bankroll=50000)))
        self.assertEqual(actual, portfolio.open_exposure)
        self.assertEqual(0, portfolio.pending_approval_count)
        settled = asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
            decision_id=logged.decision_id, result="win", closing_missing_reason="Unavailable",
            settled_at="2026-07-24T22:00:00+03:00")))
        self.assertAlmostEqual(round(actual * 0.8, 2), settled.profit_loss)

    def test_placement_replay_is_idempotent_and_changed_facts_rejected(self):
        logged = self.log_fixture_bet(confirm=False)
        self.assertFalse(self.confirm_fixture_bet(logged).idempotent_replay)
        self.assertTrue(self.confirm_fixture_bet(logged).idempotent_replay)
        with self.assertRaisesRegex(ValueError, "different facts"):
            self.confirm_fixture_bet(logged, actual_odds=1.80)

    def test_placement_requires_explicit_confirmation_and_finite_numbers(self):
        from pydantic import ValidationError
        for overrides in ({"placement_confirmed": False}, {"actual_stake": float("inf")},
                          {"actual_odds": float("nan")}, {"bookmaker_reference": " "}):
            logged = type("Logged", (), {"decision_id": "a" * 64, "approved_stake": 10})()
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.confirm_fixture_bet(logged, **overrides)

    def test_placement_journal_recovers_after_state_write_failure(self):
        from unittest.mock import patch
        logged = self.log_fixture_bet(confirm=False)
        ledger = importlib.import_module("doctore_mcp.ledger")
        with patch.object(ledger, "write_bet_rows", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.confirm_fixture_bet(logged)
        self.assertTrue(self.confirm_fixture_bet(logged).idempotent_replay)
        journal = ledger.BET_LOG_PATH.with_suffix(".csv.placements.jsonl")
        self.assertEqual(1, len(journal.read_text().splitlines()))

    def test_receipt_cannot_be_reused_for_another_decision(self):
        first = self.log_fixture_bet()
        self.evaluation.model_output["model_version"] = "fixture-second-version"
        second = self.log_fixture_bet(confirm=False)
        self.assertNotEqual(first.decision_id, second.decision_id)
        with self.assertRaisesRegex(ValueError, "reference is already"):
            self.confirm_fixture_bet(second)

    def test_legacy_approval_is_not_silently_confirmed(self):
        import csv
        ledger = importlib.import_module("doctore_mcp.ledger")
        logged = self.log_fixture_bet(confirm=False)
        rows = ledger.read_bet_rows()
        with ledger.BET_LOG_PATH.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ledger.PRE_PLACEMENT_LOG_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        portfolio = asyncio.run(self.server.doctore_portfolio_status(
            self.server.PortfolioStatusInput(bankroll=50000)))
        self.assertEqual(1, portfolio.legacy_unconfirmed_count)
        self.assertEqual(logged.approved_stake, portfolio.open_exposure)
        with self.assertRaisesRegex(ValueError, "placement must be confirmed"):
            asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
                decision_id=logged.decision_id, result="win", closing_missing_reason="Unavailable",
                settled_at="2026-07-24T22:00:00+03:00")))
        self.assertIn("LEGACY_APPROVAL_PROVENANCE_INCOMPLETE", self.confirm_fixture_bet(logged).policy_warnings)

    def test_equivalent_placement_timezones_replay_as_same_fact(self):
        logged = self.log_fixture_bet()
        result = self.confirm_fixture_bet(logged, placed_at="2026-07-24T08:01:00Z")
        self.assertTrue(result.idempotent_replay)

    def test_result_without_closing_data_is_idempotent_and_has_no_clv(self):
        logged = self.log_fixture_bet()
        params = self.server.SettleBetInput(
            decision_id=logged.decision_id, result="loss",
            settled_at="2026-07-24T22:00:00+03:00",
            closing_missing_reason="Provider did not retain the closing market",
        )
        result = asyncio.run(self.server.doctore_settle_bet(params))
        self.assertIsNone(result.price_clv_pct)
        self.assertIsNone(result.closing_odds)
        self.assertEqual(-logged.approved_stake, result.profit_loss)
        replay = asyncio.run(self.server.doctore_settle_bet(params))
        self.assertTrue(replay.idempotent_replay)
        portfolio = asyncio.run(self.server.doctore_portfolio_status(
            self.server.PortfolioStatusInput(bankroll=50000)))
        self.assertEqual(0, portfolio.open_bet_count)
        self.assertEqual(1, portfolio.settled_bet_count)
        self.assertIsNone(portfolio.avg_price_clv_pct)
        self.assertEqual(result.profit_loss, portfolio.realized_profit_loss)

    def test_missing_close_needs_reason_and_cannot_settle_before_start(self):
        logged = self.log_fixture_bet()
        for reason, settled_at in [(None, "2026-07-24T22:00:00+03:00"),
                                   ("Unavailable", "2026-07-24T19:00:00+03:00")]:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
                        decision_id=logged.decision_id, result="win",
                        settled_at=settled_at, closing_missing_reason=reason)))

    def test_closing_cannot_change_original_start_time(self):
        logged = self.log_fixture_bet()
        closing = market_snapshot(odds=1.80, captured_at="2026-07-24T19:59:00+03:00")
        closing["event_start_at"] = "2026-07-24T21:00:00+03:00"
        with self.assertRaisesRegex(ValueError, "event_start_at"):
            asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
                decision_id=logged.decision_id, result="win", closing_market_snapshot=closing,
                settled_at="2026-07-24T22:00:00+03:00")))

    def test_settlement_closing_snapshot_and_portfolio_status(self) -> None:
        evaluated = asyncio.run(self.server.doctore_evaluate_bet(self.evaluation))
        logged = asyncio.run(self.server.doctore_log_bet(self.server.LogBetInput(
            evaluation=self.evaluation,
            decision_output=evaluated.decision_output,
            human_decision="APPROVE",
        )))
        self.confirm_fixture_bet(logged)
        closing = market_snapshot(odds=1.80, captured_at="2026-07-24T19:59:00+03:00")
        settled = asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
            decision_id=logged.decision_id,
            closing_market_snapshot=closing,
            result="win",
            settled_at="2026-07-24T22:00:00+03:00",
        )))
        self.assertTrue(settled.settled)
        self.assertGreater(settled.price_clv_pct, 0)
        replay = asyncio.run(self.server.doctore_settle_bet(self.server.SettleBetInput(
            decision_id=logged.decision_id,
            closing_market_snapshot=closing,
            result="win",
            settled_at="2026-07-24T22:00:00+03:00",
        )))
        self.assertTrue(replay.idempotent_replay)
        portfolio = asyncio.run(self.server.doctore_portfolio_status(
            self.server.PortfolioStatusInput(bankroll=50000)
        ))
        self.assertEqual(0, portfolio.open_bet_count)
        self.assertEqual(1, portfolio.settled_bet_count)
        self.assertGreater(portfolio.realized_profit_loss, 0)


if __name__ == "__main__":
    unittest.main()
