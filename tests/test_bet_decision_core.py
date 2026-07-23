from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bet_decision_core import evaluate_bet_decision


EVALUATED_AT = "2026-07-23T18:05:00+03:00"


def model_output(*, status: str = "validated", probability: float = 0.55) -> dict:
    calibrated = probability if status == "validated" else None
    method = "sigmoid" if status == "validated" else "none"
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": "MLB-2026-07-23-BOS-NYY",
        "market_id": "MLB-2026-07-23-BOS-NYY-ML-BOS",
        "model_name": "doctore-mlb-moneyline",
        "model_version": "2026.07.23.1",
        "sport": "MLB",
        "competition": "MLB",
        "market_type": "moneyline",
        "target_market": "full_game_moneyline",
        "period": "full_game",
        "line": None,
        "settlement_rules": "action_including_extra_innings",
        "selection": "Boston Red Sox",
        "probability_raw": probability,
        "probability_calibrated": calibrated,
        "calibration_status": status,
        "calibration_method": method,
        "prediction_generated_at": "2026-07-23T17:50:00+03:00",
        "feature_cutoff_at": "2026-07-23T17:45:00+03:00",
        "training_cutoff_at": "2026-07-22T23:59:59+03:00",
        "feature_schema_version": "mlb.moneyline.v1",
        "validation_domain": {
            "sport": "MLB",
            "competition": "MLB",
            "market_type": "moneyline",
            "target_market": "full_game_moneyline",
            "period": "full_game",
            "line": None,
            "settlement_rules": "action_including_extra_innings",
        },
        "validation_window": "2026-04-01/2026-07-20" if status == "validated" else None,
        "validation_sample_size": 600 if status == "validated" else None,
        "brier_score": 0.21 if status == "validated" else None,
        "log_loss": 0.61 if status == "validated" else None,
        "expected_calibration_error": 0.03 if status == "validated" else None,
    }


def market_snapshot(*, odds: float = 2.20) -> dict:
    return {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": "MLB-2026-07-23-BOS-NYY",
        "market_id": "MLB-2026-07-23-BOS-NYY-ML-BOS",
        "book": "Pinnacle",
        "book_market_id": "1632000000",
        "captured_at": "2026-07-23T18:04:00+03:00",
        "event_start_at": "2026-07-23T20:10:00+03:00",
        "sport": "MLB",
        "competition": "MLB",
        "market_type": "moneyline",
        "target_market": "full_game_moneyline",
        "period": "full_game",
        "line": None,
        "settlement_rules": "action_including_extra_innings",
        "selection": "Boston Red Sox",
        "decimal_odds": odds,
        "market_status": "open",
        "is_complete": True,
        "outcomes": [
            {"selection": "Boston Red Sox", "decimal_odds": odds},
            {"selection": "New York Yankees", "decimal_odds": 1.75},
        ],
        "correlation_group": "MLB-2026-07-23-BOS-NYY",
        "source": "synthetic-test",
    }


def portfolio_state() -> dict:
    return {
        "schema_version": "doctore.portfolio-state.v1",
        "portfolio_id": "primary-eur",
        "captured_at": "2026-07-23T18:04:30+03:00",
        "currency": "EUR",
        "bankroll": 50000.0,
        "available_balance": 40000.0,
        "stake_increment": 1.0,
        "league": "MLB",
        "correlation_group": "MLB-2026-07-23-BOS-NYY",
        "drawdown_fraction": 0.04,
        "open_positions_count": 4,
        "exposures": {
            "open_amount": 2000.0,
            "daily_turnover_amount": 3000.0,
            "league_amount": 2500.0,
            "rolling_3d_turnover_amount": 7000.0,
            "correlation_group_amount": 0.0,
        },
    }


