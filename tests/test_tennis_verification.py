"""Provider-shaped fixtures are synthetic; no real feed readiness claim."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DOCTORE_REPO_PATH", str(ROOT))
os.environ.setdefault("DOCTORE_BET_LOG", str(Path(tempfile.gettempdir())/"tennis-verification-test.csv"))
from doctore_mcp import tennis_verification as verification
from src.tennis_event_gate import validate_tennis_event


class TennisVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026,10,15,10,tzinfo=timezone.utc)
        self.mapping = dict(source="sportradar", source_event_id="sr:sport_event:123", book="test-book",
            book_event_id="book-event-1", book_market_id="book-market-1", canonical_event_id="canonical-1",
            tour="atp", format="singles", tournament_id="sr:competition:1", round="round_of_16",
            event_start_at="2026-10-15T12:00:00Z", source_player_ids=["sr:competitor:1","sr:competitor:2"],
            book_player_ids=["book-player-1","book-player-2"], status="APPROVED", reviewer="fixture reviewer",
            valid_until="2026-10-15T11:00:00Z")
        self.market = dict(book=self.mapping["book"], book_market_id=self.mapping["book_market_id"],
            event_id="canonical-1", event_start_at=self.mapping["event_start_at"])
        self.payload = dict(generated_at="2026-10-15T09:59:30Z", sport_event=dict(id="sr:sport_event:123",
            start_time=self.mapping["event_start_at"], start_time_confirmed=True,
            sport_event_context=dict(category=dict(name="ATP"), competition=dict(id="sr:competition:1",type="singles"),round=dict(name="round_of_16")),
            competitors=[dict(id="sr:competitor:2",qualifier="away"),dict(id="sr:competitor:1",qualifier="home")]),
            sport_event_status=dict(status="not_started",match_status="not_started"))
        self.registry = Path(self.temp.name)/"registry.json"
        self.registry.write_text(json.dumps({"schema_version":"doctore.tennis-identity-registry.v1","mappings":[self.mapping]}))
        self.db = Path(self.temp.name)/"evidence.sqlite3"
        env = patch.dict(os.environ, {"DOCTORE_TENNIS_IDENTITY_REGISTRY":str(self.registry),
            "DOCTORE_TENNIS_EVIDENCE_DB":str(self.db),"SPORTRADAR_API_KEY":"synthetic-test-key",
            "SPORTRADAR_ACCESS_LEVEL":"trial"})
        env.start()
        self.addCleanup(env.stop)

    def acquire(self, payload=None):
        with patch.object(verification,"fetch_summary",return_value=payload or self.payload) as fetch:
            result=verification.acquire("test-book","book-market-1",allow_live_fetch=True,clock=lambda:self.now)
        self.assertEqual(1,fetch.call_count)
        return result

    def test_provider_snapshot_time_is_not_fabricated_event_change_time(self):
        result=self.acquire()
        self.assertIsNone(result["source_updated_at"])
        self.assertEqual(self.payload["generated_at"],result["provider_generated_at"])
        context=verification.verified_context(self.market,self.now.isoformat())
        self.assertEqual([],validate_tennis_event(context,self.market,self.now.isoformat()))
        self.assertEqual(result,context["tennis_event"])

    def test_missing_credentials_or_opt_in_never_calls_provider(self):
        with patch.object(verification,"fetch_summary") as fetch:
            with self.assertRaisesRegex(verification.VerificationError,"EXPLICIT_FETCH"):
                verification.acquire("test-book","book-market-1")
            with patch.dict(os.environ,{"SPORTRADAR_API_KEY":""}):
                with self.assertRaisesRegex(verification.VerificationError,"CREDENTIALS_REQUIRED"):
                    verification.acquire("test-book","book-market-1",allow_live_fetch=True)
            fetch.assert_not_called()

    def test_stale_future_snapshot_and_request_time_substitution_rejected(self):
        for stamp in ("2026-10-15T09:00:00Z","2026-10-15T10:01:00Z",None):
            payload=deepcopy(self.payload)
            payload["generated_at"]=stamp
            with self.assertRaises(verification.VerificationError):
                self.acquire(payload)
        self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))

    def test_identity_status_and_doubles_mismatches_invalidate_old_success(self):
        changes=[lambda p:p["sport_event"].update(id="sr:sport_event:999"),
            lambda p:p["sport_event_status"].update(status="live",match_status="1st_set"),
            lambda p:p["sport_event"].update(start_time_confirmed=False),
            lambda p:p["sport_event"]["sport_event_context"]["competition"].update(type="doubles"),
            lambda p:p["sport_event"]["competitors"][0].update(virtual=True),
            lambda p:p["sport_event"].update(replaced_by="sr:sport_event:999")]
        for change in changes:
            self.acquire()
            payload=deepcopy(self.payload)
            change(payload)
            with self.assertRaises(verification.VerificationError):
                self.acquire(payload)
            self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))

    def test_transport_failure_invalidates_cached_success_and_redacts_error(self):
        self.acquire()
        with patch.object(verification,"fetch_summary",side_effect=verification.VerificationError("TENNIS_PROVIDER_REQUEST_FAILED")):
            with self.assertRaises(verification.VerificationError):
                verification.acquire("test-book","book-market-1",allow_live_fetch=True,clock=lambda:self.now)
        self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))

    def test_cache_expiry_mapping_change_and_payload_tamper_block(self):
        self.acquire()
        self.assertNotIn("tennis_event",verification.verified_context(self.market,(self.now+timedelta(minutes=3)).isoformat()))
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET payload='{}'")
        self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))
        self.acquire()
        self.mapping["round"]="quarterfinal"
        self.registry.write_text(json.dumps({"schema_version":"doctore.tennis-identity-registry.v1","mappings":[self.mapping]}))
        self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))

    def test_mcp_never_accepts_caller_timestamp_without_acquired_evidence(self):
        from doctore_mcp.decision_adapter import run_decision
        from doctore_mcp.schemas import DecisionInput
        helpers=runpy.run_path(str(ROOT/"tests/test_doctore_mcp.py"))
        model,market=helpers["model_output"](),helpers["market_snapshot"]()
        for v in (model,market,model["validation_domain"]):
            v.update(sport="TENNIS",competition="ATP")
        portfolio=helpers["portfolio_state"](); portfolio["league"]="ATP"
        params=DecisionInput(model_output=model,market_snapshot=market,portfolio_state=portfolio,
            risk_policy=helpers["risk_policy"](),evaluated_at="2026-07-24T11:00:00+03:00",
            sport_context={"tennis_event":{"source_updated_at":"2026-07-24T11:00:00+03:00"}})
        result=run_decision(params)
        self.assertEqual("BLOCKED",result["decision"])
        self.assertIn("TENNIS_EVENT_EVIDENCE_MISSING",result["reason_codes"])

    def test_transport_rejects_redirect_and_redacts_credentials(self):
        with self.assertRaisesRegex(verification.VerificationError,"REDIRECT_REJECTED"):
            verification.NoRedirect().redirect_request(None,None,None,None,None,None)
        with patch.object(verification,"build_opener",side_effect=RuntimeError("secret-value")):
            with self.assertRaises(verification.VerificationError) as result:
                verification.fetch_summary("sr:sport_event:123","secret-value","trial")
        self.assertEqual("TENNIS_PROVIDER_REQUEST_FAILED",str(result.exception))

    def test_failed_payload_persistence_does_not_restore_prior_success(self):
        self.acquire()
        original = verification.store_observation
        calls = []
        def failing_store(*args):
            calls.append(args)
            if len(calls) == 1:
                return original(*args)
            raise OSError("fixture disk failure after acquisition started")
        with patch.object(verification,"store_observation",side_effect=failing_store):
            with self.assertRaises(OSError):
                self.acquire()
        self.assertNotIn("tennis_event",verification.verified_context(self.market,self.now.isoformat()))

    def test_new_request_blocks_old_evidence_before_source_returns(self):
        self.acquire()
        def source(*args):
            self.assertNotIn("tennis_event", verification.verified_context(self.market,self.now.isoformat()))
            return self.payload
        with patch.object(verification,"fetch_summary",side_effect=source):
            verification.acquire("test-book","book-market-1",allow_live_fetch=True,clock=lambda:self.now)
        self.assertIn("tennis_event", verification.verified_context(self.market,self.now.isoformat()))
