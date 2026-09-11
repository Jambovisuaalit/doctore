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

    def canonical(self, **overrides) -> dict:
        market = {
            "schema_version": "doctore.market-snapshot.v1",
            "sport": "WNBA",
            "market_type": "moneyline",
            "line": None,
            "settlement_rules": "full_game_including_overtime",
            **self.market(),
        }
        market.update(overrides)
        return market

    def test_public_no_vig_values(self) -> None:
        result = calculate_market_probabilities(self.market())
        market_sum = 1 / 1.90 + 1 / 1.95
        self.assertTrue(math.isclose(1 / 1.90, result["raw_implied_probability"], abs_tol=1e-12))
        self.assertTrue(math.isclose((1 / 1.90) / market_sum, result["no_vig_probability"], abs_tol=1e-12))
        self.assertTrue(math.isclose(market_sum, result["market_sum"], abs_tol=1e-12))
        self.assertTrue(math.isclose(market_sum - 1, result["overround"], abs_tol=1e-12))

    def test_canonical_wNBA_moneyline_remains_supported(self) -> None:
        result = calculate_market_probabilities(self.canonical())
        self.assertGreater(result["market_sum"], 1.0)

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

    def test_integer_basketball_total_is_rejected_before_binary_economics(self) -> None:
        market = self.canonical(
            sport="NBA",
            market_type="total",
            line=224.0,
            settlement_rules="full_game_including_overtime",
            selection="over",
            decimal_odds=1.91,
            outcomes=[
                {"selection": "over", "decimal_odds": 1.91},
                {"selection": "under", "decimal_odds": 1.91},
            ],
        )
        with self.assertRaisesRegex(ValueError, "push or unverified payoff states"):
            calculate_market_probabilities(market)

    def test_half_point_basketball_total_is_supported(self) -> None:
        market = self.canonical(
            sport="NBA",
            market_type="total",
            line=224.5,
            settlement_rules="full_game_including_overtime",
            selection="over",
            decimal_odds=1.91,
            outcomes=[
                {"selection": "over", "decimal_odds": 1.91},
                {"selection": "under", "decimal_odds": 1.91},
            ],
        )
        result = calculate_market_probabilities(market)
        self.assertGreater(result["market_sum"], 1.0)

    def test_soccer_quarter_total_is_rejected(self) -> None:
        market = self.canonical(
            sport="SOCCER",
            market_type="total",
            line=2.25,
            settlement_rules="soccer_90min_including_stoppage_no_extra_time_v1",
            selection="over",
            decimal_odds=1.95,
            outcomes=[
                {"selection": "over", "decimal_odds": 1.95},
                {"selection": "under", "decimal_odds": 1.95},
            ],
        )
        with self.assertRaisesRegex(ValueError, "soccer push/Asian/handicap"):
            calculate_market_probabilities(market)

    def test_soccer_half_total_is_supported(self) -> None:
        market = self.canonical(
            sport="SOCCER",
            market_type="total",
            line=2.5,
            settlement_rules="soccer_90min_including_stoppage_no_extra_time_v1",
            selection="over",
            decimal_odds=1.95,
            outcomes=[
                {"selection": "over", "decimal_odds": 1.95},
                {"selection": "under", "decimal_odds": 1.95},
            ],
        )
        result = calculate_market_probabilities(market)
        self.assertGreater(result["market_sum"], 1.0)

    def test_tennis_moneyline_is_rejected_until_void_probability_is_modeled(self) -> None:
        market = self.canonical(
            sport="TENNIS",
            market_type="match_moneyline",
            line=None,
            settlement_rules="tennis_match_moneyline_full_match_completion_required_v1",
            selection="Player A",
            decimal_odds=1.80,
            outcomes=[
                {"selection": "Player A", "decimal_odds": 1.80},
                {"selection": "Player B", "decimal_odds": 2.10},
            ],
        )
        with self.assertRaisesRegex(ValueError, "retirement/void probability"):
            calculate_market_probabilities(market)

    def test_kbo_moneyline_is_rejected_until_tie_probability_is_modeled(self) -> None:
        market = self.canonical(
            sport="KBO",
            market_type="moneyline",
            line=None,
            settlement_rules="action_including_extra_innings",
            selection="Team A",
            decimal_odds=1.80,
            outcomes=[
                {"selection": "Team A", "decimal_odds": 1.80},
                {"selection": "Team B", "decimal_odds": 2.10},
            ],
        )
        with self.assertRaisesRegex(ValueError, "tie probability"):
            calculate_market_probabilities(market)


if __name__ == "__main__":
    unittest.main()
