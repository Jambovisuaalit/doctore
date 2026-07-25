from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tennis_context import evaluate_tennis_context, evaluate_tennis_settlement


EVALUATED_AT = "2026-07-25T12:00:00+03:00"


def market_snapshot() -> dict:
    return {
        "event_id": "TENNIS-ATP-KITZBUHEL-2026-R16-1001",
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
        "event_id": "TENNIS-ATP-KITZBUHEL-2026-R16-1001",
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


def evaluate(context: dict) -> dict:
    return evaluate_tennis_context(
        context,
        market_snapshot=market_snapshot(),
        evaluated_at=EVALUATED_AT,
        max_age_seconds=900,
    )


class TennisContextTests(unittest.TestCase):
    def test_correct_scope_passes(self) -> None:
        result = evaluate(tennis_context())
        self.assertEqual({"status", "reason_codes", "diagnostics"}, set(result))
        self.assertEqual("VALID", result["status"])
        self.assertEqual([], result["reason_codes"])

    def test_wrong_tier_is_rejected(self) -> None:
        context = tennis_context()
        context["tier"] = "challenger"
        result = evaluate(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("TENNIS_TIER_MISMATCH", result["reason_codes"])

    def test_best_of_five_is_rejected(self) -> None:
        context = tennis_context()
        context["match_format"] = "best_of_5"
        result = evaluate(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("TENNIS_BEST_OF_FIVE_EXCLUDED", result["reason_codes"])

    def test_in_progress_match_is_rejected(self) -> None:
        context = tennis_context()
        context["event_status"] = "in_progress"
        result = evaluate(context)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("EVENT_ALREADY_STARTED", result["reason_codes"])

    def test_retirement_settlement_is_excluded_but_audited(self) -> None:
        result = evaluate_tennis_settlement({"match_status": "retirement"})
        self.assertEqual("void_retirement", result["settlement_status"])
        self.assertTrue(result["exclude_from_clv_aggregation"])
        self.assertTrue(result["exclude_from_brier_aggregation"])
        self.assertTrue(result["keep_in_raw_audit_log"])


if __name__ == "__main__":
    unittest.main()
