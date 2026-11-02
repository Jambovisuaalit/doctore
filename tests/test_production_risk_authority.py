"""D3 adversarial checks use synthetic signed operator fixtures, never live funds."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

from test_doctore_mcp import model_output, market_snapshot, portfolio_state, risk_policy

ROOT = Path(__file__).resolve().parents[1]


class ProductionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / 'authority'
        self.root.mkdir(mode=0o700)
        (self.root / 'authority.key').write_bytes(secrets.token_bytes(32))
        (self.root / 'authority.key').chmod(0o600)
        self.ledger_path = (self.directory / 'bets.csv').resolve()
        os.environ['DOCTORE_REPO_PATH'] = str(ROOT)
        os.environ['DOCTORE_BET_LOG'] = str(self.ledger_path)
        for name in list(sys.modules):
            if name.startswith('doctore_mcp.'):
                del sys.modules[name]
        self.server = importlib.import_module('doctore_mcp.server')
        self.authority = importlib.import_module('doctore_mcp.risk_authority')
        self.ledger = importlib.import_module('doctore_mcp.ledger')
        self.publisher = importlib.import_module('doctore_mcp.operator_authority')
        self.addCleanup(self.authority.configure)
        self.now = datetime.now(timezone.utc)
        self.params = self.server.DecisionInput(model_output=model_output(), market_snapshot=market_snapshot(), portfolio_state=portfolio_state(), risk_policy=risk_policy(), evaluated_at=self.now.isoformat())
        self.params.market_snapshot['captured_at'] = (self.now-timedelta(seconds=1)).isoformat()
        self.params.market_snapshot['event_start_at'] = (self.now+timedelta(hours=2)).isoformat()
        self.params.model_output['prediction_generated_at'] = (self.now-timedelta(seconds=10)).isoformat()
        self.params.model_output['feature_cutoff_at'] = (self.now-timedelta(seconds=30)).isoformat()
        self.params.model_output['training_cutoff_at'] = (self.now-timedelta(days=1)).isoformat()
        self.params.portfolio_state['captured_at'] = (self.now-timedelta(seconds=1)).isoformat()
        self.params.portfolio_state['exposures'] = dict.fromkeys(self.params.portfolio_state['exposures'], 0)
        self.params.portfolio_state['available_balance'] = 50000
        self.params.portfolio_state['open_positions_count'] = 0
        policy = risk_policy()
        policy['allowed_calibration_statuses'] = ['validated']
        policy['block_unknown_correlation'] = True
        self.policy = {
            'schema_version':'doctore.production-authority.v1', 'policy_id':'synthetic-operator', 'policy_version':'1',
            'valid_from':(self.now-timedelta(minutes=1)).isoformat(), 'expires_at':(self.now+timedelta(hours=1)).isoformat(),
            'currency':'EUR', 'ledger_path_sha256':hashlib.sha256(str(self.ledger_path).encode()).hexdigest(),
            'risk_policy':policy,
            'limits':{'max_bankroll':50000,'max_stake_amount':1000,'max_event_exposure_fraction':0.02,'max_market_exposure_fraction':0.02},
            'providers':{name:['synthetic-reviewed-adapter'] for name in ('market','model','portfolio','context')},
        }
        self.sign_policy()
        self.sign_evidence()
        self.authority.configure('production', str(self.root))

    def sign_policy(self):
        self.publisher.publish(self.root, 'policy', self.policy)

    def sign_evidence(self, **changes):
        evidence = {'schema_version':'doctore.production-evidence.v1','valid_from':(self.now-timedelta(minutes=1)).isoformat(),'expires_at':(self.now+timedelta(minutes=5)).isoformat(),'complete':True,'coverage':'external_only','currency':'EUR',
            'inputs':{name:{'sha256':hashlib.sha256(self.authority._canonical(value)).hexdigest(),'provider':'synthetic-reviewed-adapter','observed_at':self.now.isoformat()} for name,value in {'market':self.params.market_snapshot,'model':self.params.model_output,'portfolio':self.params.portfolio_state,'context':self.params.sport_context}.items()},
            'external_event_exposure_amount':0,'external_market_exposure_amount':0,'closed_ledger_decisions':{}}
        evidence.update(changes)
        self.publisher.publish(self.root, 'evidence', evidence)
        self.evidence = evidence

    def evaluate(self, params=None):
        return asyncio.run(self.server.doctore_evaluate_bet(params or self.params)).decision_output

    def approval(self, decision=None, params=None, stake=None):
        decision = decision or self.evaluate(params)
        return self.server.LogBetInput(evaluation=params or self.params,decision_output=decision,human_decision='APPROVE' if stake is None else 'REDUCE',approved_stake=stake)

    def test_production_authentication_and_research_preservation(self):
        result = self.evaluate()
        self.assertEqual(result['decision'], 'BET')
        self.assertLessEqual(result['staking']['final_stake'], 1000)
        self.assertEqual(result['audit']['risk_authority']['mode'], 'production')
        self.authority.configure()
        research = self.evaluate()
        self.assertNotIn('risk_authority', research['audit'])
        os.environ['DOCTORE_MODE'] = 'production'
        self.assertEqual(self.authority.mode(), 'research')
        os.environ.pop('DOCTORE_MODE')

    def test_permissive_client_policy_cannot_relax_server(self):
        params = self.params.model_copy(deep=True)
        params.risk_policy['caps'] = dict.fromkeys(params.risk_policy['caps'], 1)
        params.risk_policy['kelly_fraction']['validated'] = 1
        params.risk_policy['sizing_model_weight']['validated'] = 1
        params.risk_policy['freshness_seconds'] = dict.fromkeys(params.risk_policy['freshness_seconds'], 999999)
        params.risk_policy['minimum_ev'] = 0
        params.risk_policy['minimum_edge_probability_points'] = 0
        params.risk_policy['block_unknown_correlation'] = False
        result = self.evaluate(params)
        self.assertEqual(result['decision'], 'BET')
        self.assertLessEqual(result['staking']['final_stake'], self.evaluate()['staking']['final_stake'])
        self.assertLessEqual(result['staking']['kelly_fraction'], self.policy['risk_policy']['kelly_fraction']['validated'])

    def test_client_can_be_stricter(self):
        params = self.params.model_copy(deep=True)
        params.risk_policy['caps']['max_stake_fraction_per_bet'] = 0.001
        result = self.evaluate(params)
        self.assertLessEqual(result['staking']['final_stake'], 50)

    def test_forged_bankroll_snapshot_and_currency_fail_closed(self):
        for field,value in [('bankroll',999999),('currency','USD'),('captured_at',(self.now+timedelta(hours=1)).isoformat())]:
            with self.subTest(field=field):
                params=self.params.model_copy(deep=True)
                params.portfolio_state[field]=value
                result=self.evaluate(params)
                self.assertEqual(result['decision'],'BLOCKED')
                self.assertEqual(result['staking']['final_stake'],0)

    def test_signed_stale_provenance_and_incomplete_evidence_fail_closed(self):
        self.evidence['inputs']['market']['observed_at']=(self.now-timedelta(hours=1)).isoformat()
        self.publisher.publish(self.root,'evidence',self.evidence)
        self.assertIn('D3_SOURCE_STALE',self.evaluate()['diagnostics'])
        self.evidence['inputs']['market']['observed_at']=self.now.isoformat()
        self.evidence['complete']=False
        self.publisher.publish(self.root,'evidence',self.evidence)
        self.assertIn('D3_EVIDENCE_INCOMPLETE',self.evaluate()['diagnostics'])

    def test_signature_tampering_and_missing_policy_fail_closed(self):
        path=self.root/'policy.json'
        doc=json.loads(path.read_text());doc['payload']['limits']['max_stake_amount']=999999
        path.write_text(json.dumps(doc));path.chmod(0o600)
        self.assertIn('D3_AUTHORITY_SIGNATURE_INVALID',self.evaluate()['diagnostics'])
        path.unlink()
        self.assertEqual(self.evaluate()['decision'],'BLOCKED')
        self.authority.configure()
        with self.assertRaises(ValueError): self.authority.configure('production',str(self.root))
        self.assertEqual(self.authority.mode(),'research')

    def test_event_market_absolute_caps_and_drawdown(self):
        for key in ['max_stake_amount','max_event_exposure_fraction','max_market_exposure_fraction']:
            with self.subTest(key=key):
                saved=self.policy['limits'][key];self.policy['limits'][key]=0;self.sign_policy()
                self.assertEqual(self.evaluate()['decision'],'BLOCKED')
                self.policy['limits'][key]=saved
        self.sign_policy()
        self.params.portfolio_state['drawdown_fraction']=0.99;self.sign_evidence()
        self.assertEqual(self.evaluate()['decision'],'BLOCKED')

    def test_approval_rotation_idempotency_and_durable_audit(self):
        request=self.approval()
        result=self.ledger.log_bet(request)
        self.assertTrue(result.logged,result.reason)
        replay=self.ledger.log_bet(request)
        self.assertTrue(replay.logged,replay.reason)
        self.assertEqual(replay.reason,'D3_APPROVAL_IDEMPOTENT_REPLAY')
        self.assertEqual(len(self.ledger.read_bet_rows()),1)
        self.assertIn('policy_sha256',self.ledger.read_bet_rows()[0]['risk_authority_json'])
        changed=request.model_copy(deep=True);changed.approved_stake=1;changed.human_decision=self.server.HumanDecision.REDUCE
        self.assertFalse(self.ledger.log_bet(changed).logged)
        self.policy['policy_version']='2';self.policy['limits']['max_stake_amount']=1;self.sign_policy()
        other=self.params.model_copy(deep=True);other.evaluated_at=(self.now+timedelta(seconds=1)).isoformat()
        old=self.approval(decision=request.decision_output,params=other)
        self.assertFalse(self.ledger.log_bet(old).logged)

    def test_policy_rotation_between_decision_and_approval(self):
        request=self.approval()
        self.policy['policy_version']='2';self.policy['limits']['max_stake_amount']=1;self.sign_policy()
        result=self.ledger.log_bet(request)
        self.assertFalse(result.logged)
        self.assertEqual(self.ledger.read_bet_rows(),[])

    def test_concurrent_retries_never_double_write(self):
        request=self.approval()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.ledger.log_bet(request),range(4)))
        self.assertTrue(all(r.logged for r in results),[r.reason for r in results])
        self.assertEqual(len(self.ledger.read_bet_rows()),1)
        self.assertLessEqual(sum(float(r['approved_stake']) for r in self.ledger.read_bet_rows()),1000)

    def test_concurrent_distinct_approvals_cannot_oversubscribe(self):
        requests=[self.approval() for _ in range(4)]
        self.assertEqual(len({r.decision_output['decision_id'] for r in requests}),4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(self.ledger.log_bet,requests))
        rows=self.ledger.read_bet_rows()
        self.assertEqual(sum(r.logged for r in results),1,[r.reason for r in results])
        self.assertLessEqual(sum(float(row['approved_stake']) for row in rows),1000)

    def test_operator_rotation_waits_for_shared_approval_lock(self):
        from threading import Event
        started=Event()
        def rotate():
            started.set()
            self.sign_policy()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.ledger.log_lock():
                future=pool.submit(rotate)
                self.assertTrue(started.wait(2))
                from concurrent.futures import TimeoutError
                with self.assertRaises(TimeoutError): future.result(timeout=0.05)
            future.result(timeout=2)

    def test_retry_after_atomic_replace_failure(self):
        from unittest.mock import patch
        request=self.approval()
        with patch('doctore_mcp.ledger.os.replace',side_effect=OSError('synthetic precommit failure')):
            with self.assertRaises(OSError): self.ledger.log_bet(request)
        self.assertEqual(self.ledger.read_bet_rows(),[])
        self.assertTrue(self.ledger.log_bet(request).logged)
        self.assertEqual(len(self.ledger.read_bet_rows()),1)

    def test_quality_gate_cannot_extend_production_freshness(self):
        params=self.server.QualityGateInput(snapshot_at=(self.now-timedelta(hours=1)).isoformat(),max_age_minutes=9999)
        result=asyncio.run(self.server.doctore_check_data_quality(params))
        self.assertEqual(result.status,'BLOCKED')

    def test_unverified_settlement_does_not_release_capacity(self):
        request=self.approval();result=self.ledger.log_bet(request)
        self.assertTrue(result.logged,result.reason)
        rows=self.ledger.read_bet_rows();rows[0]['result']='void';rows[0]['placement_status']='PLACED';rows[0]['actual_stake']='1'
        self.ledger.write_bet_rows(rows)
        # A caller-reported void or smaller execution cannot erase approved risk.
        next_decision=self.evaluate()
        self.assertEqual(next_decision['decision'],'BLOCKED')
        self.assertEqual(next_decision['reason_codes'],['D3_EXPOSURE_LIMIT'])

    def test_backdated_claimed_placement_cannot_release_turnover(self):
        self.policy['limits']['max_event_exposure_fraction']=1
        self.policy['limits']['max_market_exposure_fraction']=1
        self.policy['limits']['max_stake_amount']=100
        self.policy['risk_policy']['caps']['max_daily_turnover_fraction']=0.002
        self.policy['risk_policy']['caps']['max_rolling_3d_turnover_fraction']=0.002
        self.sign_policy()
        first=self.approval();self.assertTrue(self.ledger.log_bet(first).logged)
        rows=self.ledger.read_bet_rows()
        rows[0]['placement_status']='PLACED'
        rows[0]['actual_stake']='1'
        rows[0]['placed_at']=(self.now-timedelta(days=10)).isoformat()
        self.ledger.write_bet_rows(rows)
        decision=self.evaluate()
        self.assertNotEqual(decision['decision'],'BET')
        self.assertEqual(decision['staking']['caps']['daily'],0)
        self.assertEqual(decision['staking']['caps']['rolling_3d'],0)
        self.assertEqual(float(self.ledger.read_bet_rows()[0]['approved_stake']),100)
        self.assertEqual(self.ledger.read_bet_rows()[0]['placed_at'],rows[0]['placed_at'])

    def test_authenticated_production_over_real_stdio(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def call():
            server=StdioServerParameters(command=sys.executable,args=[str(ROOT/'doctore_mcp/launch.py'),'--bet-log',str(self.ledger_path),'--mode','production','--authority-root',str(self.root)],env=dict(os.environ))
            async with stdio_client(server) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools),14)
                    result=await session.call_tool('doctore_evaluate_bet',{'params':self.params.model_dump(mode='json')})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent['execution_mode'],'production')
                    self.assertEqual(result.structuredContent['decision_output']['audit']['risk_authority']['mode'],'production')
                    self.assertEqual(result.structuredContent['decision_output']['decision'],'BET')
        asyncio.run(call())
        self.assertFalse(self.ledger_path.exists())

    def test_private_permissions_and_cli_mode_override(self):
        (self.root/'authority.key').chmod(0o644)
        self.assertEqual(self.evaluate()['decision'],'BLOCKED')
        result=subprocess.run([sys.executable,'-m','doctore_mcp','--mode','production','--bet-log',str(self.ledger_path),'--check'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('--authority-root',result.stderr)

if __name__ == '__main__': unittest.main()
