from datetime import datetime
from pathlib import Path
import os
import runpy
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from doctore_mcp.tennis_data import TennisDataInput, fetch_tennis_data


class KeylessTennisTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ, {"DOCTORE_TENNIS_MODE":"research", "SPORTRADAR_API_KEY":"",
                                  "SPORTRADAR_ACCESS_LEVEL":"", "DOCTORE_TENNIS_OFFLINE":"1"})
        env.start(); self.addCleanup(env.stop)
        helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tests/test_doctore_mcp.py"))
        self.market=helpers["market_snapshot"](odds=2.0)
        self.market.update(sport="TENNIS",competition="ATP")
        self.market["outcomes"][1]["decimal_odds"]=2.0
        self.now=datetime.fromisoformat("2026-07-24T11:00:00+03:00")

    def analyze(self, market=None):
        return fetch_tennis_data(TennisDataInput(command="analyze_supplied_market",tour="atp",
            market_snapshot=market or self.market),clock=lambda:self.now)

    def test_default_capabilities_need_no_key_package_or_network(self):
        with patch.dict(os.environ,clear=False) as env:
            env.pop("DOCTORE_TENNIS_MODE",None)
            with patch("doctore_mcp.tennis_data.version",side_effect=AssertionError("local command must not import provider")):
                result=fetch_tennis_data(TennisDataInput(command="get_capabilities",tour="atp"))
        self.assertEqual("OK",result.status)
        self.assertEqual("research",result.data["mode"])
        self.assertFalse(result.data["api_key_required"])
        self.assertFalse(result.data["live_decisions_enabled"])
        self.assertTrue(result.research_only)

    def test_timestamped_supplied_odds_return_only_price_vector_baseline(self):
        result=self.analyze()
        self.assertEqual("OK",result.status)
        self.assertEqual(.5,result.data["market_baseline"]["no_vig_probability"])
        self.assertEqual(0,result.data["market_baseline"]["overround"])
        self.assertEqual("price_vector_only",result.data["scope"])
        for key in ("model_probability","stake","recommendation"):
            self.assertIsNone(result.data[key])
        self.assertFalse(result.event_freshness_verified)
        self.assertFalse(result.recommendation_available)
        self.assertFalse(result.data["settlement_payoff_verified"])
        self.assertFalse(result.data["executable_price_verified"])

    def test_stale_future_incomplete_and_nonfinite_prices_are_blocked(self):
        from copy import deepcopy
        for change in ({"captured_at":"2026-07-24T10:00:00+03:00"},
                       {"captured_at":"2026-07-24T11:01:00+03:00"},
                       {"is_complete":False},{"market_status":"suspended"},
                       {"sport":"MLB"}):
            market=deepcopy(self.market);market.update(change)
            self.assertEqual("BLOCKED",self.analyze(market).status)
        market=deepcopy(self.market);market["outcomes"][1]["decimal_odds"]=float("inf")
        self.assertEqual("BLOCKED",self.analyze(market).status)
        market=deepcopy(self.market);market.pop("captured_at")
        self.assertEqual("BLOCKED",self.analyze(market).status)

    def test_command_parameters_do_not_leak_to_background_provider(self):
        with self.assertRaises(ValidationError):
            TennisDataInput(command="get_scoreboard",tour="atp",market_snapshot=self.market)
        with self.assertRaises(ValidationError):
            TennisDataInput(command="analyze_supplied_market",tour="atp")

    def test_paid_provider_is_disabled_even_with_a_key_in_research_mode(self):
        from doctore_mcp.tennis_verification import acquire, VerificationError
        with patch.dict(os.environ,{"SPORTRADAR_API_KEY":"synthetic-test-key","SPORTRADAR_ACCESS_LEVEL":"trial"}):
            with patch("doctore_mcp.tennis_verification.fetch_summary") as fetch:
                with self.assertRaisesRegex(VerificationError,"PAID_PROVIDER_DISABLED"):
                    acquire("Pinnacle","test",allow_live_fetch=True)
                fetch.assert_not_called()
