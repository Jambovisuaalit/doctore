from __future__ import annotations

from pathlib import Path
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_probability import calculate_market_probabilities


class MarketProbabilityTests(unittest.TestCase):
    def market(self) -> dict:
        return {
            "selection": "Minnesota Lynx",
            "decimal_odds": 1.90,
            "outcomes": [
                {"selection": "Minnesota Lynx", "decimal_odds": 1.90},
                {"selection": "New York Liberty", "decimal_odds": 1.95},
            ],
        }

    def test_public_no_vig_values(self) -> None:
        result = calculate_market_probabilities(self.market())
        market_sum = 1 / 1.90 + 1 / 1.95
        self.assertTrue(math.isclose(1 / 1.90, result["raw_implied_probability"], abs_tol=1e-12))
        self.assertTrue(math.isclose((1 / 1.90) / market_sum, result["no_vig_probability"], abs_tol=1e-12))
        self.assertTrue(math.isclose(market_sum, result["market_sum"], abs_tol=1e-12))
        self.assertTrue(math.isclose(market_sum - 1, result["overround"], abs_tol=1e-12))

    def test_selected_price_mismatch_is_rejected(self) -> None:
        market = self.market()
        market["decimal_odds"] = 1.91
        with self.assertRaisesRegex(ValueError, "selected outcome odds mismatch"):
            calculate_market_probabilities(market)

    def test_incomplete_market_is_rejected(self) -> None:
        market = self.market()
        market["outcomes"] = market["outcomes"][:1]
        with self.assertRaisesRegex(ValueError, "at least two"):
            calculate_market_probabilities(market)

    def test_invalid_outcome_price_is_rejected(self) -> None:
        market = self.market()
        market["outcomes"][1]["decimal_odds"] = 1.0
        with self.assertRaisesRegex(ValueError, "greater than 1"):
            calculate_market_probabilities(market)


if __name__ == "__main__":
    unittest.main()
