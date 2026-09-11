from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_contract_adapter import (  # noqa: E402
    adapt_and_join_selection_record,
    adapt_selection_record,
    exact_model_output_join,
)


def raw_record(
    *,
    sport: str = "MLB",
    competition: str = "Generic",
    market_key: str = "h2h",
    bookmaker: str = "Pinnacle",
    selection: str = "Colorado Rockies",
    price: float = 2.57,
    point=None,
    outcomes=None,
    event_id: str = "0d167726c87fa6102be38d57",
    raw_market_id: str = "c490a262b835162d6f5f773d",
) -> dict:
    if outcomes is None:
        outcomes = [
            {"name": "Colorado Rockies", "price": 2.57},
            {"name": "Detroit Tigers", "price": 1.57},
        ]
    return {
        "selection_id": "96c02f578773b81dbd831e7d",
        "market_id": raw_market_id,
        "event_id": event_id,
        "source_event_id": "ef265df05ca10a02712319b8f7e74641",
        "book_market_id": "ef265df05ca10a02712319b8f7e74641_h2h",
        "source": "the-odds-api",
        "captured_at": "2026-09-11T01:45:22Z",
        "event_start_at": "2026-09-11T22:41:00Z",
        "market_status": "open",
        "sport": sport,
        "competition": competition,
        "home_team": "Detroit Tigers",
        "away_team": "Colorado Rockies",
        "bookmaker": bookmaker,
        "market_key": market_key,
        "exact_domain": "generic_h2h",
        "period": "full_time",
        "target_market": "moneyline_or_equivalent",
        "settlement_rules": "standard_rule_v1",
        "selection_name": selection,
        "price": price,
        "point": point,
        "outcomes_vector_json": json.dumps(outcomes),
    }


def soccer_h2h_record(*, bookmaker: str = "Pinnacle") -> dict:
    outcomes = [
        {"name": "Aston Villa", "price": 2.32},
        {"name": "Nottingham Forest", "price": 3.22},
        {"name": "Draw", "price": 3.44},
    ]
    return raw_record(
        sport="EPL",
        market_key="h2h",
        bookmaker=bookmaker,
        selection="Aston Villa",
        price=2.32,
        outcomes=outcomes,
    )


def tennis_h2h_record(*, bookmaker: str = "Pinnacle") -> dict:
    outcomes = [
        {"name": "Alexander Zverev", "price": 1.19},
        {"name": "Karen Khachanov", "price": 4.51},
    ]
    return raw_record(
        sport="ATP US Open",
        market_key="h2h",
        bookmaker=bookmaker,
        selection="Alexander Zverev",
        price=1.19,
        outcomes=outcomes,
    )


def valid_model(snapshot: dict, *, probability: float = 0.55) -> dict:
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": snapshot["event_id"],
        "market_id": snapshot["market_id"],
        "model_name": "test-model",
        "model_version": "1.0.0",
        "sport": snapshot["sport"],
        "competition": snapshot["competition"],
        "market_type": snapshot["market_type"],
        "target_market": snapshot["target_market"],
        "period": snapshot["period"],
        "line": snapshot["line"],
        "settlement_rules": snapshot["settlement_rules"],
        "selection": snapshot["selection"],
        "probability_raw": probability,
        "probability_calibrated": probability,
        "calibration_status": "validated",
        "calibration_method": "sigmoid",
        "prediction_generated_at": "2026-09-11T01:40:00Z",
        "feature_cutoff_at": "2026-09-11T01:35:00Z",
        "training_cutoff_at": "2026-09-10T23:59:59Z",
        "feature_schema_version": "test.v1",
        "validation_domain": {
            "sport": snapshot["sport"],
            "competition": snapshot["competition"],
            "market_type": snapshot["market_type"],
            "target_market": snapshot["target_market"],
            "period": snapshot["period"],
            "line": snapshot["line"],
            "settlement_rules": snapshot["settlement_rules"],
        },
        "validation_window": "2026-01-01/2026-09-01",
        "validation_sample_size": 500,
        "brier_score": 0.22,
        "log_loss": 0.63,
        "expected_calibration_error": 0.03,
    }


