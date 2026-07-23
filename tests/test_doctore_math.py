import unittest

from src.doctore_math import (
    expected_value,
    full_kelly_fraction,
    implied_probability,
    market_margin,
    minimum_odds_for_ev,
    minimum_probability_for_ev,
    no_vig_probabilities,
    price_clv,
    raw_clv_probability_points,
    shrunk_probability,
)


class DoctoreMathTests(unittest.TestCase):
    def test_implied_probability(self) -> None:
        self.assertAlmostEqual(implied_probability(2.10), 1 / 2.10)

    def test_no_vig_market(self) -> None:
        probabilities = no_vig_probabilities([2.10, 1.75])
        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertAlmostEqual(probabilities[0], 0.4545454545454546)
        self.assertAlmostEqual(market_margin([2.10, 1.75]), 0.04761904761904767)

    def test_expected_value(self) -> None:
        self.assertAlmostEqual(expected_value(0.51, 2.10), 0.071)

    def test_price_thresholds(self) -> None:
        self.assertAlmostEqual(minimum_odds_for_ev(0.51, 0.03), 1.03 / 0.51)
        self.assertAlmostEqual(minimum_probability_for_ev(2.10, 0.03), 1.03 / 2.10)

    def test_uncertainty_shrinkage_and_kelly(self) -> None:
        market_probability = 0.4545454545454546
        sizing_probability = shrunk_probability(0.51, market_probability, 0.85)
        self.assertAlmostEqual(sizing_probability, 0.5016818181818182)
        self.assertAlmostEqual(
            full_kelly_fraction(sizing_probability, 2.10),
            0.048665289256198445,
        )

    def test_negative_kelly_is_zero(self) -> None:
        self.assertEqual(full_kelly_fraction(0.45, 2.00), 0.0)

    def test_positive_clv_sign(self) -> None:
        self.assertGreater(raw_clv_probability_points(2.30, 2.10), 0.0)
        self.assertAlmostEqual(price_clv(2.30, 2.10), 2.30 / 2.10 - 1.0)

    def test_invalid_values_raise(self) -> None:
        with self.assertRaises(ValueError):
            implied_probability(1.0)
        with self.assertRaises(ValueError):
            expected_value(1.2, 2.0)
        with self.assertRaises(ValueError):
            no_vig_probabilities([2.0])


if __name__ == "__main__":
    unittest.main()