def risk_policy() -> dict:
    return {
        "schema_version": "doctore.risk-policy.v1",
        "policy_id": "doctore-default",
        "policy_version": "2026.07.23",
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


def mlb_context(*, starter_status: str = "confirmed") -> dict:
    return {
        "schema_version": "doctore.mlb-context.v1",
        "event_id": "MLB-2026-07-23-BOS-NYY",
        "captured_at": "2026-07-23T18:03:00+03:00",
        "settlement": {"pitcher_rule": "action", "listed_pitchers_match": None},
        "starters": {
            "home": {"name": "Starter A", "status": starter_status},
            "away": {"name": "Starter B", "status": "confirmed"},
        },
        "lineups": {"home": "confirmed_compatible", "away": "confirmed_compatible"},
        "bullpen": {"home": "current", "away": "current"},
        "environment": {
            "roof_matches_model": True,
            "weather_matches_model": True,
            "umpire_matches_model": None,
        },
        "model_dependencies": {
            "requires_confirmed_starters": True,
            "requires_lineup_compatibility": True,
            "requires_bullpen_state": True,
            "uses_roof": True,
            "uses_weather": True,
            "uses_umpire": False,
        },
    }


def evaluate(*, model=None, market=None, portfolio=None, policy=None, context=None) -> dict:
    return evaluate_bet_decision(
        model_output=model or model_output(),
        market_snapshot=market or market_snapshot(),
        portfolio_state=portfolio or portfolio_state(),
        risk_policy=policy or risk_policy(),
        evaluated_at=EVALUATED_AT,
        sport_context=context or mlb_context(),
    )


class SchemaTests(unittest.TestCase):
    def test_all_new_schemas_are_valid_draft_2020_12(self) -> None:
        paths = [
            ROOT / "contracts" / "market-snapshot.schema.json",
            ROOT / "contracts" / "portfolio-state.schema.json",
            ROOT / "contracts" / "risk-policy.schema.json",
            ROOT / "contracts" / "decision-output.schema.json",
            ROOT / "skills" / "sport-specific" / "mlb" / "contracts" / "mlb-context.schema.json",
        ]
        for path in paths:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

    def test_fixtures_validate_against_input_schemas(self) -> None:
        fixtures = [
            ("model-output.schema.json", model_output()),
            ("market-snapshot.schema.json", market_snapshot()),
            ("portfolio-state.schema.json", portfolio_state()),
            ("risk-policy.schema.json", risk_policy()),
        ]
        for schema_name, payload in fixtures:
            schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
            self.assertEqual([], errors, msg=f"{schema_name}: {errors}")


class DecisionIntegrationTests(unittest.TestCase):
    def assert_decision_schema_valid(self, payload: dict) -> None:
        schema = json.loads((ROOT / "contracts" / "decision-output.schema.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        self.assertEqual([], errors, msg="\n".join(error.message for error in errors))

    def test_validated_candidate_qualifies_and_is_capped_at_two_percent(self) -> None:
        result = evaluate()
        self.assert_decision_schema_valid(result)
        self.assertEqual("BET", result["decision"])
        self.assertEqual(["QUALIFIED"], result["reason_codes"])
        self.assertEqual(0.25, result["staking"]["kelly_fraction"])
        self.assertEqual(1000.0, result["staking"]["final_stake"])
        self.assertEqual("per_bet", result["staking"]["binding_cap"])
        self.assertTrue(result["human_approval_required"])

    def test_uncalibrated_candidate_uses_raw_probability_and_tenth_kelly(self) -> None:
        result = evaluate(model=model_output(status="uncalibrated"))
        self.assertEqual("BET", result["decision"])
        self.assertEqual(0.10, result["staking"]["kelly_fraction"])
        self.assertEqual(result["model"]["probability_raw"], result["model"]["probability_used_for_economics"])
        self.assertIsNone(result["model"]["probability_calibrated"])

    def test_domain_mismatch_is_blocked(self) -> None:
        market = market_snapshot()
        market["period"] = "first_five"
        result = evaluate(market=market)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("DOMAIN_MISMATCH", result["reason_codes"])

    def test_negative_economics_passes_without_stake(self) -> None:
        result = evaluate(model=model_output(probability=0.44))
        self.assertEqual("PASS", result["decision"])
        self.assertIn("EV_BELOW_MINIMUM", result["reason_codes"])
        self.assertIsNone(result["staking"]["final_stake"])

    def test_stale_market_is_blocked(self) -> None:
        market = market_snapshot()
        market["captured_at"] = "2026-07-23T17:00:00+03:00"
        result = evaluate(market=market)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("MARKET_SNAPSHOT_STALE", result["reason_codes"])

    def test_exhausted_open_exposure_is_blocked(self) -> None:
        portfolio = portfolio_state()
        portfolio["exposures"]["open_amount"] = 5000.0
        result = evaluate(portfolio=portfolio)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("NO_RISK_CAPACITY", result["reason_codes"])

    def test_mlb_starter_change_is_blocked(self) -> None:
        result = evaluate(context=mlb_context(starter_status="changed"))
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("MLB_STARTER_CHANGED", result["reason_codes"])

    def test_projected_mlb_starter_is_watch(self) -> None:
        result = evaluate(context=mlb_context(starter_status="projected"))
        self.assertEqual("WATCH", result["decision"])
        self.assertIn("MLB_STARTER_UNCONFIRMED", result["reason_codes"])
        self.assertIsNone(result["staking"]["final_stake"])

    def test_missing_mlb_context_is_blocked(self) -> None:
        result = evaluate_bet_decision(
            model_output=model_output(), market_snapshot=market_snapshot(),
            portfolio_state=portfolio_state(), risk_policy=risk_policy(),
            evaluated_at=EVALUATED_AT, sport_context=None,
        )
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("MLB_CONTEXT_MISSING", result["reason_codes"])

    def test_structurally_invalid_input_returns_schema_valid_blocked_output(self) -> None:
        market = market_snapshot()
        market["decimal_odds"] = "not-a-number"
        result = evaluate(market=market)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("INPUT_SCHEMA_INVALID", result["reason_codes"])
        self.assertIsNone(result["decimal_odds"])
        self.assert_decision_schema_valid(result)

    def test_identical_inputs_produce_identical_output(self) -> None:
        first, second = evaluate(), evaluate()
        self.assertEqual(first, second)
        self.assertEqual(first["decision_id"], second["decision_id"])

    def test_cli_emits_same_schema_valid_decision(self) -> None:
        script = ROOT / "skills" / "bet-decision-core" / "scripts" / "evaluate_bet.py"
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for name, payload in {
                "model": model_output(), "market": market_snapshot(),
                "portfolio": portfolio_state(), "policy": risk_policy(),
                "context": mlb_context(),
            }.items():
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[name] = path
            completed = subprocess.run([
                sys.executable, str(script), "--model-output", str(paths["model"]),
                "--market-snapshot", str(paths["market"]), "--portfolio-state", str(paths["portfolio"]),
                "--risk-policy", str(paths["policy"]), "--sport-context", str(paths["context"]),
                "--evaluated-at", EVALUATED_AT,
            ], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(0, completed.returncode, msg=completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("BET", result["decision"])
        self.assert_decision_schema_valid(result)


if __name__ == "__main__":
    unittest.main()
