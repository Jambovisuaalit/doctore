"""Fail-closed NHL quote scan regression tests; all inputs are synthetic fixtures."""
import copy
import unittest

from doctore_mcp.nhl_quote_scanner import scan_nhl_totals

NOW = "2026-11-01T17:54:00+02:00"


def quote(book: str, over: float, under: float, **changes):
    data = {
        "canonical_event_id": "nhl:2026020177",
        "event_identity_verified": True,
        "provider_event_id": "provider-nhl-0177",
        "provider_quote_id": "quote-" + book,
        "book": book,
        "source_observed_at": "2026-11-01T17:52:00+02:00",
        "captured_at": "2026-11-01T17:52:15+02:00",
        "source_capture_method": "provider_api",
        "scheduled_start_at": "2026-11-02T02:00:00+02:00",
        "market_state": "pregame",
        "quote_status": "open",
        "sport": "NHL", "competition": "NHL",
        "market_type": "total", "period": "full_game",
        "line": 6.5, "line_role": "main",
        "over_odds": over, "under_odds": under,
        "settlement_scope": "REGULATION_OT_SO",
        "settlement_rule_url": "https://example.org/verified-rule-" + book,
        "settlement_rule_verified_at": "2026-11-01T17:50:00+02:00",
        "settlement_rule_verified": True,
        "commission_fraction": 0.0,
    }
    data.update(changes)
    return data


class NhlQuoteScanTests(unittest.TestCase):
    def test_anaheim_synthetic_cross_book_arbitrage_is_shadow_only(self):
        result = scan_nhl_totals([quote("Unibet NL", 2.00, 1.82), quote("Pinnacle", 1.76, 2.17)], NOW)
        self.assertEqual("SHADOW", result.execution_mode)
        self.assertEqual(0, result.recommended_stake_eur)
        self.assertEqual(1, result.candidate_count)
        self.assertAlmostEqual(4.077, result.candidates[0]["theoretical_net_margin_pct"], places=2)

    def test_edmonton_synthetic_same_line_is_shadow_only(self):
        result = scan_nhl_totals([quote("1xBet", 2.17, 1.76), quote("BetOnline", 1.87, 1.99)], NOW)
        self.assertEqual(1, result.candidate_count)
        self.assertEqual(0, result.candidates[0]["recommended_stake_eur"])

    def test_opposite_period_rules_never_compare(self):
        rows = [quote("1xBet", 2.17, 1.76, settlement_scope="REGULATION_60"),
                quote("BetOnline", 1.87, 1.99)]
        result = scan_nhl_totals(rows, NOW)
        self.assertEqual(0, result.candidate_count)
        self.assertTrue(any(r["reason_code"] == "SETTLEMENT_MISMATCH" for r in result.pair_exclusions))

    def test_different_lines_and_main_alternate_never_compare(self):
        rows = [quote("1xBet", 2.17, 1.76, line=6.0),
                quote("BetOnline", 1.87, 1.99)]
        result = scan_nhl_totals(rows, NOW)
        self.assertEqual(0, result.candidate_count)
        self.assertTrue(any(r["reason_code"] == "ALTERNATE_LINE_MISMATCH" for r in result.pair_exclusions))
        rows[0]["line"] = 6.5
        rows[0]["line_role"] = "alternate"
        self.assertEqual(0, scan_nhl_totals(rows, NOW).candidate_count)

    def test_day_only_sheet_is_rejected_not_turned_into_executable_timestamp(self):
        row = quote("Pinnacle", 1.76, 2.17)
        row["source_observed_at"] = "2026-11-01"
        result = scan_nhl_totals([row], NOW)
        self.assertEqual(0, result.eligible_quote_count)
        self.assertEqual(0, result.candidate_count)
        self.assertIn("TIMESTAMP", result.rejections[0]["reason_code"])

    def test_missing_source_capture_or_rule_metadata_is_fail_closed(self):
        for key in ("source_observed_at", "captured_at", "settlement_scope",
                    "settlement_rule_url", "provider_event_id"):
            with self.subTest(key=key):
                row = quote("Pinnacle", 1.76, 2.17)
                del row[key]
                self.assertEqual(0, scan_nhl_totals([row], NOW).eligible_quote_count)

    def test_stale_quotes_block(self):
        result = scan_nhl_totals([quote("Pinnacle", 1.76, 2.17,
                                       source_observed_at="2026-11-01T17:40:00+02:00")], NOW)
        self.assertEqual(0, result.eligible_quote_count)
        self.assertIn("SOURCE_QUOTE_STALE", result.rejections[0]["reason_code"])

    def test_quote_after_start_blocks_even_when_marked_pregame(self):
        row = quote("Pinnacle", 1.76, 2.17,
                    scheduled_start_at="2026-11-01T17:30:00+02:00")
        result = scan_nhl_totals([row], NOW)
        self.assertEqual(0, result.eligible_quote_count)
        self.assertEqual("NOT_PREGAME_AT_EVALUATION", result.rejections[0]["reason_code"])

    def test_unverified_event_identity_and_unknown_fee_block(self):
        self.assertEqual(0, scan_nhl_totals([
            quote("A", 2.0, 1.8, event_identity_verified=False)], NOW).eligible_quote_count)
        self.assertEqual(0, scan_nhl_totals([
            quote("A", 2.0, 1.8, commission_fraction=None)], NOW).eligible_quote_count)

    def test_commission_erases_thin_arbitrage(self):
        rows = [quote("A", 2.0, 1.90, commission_fraction=0.04),
                quote("B", 1.90, 2.0, commission_fraction=0.04)]
        self.assertEqual(0, scan_nhl_totals(rows, NOW).candidate_count)

    def test_superseded_quote_excluded(self):
        row = quote("Pinnacle", 1.76, 2.17)
        older = copy.deepcopy(row)
        older["source_observed_at"] = "2026-11-01T17:51:00+02:00"
        older["captured_at"] = "2026-11-01T17:51:10+02:00"
        older["over_odds"] = 100.0
        result = scan_nhl_totals([older, row, quote("Unibet", 2, 1.82)], NOW)
        self.assertEqual(2, result.eligible_quote_count)
        self.assertEqual(1, result.candidate_count)

    def test_only_one_book_no_cross_book_arbitrage(self):
        result = scan_nhl_totals([quote("Pinnacle", 2.00, 2.17)], NOW)
        self.assertEqual(0, result.candidate_count)


if __name__ == "__main__":
    unittest.main()