class MarketContractAdapterTests(unittest.TestCase):
    def test_mlb_h2h_becomes_canonical_moneyline(self) -> None:
        result = adapt_selection_record(raw_record())
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("doctore.market-snapshot.v1", snapshot["schema_version"])
        self.assertEqual("MLB", snapshot["sport"])
        self.assertEqual("MLB", snapshot["competition"])
        self.assertEqual("moneyline", snapshot["market_type"])
        self.assertEqual("full_game_moneyline", snapshot["target_market"])
        self.assertEqual("full_game", snapshot["period"])
        self.assertEqual("action_including_extra_innings", snapshot["settlement_rules"])
        self.assertIsNone(snapshot["line"])
        self.assertEqual("Colorado Rockies", snapshot["selection"])
        self.assertEqual(2.57, snapshot["decimal_odds"])
        self.assertNotIn("book_market_id", snapshot)
        self.assertEqual(snapshot["event_id"], snapshot["correlation_group"])

    def test_kbo_spread_becomes_run_line(self) -> None:
        outcomes = [
            {"name": "Hanwha Eagles", "price": 1.70, "point": 1.5},
            {"name": "NC Dinos", "price": 2.18, "point": -1.5},
        ]
        record = raw_record(
            sport="KBO", market_key="spreads", selection="Hanwha Eagles",
            price=1.70, point=1.5, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("KBO", snapshot["competition"])
        self.assertEqual("run_line", snapshot["market_type"])
        self.assertEqual("full_game_run_line", snapshot["target_market"])
        self.assertEqual("full_game_including_extra_innings", snapshot["settlement_rules"])
        self.assertEqual(1.5, snapshot["line"])

    def test_npb_total_becomes_full_game_total_and_normalizes_selection(self) -> None:
        outcomes = [
            {"name": "Over", "price": 1.91, "point": 8.5},
            {"name": "Under", "price": 1.91, "point": 8.5},
        ]
        record = raw_record(
            sport="NPB", market_key="totals", selection="Over",
            price=1.91, point=8.5, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("total", snapshot["market_type"])
        self.assertEqual("full_game_total", snapshot["target_market"])
        self.assertEqual("over", snapshot["selection"])
        self.assertEqual({"over", "under"}, {x["selection"] for x in snapshot["outcomes"]})

    def test_verified_soccer_h2h_becomes_canonical_1x2(self) -> None:
        result = adapt_selection_record(soccer_h2h_record(bookmaker="Pinnacle"))
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("SOCCER", snapshot["sport"])
        self.assertEqual("EPL", snapshot["competition"])
        self.assertEqual("1x2", snapshot["market_type"])
        self.assertEqual("full_time_1x2", snapshot["target_market"])
        self.assertEqual("regulation_time", snapshot["period"])
        self.assertEqual(
            "soccer_90min_including_stoppage_no_extra_time_v1",
            snapshot["settlement_rules"],
        )
        self.assertEqual("soccer.pinnacle.regulation90.v1", result["settlement_evidence"]["rule_id"])
        self.assertIsNone(snapshot["line"])

    def test_soccer_unverified_book_stays_fail_closed(self) -> None:
        result = adapt_selection_record(soccer_h2h_record(bookmaker="Unibet"))
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertEqual({"sport": "SOCCER", "competition": "EPL"}, result["normalized"])
        self.assertEqual("1x2", result["domain"]["market_type"])
        self.assertIn("BOOK_SETTLEMENT_RULE_UNVERIFIED", result["reason_codes"])
        self.assertIsNone(result["market_snapshot"])

    def test_soccer_country_and_competition_are_split(self) -> None:
        record = soccer_h2h_record(bookmaker="Pinnacle")
        record["sport"] = "Germany"
        record["competition"] = "Bundesliga"
        result = adapt_selection_record(record)
        self.assertEqual("SOCCER", result["normalized"]["sport"])
        self.assertEqual("Bundesliga", result["normalized"]["competition"])

    def test_verified_soccer_half_total_becomes_canonical(self) -> None:
        outcomes = [
            {"name": "Over", "price": 1.95, "point": 2.5},
            {"name": "Under", "price": 1.85, "point": 2.5},
        ]
        record = raw_record(
            sport="Italy", competition="Serie A", market_key="totals",
            bookmaker="Betsson", selection="Over", price=1.95,
            point=2.5, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("total", snapshot["market_type"])
        self.assertEqual("full_time_total", snapshot["target_market"])
        self.assertEqual(2.5, snapshot["line"])
        self.assertEqual("over", snapshot["selection"])
        self.assertEqual(
            "soccer_90min_including_stoppage_no_extra_time_v1",
            snapshot["settlement_rules"],
        )

    def test_soccer_integer_total_is_blocked_for_push_semantics(self) -> None:
        outcomes = [
            {"name": "Over", "price": 1.95, "point": 2.0},
            {"name": "Under", "price": 1.85, "point": 2.0},
        ]
        record = raw_record(
            sport="Italy", competition="Serie A", market_key="totals",
            bookmaker="Pinnacle", selection="Over", price=1.95,
            point=2.0, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertIn("PUSH_SETTLEMENT_UNSUPPORTED", result["reason_codes"])
        self.assertIsNone(result["market_snapshot"])

    def test_soccer_quarter_total_is_blocked(self) -> None:
        outcomes = [
            {"name": "Over", "price": 1.95, "point": 2.25},
            {"name": "Under", "price": 1.85, "point": 2.25},
        ]
        record = raw_record(
            sport="Italy", competition="Serie A", market_key="totals",
            bookmaker="Pinnacle", selection="Over", price=1.95,
            point=2.25, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertIn("ASIAN_QUARTER_LINE_UNSUPPORTED", result["reason_codes"])

    def test_soccer_spread_stays_blocked_even_on_half_line(self) -> None:
        outcomes = [
            {"name": "Team A", "price": 1.95, "point": -0.5},
            {"name": "Team B", "price": 1.85, "point": 0.5},
        ]
        record = raw_record(
            sport="Italy", competition="Serie A", market_key="spreads",
            bookmaker="Pinnacle", selection="Team A", price=1.95,
            point=-0.5, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertIn("SOCCER_HANDICAP_SETTLEMENT_UNVERIFIED", result["reason_codes"])

    def test_soccer_semantic_rule_is_shared_across_verified_books(self) -> None:
        pinnacle = adapt_selection_record(soccer_h2h_record(bookmaker="Pinnacle"))
        betsson = adapt_selection_record(soccer_h2h_record(bookmaker="Betsson"))
        self.assertEqual("CANONICAL", pinnacle["status"])
        self.assertEqual("CANONICAL", betsson["status"])
        self.assertEqual(
            pinnacle["market_snapshot"]["settlement_rules"],
            betsson["market_snapshot"]["settlement_rules"],
        )
        self.assertEqual(
            pinnacle["market_snapshot"]["market_id"],
            betsson["market_snapshot"]["market_id"],
        )
        self.assertNotEqual(
            pinnacle["settlement_evidence"]["rule_id"],
            betsson["settlement_evidence"]["rule_id"],
        )

    def test_verified_pinnacle_tennis_moneyline_becomes_canonical(self) -> None:
        result = adapt_selection_record(tennis_h2h_record(bookmaker="Pinnacle"))
        self.assertEqual("CANONICAL", result["status"])
        snapshot = result["market_snapshot"]
        self.assertEqual("TENNIS", snapshot["sport"])
        self.assertEqual("match_moneyline", snapshot["market_type"])
        self.assertEqual("full_match_moneyline", snapshot["target_market"])
        self.assertEqual(
            "tennis_match_moneyline_one_full_set_required_retirement_winner_advances_v1",
            snapshot["settlement_rules"],
        )
        self.assertEqual(
            "tennis.pinnacle.match-moneyline.one-set.v1",
            result["settlement_evidence"]["rule_id"],
        )

    def test_verified_william_hill_tennis_requires_full_match(self) -> None:
        result = adapt_selection_record(tennis_h2h_record(bookmaker="William Hill"))
        self.assertEqual("CANONICAL", result["status"])
        self.assertEqual(
            "tennis_match_moneyline_full_match_completion_required_v1",
            result["market_snapshot"]["settlement_rules"],
        )

    def test_tennis_unverified_book_stays_fail_closed(self) -> None:
        result = adapt_selection_record(tennis_h2h_record(bookmaker="Unibet"))
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertEqual({"sport": "TENNIS", "competition": "ATP US Open"}, result["normalized"])
        self.assertEqual("match_moneyline", result["domain"]["market_type"])
        self.assertIn("BOOK_SETTLEMENT_RULE_UNVERIFIED", result["reason_codes"])
        self.assertIsNone(result["market_snapshot"])

    def test_tennis_non_moneyline_stays_fail_closed(self) -> None:
        outcomes = [
            {"name": "Over", "price": 1.91, "point": 38.5},
            {"name": "Under", "price": 1.91, "point": 38.5},
        ]
        record = raw_record(
            sport="ATP US Open", market_key="totals", bookmaker="Pinnacle",
            selection="Over", price=1.91, point=38.5, outcomes=outcomes,
        )
        result = adapt_selection_record(record)
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertIn("TENNIS_NON_MONEYLINE_SETTLEMENT_UNVERIFIED", result["reason_codes"])

    def test_unknown_sport_fails_closed(self) -> None:
        record = raw_record(sport="Unknown Hockey League")
        result = adapt_selection_record(record)
        self.assertEqual("INVALID_INPUT", result["status"])
        self.assertIn("SPORT_UNVERIFIED", result["reason_codes"])
        self.assertIsNone(result["market_snapshot"])

    def test_post_start_quote_is_invalid(self) -> None:
        record = raw_record()
        record["captured_at"] = "2026-09-12T00:00:00Z"
        result = adapt_selection_record(record)
        self.assertEqual("INVALID_INPUT", result["status"])
        self.assertIn("QUOTE_NOT_PREGAME", result["reason_codes"])

    def test_selected_price_must_match_outcomes_vector(self) -> None:
        record = raw_record(price=2.60)
        result = adapt_selection_record(record)
        self.assertEqual("INVALID_INPUT", result["status"])
        self.assertIn("SELECTED_PRICE_MISMATCH", result["reason_codes"])

    def test_canonical_market_id_is_book_independent(self) -> None:
        first = adapt_selection_record(raw_record(bookmaker="Pinnacle", raw_market_id="raw-a"))
        second = adapt_selection_record(raw_record(bookmaker="Betsson", raw_market_id="raw-b"))
        self.assertEqual(first["market_snapshot"]["market_id"], second["market_snapshot"]["market_id"])
        self.assertNotEqual(first["market_snapshot"]["book"], second["market_snapshot"]["book"])

    def test_opposite_selection_has_distinct_canonical_market_id(self) -> None:
        first = adapt_selection_record(raw_record())
        second = adapt_selection_record(raw_record(selection="Detroit Tigers", price=1.57))
        self.assertNotEqual(first["market_snapshot"]["market_id"], second["market_snapshot"]["market_id"])

    def test_exact_model_join_matches_one_model(self) -> None:
        adapted = adapt_selection_record(raw_record())
        snapshot = adapted["market_snapshot"]
        model = valid_model(snapshot)
        result = exact_model_output_join(snapshot, [model])
        self.assertEqual("MATCHED", result["status"])
        self.assertEqual(model, result["model_output"])

    def test_exact_model_join_matches_soccer_model_across_verified_books(self) -> None:
        pinnacle = adapt_selection_record(soccer_h2h_record(bookmaker="Pinnacle"))["market_snapshot"]
        betsson = adapt_selection_record(soccer_h2h_record(bookmaker="Betsson"))["market_snapshot"]
        model = valid_model(pinnacle)
        result = exact_model_output_join(betsson, [model])
        self.assertEqual("MATCHED", result["status"])

    def test_exact_model_join_rejects_tennis_settlement_mismatch(self) -> None:
        pinnacle = adapt_selection_record(tennis_h2h_record(bookmaker="Pinnacle"))["market_snapshot"]
        william_hill = adapt_selection_record(tennis_h2h_record(bookmaker="William Hill"))["market_snapshot"]
        model = valid_model(pinnacle)
        result = exact_model_output_join(william_hill, [model])
        self.assertEqual("MODEL_DOMAIN_MISMATCH", result["status"])
        self.assertTrue(any("settlement_rules" in item for item in result["diagnostics"]))

    def test_exact_model_join_rejects_domain_mismatch(self) -> None:
        adapted = adapt_selection_record(raw_record())
        snapshot = adapted["market_snapshot"]
        model = valid_model(snapshot)
        model["period"] = "first_five"
        model["validation_domain"]["period"] = "first_five"
        result = exact_model_output_join(snapshot, [model])
        self.assertEqual("MODEL_DOMAIN_MISMATCH", result["status"])
        self.assertTrue(any("period" in item for item in result["diagnostics"]))

    def test_unverified_domain_never_reaches_model_join(self) -> None:
        record = tennis_h2h_record(bookmaker="Unibet")
        result = adapt_and_join_selection_record(record, [])
        self.assertEqual("DOMAIN_UNVERIFIED", result["status"])
        self.assertIsNone(result["market_snapshot"])
        self.assertIsNone(result["model_output"])

    def test_duplicate_exact_models_fail_closed(self) -> None:
        adapted = adapt_selection_record(raw_record())
        snapshot = adapted["market_snapshot"]
        model = valid_model(snapshot)
        result = exact_model_output_join(snapshot, [model, copy.deepcopy(model)])
        self.assertEqual("MODEL_OUTPUT_AMBIGUOUS", result["status"])
        self.assertIsNone(result["model_output"])


if __name__ == "__main__":
    unittest.main()
