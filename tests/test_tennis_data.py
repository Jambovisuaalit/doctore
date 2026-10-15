from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from pydantic import ValidationError
from doctore_mcp.tennis_data import TennisDataInput, fetch_tennis_data


class TennisDataTests(unittest.TestCase):
    def test_tour_and_supported_command_are_required(self):
        for params in ({"command": "get_scoreboard"}, {"command": "get_head_to_head", "tour": "atp"}):
            with self.assertRaises(ValidationError):
                TennisDataInput(**params)

    def test_calendar_year_comes_from_clock_and_preserves_provenance(self):
        calls = []
        def calendar(**kwargs):
            calls.append(kwargs)
            return {"status": True, "data": {"tour": "WTA", "tournaments": []}}
        result = fetch_tennis_data(TennisDataInput(command="get_calendar", tour="wta"),
            provider=SimpleNamespace(get_calendar=calendar),
            clock=lambda: datetime(2031, 1, 1, tzinfo=timezone.utc))
        self.assertEqual([{"tour": "wta", "year": 2031}], calls)
        self.assertEqual("OK", result.status)
        self.assertFalse(result.event_freshness_verified)
        self.assertIsNone(result.source_updated_at)

    def test_failure_shape_and_wrong_tour_are_blocked(self):
        for response in ({"status": False, "data": None},
                         {"status": True, "data": {"rankings": "broken"}},
                         {"status": True, "data": {"tour": "WTA", "rankings": []}}):
            provider = SimpleNamespace(get_rankings=lambda **_: response)
            result = fetch_tennis_data(TennisDataInput(command="get_rankings", tour="atp"), provider=provider)
            self.assertEqual("BLOCKED", result.status)
            self.assertIsNone(result.data)

    def test_player_uses_reviewed_signature_and_exact_id(self):
        calls = []
        def player(**kwargs):
            calls.append(kwargs)
            return {"status": True, "data": {"id": "3782", "name": "Fixture Player"}}
        result = fetch_tennis_data(TennisDataInput(command="get_player_info", tour="atp", player_id="3782"),
                                  provider=SimpleNamespace(get_player_info=player))
        self.assertEqual("OK", result.status)
        self.assertEqual([{"player_id": "3782"}], calls)

    def test_incomplete_ranking_identity_is_blocked(self):
        provider = SimpleNamespace(get_rankings=lambda **_: {
            "status": True, "data": {"tour": "ATP", "rankings": [{"id": "3623", "name": ""}]}})
        result = fetch_tennis_data(TennisDataInput(command="get_rankings", tour="atp"), provider=provider)
        self.assertEqual(["TENNIS_RANKING_IDENTITY_INCOMPLETE"], result.reason_codes)
        self.assertIsNone(result.data)

    def test_extra_parameters_are_rejected(self):
        with self.assertRaises(ValidationError):
            TennisDataInput(command="get_scoreboard", tour="atp", year=2031)


class TennisTransportTests(unittest.TestCase):
    def test_espn_http_reference_is_upgraded_without_changing_identity(self):
        from doctore_mcp.tennis_data import _https_espn_reference
        self.assertEqual("https://sports.core.api.espn.com/v2/athletes/123?lang=en",
            _https_espn_reference("http://sports.core.api.espn.com/v2/athletes/123?lang=en"))
        for url in ("http://evil.example/", "http://sports.core.api.espn.com.evil.example/",
                    "https://sports.core.api.espn.com/x", "http://user@sports.core.api.espn.com/x"):
            self.assertEqual(url, _https_espn_reference(url))

    def test_network_disabled_and_deadline_are_explicit(self):
        from unittest.mock import patch
        from doctore_mcp.tennis_data import fetch_tennis_data, PROVIDER_VERSION
        params = TennisDataInput(command="get_scoreboard", tour="atp")
        with patch.dict("os.environ", {"DOCTORE_TENNIS_OFFLINE": "1"}):
            self.assertEqual(["TENNIS_NETWORK_DISABLED"], fetch_tennis_data(params).reason_codes)
        with patch.dict("os.environ", {"DOCTORE_TENNIS_OFFLINE": "0"}), \
             patch("doctore_mcp.tennis_data.version", return_value=PROVIDER_VERSION), \
             patch("doctore_mcp.tennis_data._bounded_source_call", side_effect=TimeoutError):
            self.assertEqual(["TENNIS_SOURCE_TIMEOUT"], fetch_tennis_data(params).reason_codes)
