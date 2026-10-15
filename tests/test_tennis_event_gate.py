from copy import deepcopy
import unittest
from src.tennis_event_gate import validate_tennis_event


class TennisIdentityTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-10-15T10:00:00Z"
        self.market = dict(book="test", book_market_id="book-1", event_id="canonical-1", event_start_at="2026-10-15T12:00:00Z")
        event = dict(book_event_id="book-event-1", source="test-provider", source_event_id="source-1", tour="atp", format="singles",
                     tournament_id="t1", round="R16", event_start_at=self.market["event_start_at"],
                     source_player_ids=["a", "b"], book_player_ids=["x", "y"], status="scheduled",
                     source_updated_at="2026-10-15T09:59:00Z", received_at=self.now)
        mapping = dict(event, book="test", book_market_id="book-1", canonical_event_id="canonical-1",
                       status="APPROVED", reviewer="fixture", valid_until="2026-10-15T11:00:00Z")
        self.context = dict(tennis_event=event, identity_registry={"mappings": [mapping]})

    def test_exact_mapping_and_event_update_pass(self):
        self.assertEqual([], validate_tennis_event(self.context, self.market, self.now))

    def test_request_time_does_not_prove_freshness(self):
        self.context["tennis_event"].pop("source_updated_at")
        self.assertIn("TENNIS_EVENT_FRESHNESS_UNVERIFIED", validate_tennis_event(self.context, self.market, self.now))

    def test_stale_future_reversed_players_and_doubles_block(self):
        for changes in ({"source_updated_at": "2026-10-15T09:00:00Z"},
                        {"source_updated_at": "2026-10-15T10:01:00Z"},
                        {"source_player_ids": ["b", "a"]}, {"format": "doubles"},
                        {"status": "in_progress"}, {"round": "QF"}):
            context = deepcopy(self.context)
            context["tennis_event"].update(changes)
            self.assertTrue(validate_tennis_event(context, self.market, self.now))

    def test_ambiguous_mapping_expired_and_no_mapping_block(self):
        for mappings in ([], self.context["identity_registry"]["mappings"] * 2,
                         [dict(self.context["identity_registry"]["mappings"][0], valid_until="2026-10-15T09:00:00Z")]):
            context = deepcopy(self.context)
            context["identity_registry"]["mappings"] = mappings
            self.assertTrue(validate_tennis_event(context, self.market, self.now))

    def test_core_blocks_tennis_without_evidence_and_mcp_ignores_injected_registry(self):
        import os
        from pathlib import Path
        import runpy
        import tempfile
        from unittest.mock import patch
        root = Path(__file__).resolve().parents[1]
        helpers = runpy.run_path(str(root / "tests/test_doctore_mcp.py"))
        from doctore_mcp.schemas import DecisionInput, schema_errors
        from doctore_mcp.decision_adapter import run_decision
        model, market = helpers["model_output"](), helpers["market_snapshot"]()
        for value in (model, market, model["validation_domain"]):
            value.update(sport="TENNIS", competition="ATP")
        portfolio = helpers["portfolio_state"]()
        portfolio["league"] = "ATP"
        params = DecisionInput(model_output=model, market_snapshot=market, portfolio_state=portfolio,
            risk_policy=helpers["risk_policy"](), evaluated_at="2026-07-24T11:00:00+03:00")
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"DOCTORE_TENNIS_IDENTITY_REGISTRY": str(Path(temp)/"absent.json")}):
                output = run_decision(params)
                self.assertEqual("BLOCKED", output["decision"])
                self.assertEqual(["TENNIS_EVENT_EVIDENCE_MISSING"], output["reason_codes"])
                self.assertEqual([], schema_errors("decision", output))
                params.sport_context = self.context
                output = run_decision(params)
                self.assertEqual(["TENNIS_IDENTITY_UNVERIFIED"], output["reason_codes"])
                self.assertIsNone(output["staking"]["final_stake"])
