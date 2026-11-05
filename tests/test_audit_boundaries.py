"""Regressions for the project audit's market and numeric boundaries."""
import math
import os
from pathlib import Path
import tempfile
os.environ.setdefault("DOCTORE_REPO_PATH", str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DOCTORE_BET_LOG", str(Path(tempfile.gettempdir()) / "doctore-audit-boundaries.csv"))
import unittest
from unittest.mock import patch

from test_bet_decision_core import evaluate, model_output, market_snapshot, portfolio_state, risk_policy
from market_probability import calculate_market_probabilities
from doctore_mcp.decision_adapter import check_data_quality, load_model_prediction
from doctore_mcp.schemas import QualityGateInput, LoadPredictionInput


class NumericBoundaryTests(unittest.TestCase):
    def test_real_prediction_adapter_preserves_settlement_domain(self):
        result = load_model_prediction(LoadPredictionInput(
            prediction_path="examples/sample-versioned-prediction.json", market_id="example",
            competition="NBA", target_market="full_game_total",
            settlement_rules="full_game_including_overtime",
        ))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.model_output["settlement_rules"], "full_game_including_overtime")
        self.assertEqual(result.model_output["validation_domain"]["settlement_rules"], "full_game_including_overtime")

    def test_all_nonfinite_numeric_inputs_fail_closed(self):
        for value in (math.inf, -math.inf, math.nan):
            for name, factory, key in (
                ("model", model_output, "probability_calibrated"),
                ("market", market_snapshot, "decimal_odds"),
                ("portfolio", portfolio_state, "bankroll"),
                ("policy", risk_policy, "kelly_fraction"),
            ):
                with self.subTest(value=value, name=name):
                    payload = factory()
                    payload[key] = value
                    result = evaluate(**{name: payload})
                    self.assertEqual(result["decision"], "BLOCKED")
                    self.assertIn("INPUT_SCHEMA_INVALID", result["reason_codes"])

    def test_market_price_vector_rejects_nonfinite_values(self):
        for value in (math.inf, -math.inf, math.nan):
            market = {"selection": "a", "decimal_odds": value,
                      "outcomes": [{"selection": "a", "decimal_odds": value},
                                   {"selection": "b", "decimal_odds": value}]}
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate_market_probabilities(market)

    def test_quality_gate_rejects_nonfinite_reference(self):
        for value in (math.inf, -math.inf, math.nan):
            params = QualityGateInput(snapshot_at="2026-10-15T12:00:00Z",
                                      reference_odds={"a": value}, current_odds={"a": 2.0})
            with patch.dict(check_data_quality.__globals__, {"minutes_since": lambda _: 0.1}):
                self.assertEqual(check_data_quality(params).status, "BLOCKED")
