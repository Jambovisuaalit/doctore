"""Synthetic quotes only: never contact a price provider."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch, Mock
from doctore_mcp.tennis_odds import import_quotes, compare_quotes, decimal_price, fetch_once, OddsError
from doctore_mcp.tennis_data import TennisDataInput, fetch_tennis_data


class TennisOddsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
        self.data = dict(source_format="copied_table", raw_table="Player A\t1,91\nPlayer B\t2.05",
            captured_at=self.now.isoformat(), event_start_at="2026-10-15T12:00:00Z",
            book="book-a", book_event_id="123", competition="ATP example",
            settlement_rules="one_completed_set", price_format="decimal",
            source_url="https://example.com/tennis/123", event_reference="asserted-event")

    def snapshots(self, data=None):
        return import_quotes(data or self.data, "atp", self.now)["snapshots"]

    def test_copied_prices_complete_pair_without_fabricated_book_market_id(self):
        snapshots = self.snapshots()
        self.assertEqual([1.91, 2.05], [s["decimal_odds"] for s in snapshots])
        self.assertEqual(2, len(snapshots[0]["outcomes"]))
        self.assertNotIn("book_market_id", snapshots[0])
        data = dict(self.data, raw_table="Player A\n-110\nPlayer B\n+105", price_format="american")
        self.assertAlmostEqual(1 + 100/110, self.snapshots(data)[0]["decimal_odds"])

    def test_bad_formats_times_sources_and_incomplete_pairs_rejected(self):
        for change in [dict(raw_table="Player A\t2"), dict(raw_table="A\t2\nA\t2"),
                       dict(raw_table="A\tNaN\nB\t2"),dict(captured_at="2026-10-15T08:54:59Z"),
                       dict(captured_at="2026-10-15T09:00:01Z"),dict(captured_at="2026-10-15T09:00:00"),
                       dict(event_start_at="2026-10-15T08:00:00Z"),dict(source_url="https://example.com/?apiKey=secret")]:
            with self.subTest(change=change), self.assertRaises(OddsError):
                self.snapshots(dict(self.data, **change))
        for price in [True, "inf", "NaN", "1", "-110", "2,0.1"]:
            with self.assertRaises(OddsError): decimal_price(price, "decimal")

    def api(self):
        return dict(source_format="odds_api_v4",price_format="decimal",payload=[dict(id="e1",
            sport_key="tennis_atp_example",commence_time="2026-10-15T12:00:00Z",home_team="A",away_team="B",
            bookmakers=[dict(key="book-a",last_update="2026-10-15T08:59:30Z",markets=[dict(key="h2h",
                outcomes=[dict(name="A",price=1.9),dict(name="B",price=2.1)])])])])

    def test_api_preserves_source_time_and_unverified_rules(self):
        result=import_quotes(self.api(),"atp",self.now)
        self.assertEqual([],result["rejected"])
        self.assertEqual("2026-10-15T08:59:30+00:00",result["snapshots"][0]["captured_at"])
        self.assertEqual("unverified",result["snapshots"][0]["settlement_rules"])
        self.assertNotIn("book_market_id",result["snapshots"][0])
        self.assertFalse(result["identity_verified"])

    def test_api_missing_time_wrong_participants_tour_and_duplicates(self):
        for kind in ("time","participants","tour","duplicate"):
            data=self.api(); event=data["payload"][0]; book=event["bookmakers"][0]
            if kind=="time": book.pop("last_update")
            if kind=="participants": book["markets"][0]["outcomes"][0]["name"]="Other"
            if kind=="tour": event["sport_key"]="tennis_wta_example"
            if kind=="duplicate": event["bookmakers"].append(deepcopy(book))
            result=import_quotes(data,"atp",self.now)
            self.assertFalse(result["snapshots"],kind)
            self.assertTrue(result["rejected"],kind)

    def comparison(self):
        a=self.snapshots()[0]
        b=self.snapshots(dict(self.data,book="book-b",raw_table="Player A\t2.0\nPlayer B\t1.9"))[0]
        return [a,b]

    def test_compare_exact_same_selection_only_and_no_recommendation(self):
        result=compare_quotes(self.comparison(),self.now)
        self.assertEqual("book-b",result["best_observed_book"])
        self.assertIsNone(result["recommendation"])
        self.assertIsNone(result["stake"])
        for field,value in [("settlement_rules","unverified"),("event_id","other"),
                            ("captured_at","2026-10-15T08:58:59Z"),
                            ("event_start_at","2026-10-15T08:00:00Z")]:
            quotes=self.comparison();quotes[1][field]=value
            with self.subTest(field=field), self.assertRaises(OddsError): compare_quotes(quotes,self.now)
        with self.assertRaises(OddsError): compare_quotes(self.snapshots(),self.now)

    def test_latest_complete_pair_and_same_time_conflict(self):
        quotes=self.comparison();old=deepcopy(quotes[1]);old["captured_at"]="2026-10-15T08:59:30Z"
        result=compare_quotes([old]+quotes,self.now)
        self.assertEqual(2,len(result["quotes"]))
        conflict=deepcopy(quotes[1]);conflict["source"]="conflicting-source"
        with self.assertRaisesRegex(OddsError,"CONFLICTING"): compare_quotes(quotes+[conflict],self.now)

    def test_local_mcp_commands_do_not_load_provider(self):
        with patch("doctore_mcp.tennis_data.version",side_effect=AssertionError("network/provider forbidden")):
            result=fetch_tennis_data(TennisDataInput(command="import_odds",tour="atp",odds_import=self.data),clock=lambda:self.now)
            self.assertEqual("OK",result.status)
            result=fetch_tennis_data(TennisDataInput(command="compare_odds",tour="atp",comparison_snapshots=self.comparison()),clock=lambda:self.now)
            self.assertEqual("OK",result.status)
            self.assertFalse(result.recommendation_available)

    def test_credit_guard_prevents_network_and_transport_errors_are_redacted(self):
        # Other repository tests reload modules. Patch this function's own
        # globals so a stale imported function can never escape the mock.
        opener = Mock()
        with patch.dict(fetch_once.__globals__, build_opener=opener):
            with self.assertRaisesRegex(OddsError,"CREDIT_APPROVAL_REQUIRED"): fetch_once("tennis_atp_example")
            opener.assert_not_called()
            with patch.dict("os.environ",{"ODDS_API_KEY":"synthetic-secret"}):
                opener.return_value.open.side_effect=RuntimeError("url contains synthetic-secret")
                with self.assertRaisesRegex(OddsError,"^TENNIS_ODDS_REQUEST_FAILED$"):
                    fetch_once("tennis_atp_example",allow_one_credit=True)
                url=opener.return_value.open.call_args.args[0].full_url
                self.assertIn("regions=eu&markets=h2h&oddsFormat=decimal&dateFormat=iso",url)
                self.assertEqual(1,opener.return_value.open.call_count)
