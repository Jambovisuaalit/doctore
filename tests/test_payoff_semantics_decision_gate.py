from __future__ import annotations

from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bet_decision_core import evaluate_bet_decision  # noqa: E402

FIXTURES = runpy.run_path(str(ROOT / "tests" / "test_bet_decision_core.py"))


class PayoffSemanticsDecisionGateTests(unittest.TestCase):
    def test_integer_total_is_blocked_before_ev_and_kelly(self) -> None:
        market = FIXTURES["market_snapshot"]()
        model = FIXTURES["model_output"]()
        portfolio = FIXTURES["portfolio_state"]()
        policy = FIXTURES["risk_policy"]()

        market.update({
            "sport": "NBA",
            "competition": "NBA",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "line": 224.0,
            "settlement_rules": "full_game_including_overtime",
            "selection": "over",
            "decimal_odds": 1.91,
            "outcomes": [
                {"selection": "over", "decimal_odds": 1.91},
                {"selection": "under", "decimal_odds": 1.91},
            ],
        })
        model.update({
            "sport": "NBA",
            "competition": "NBA",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "line": 224.0,
            "settlement_rules": "full_game_including_overtime",
            "selection": "over",
        })
        model["validation_domain"] = {
            "sport": "NBA",
            "competition": "NBA",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "line": 224.0,
            "settlement_rules": "full_game_including_overtime",
        }
        portfolio["league"] = "NBA"

        result = evaluate_bet_decision(
            model_output=model,
            market_snapshot=market,
            portfolio_state=portfolio,
            risk_policy=policy,
            evaluated_at=FIXTURES["EVALUATED_AT"],
            sport_context=None,
        )

        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("MARKET_INCOMPLETE", result["reason_codes"])
        self.assertTrue(any("payoff semantics unsupported" in item for item in result["diagnostics"]))
        self.assertIsNone(result["economics"]["ev"])
        self.assertIsNone(result["economics"]["full_kelly"])
        self.assertIsNone(result["staking"]["final_stake"])


if __name__ == "__main__":
    unittest.main()
