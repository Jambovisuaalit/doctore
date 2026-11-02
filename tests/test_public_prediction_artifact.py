"""The public artifact contract must be usable through real MCP without source discovery."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from jsonschema import Draft202012Validator, FormatChecker

ROOT=Path(__file__).resolve().parents[1]

class PublicArtifactTests(unittest.TestCase):
    def test_complete_contract_and_loader_via_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory);artifacts=temp/'artifacts';artifacts.mkdir()
            ledger=temp/'private/bets.csv'
            sample=json.loads((ROOT/'examples/public_prediction_artifact.json').read_text())
            env={k:v for k,v in os.environ.items() if not k.startswith('DOCTORE_')}
            env.update(DOCTORE_REPO_PATH=str(ROOT),DOCTORE_BET_LOG=str(ledger),DOCTORE_MODEL_ARTIFACT_ROOT=str(artifacts),DOCTORE_TENNIS_OFFLINE='1')
            async def inspect():
                async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'doctore_mcp/server.py')],env=env)) as (reader,writer):
                    async with ClientSession(reader,writer) as session:
                        await session.initialize()
                        catalog=await session.list_tools()
                        self.assertEqual(len(catalog.tools),14)
                        tool=next(t for t in catalog.tools if t.name=='doctore_load_model_prediction')
                        schema=tool.inputSchema
                        node=schema['properties']['params']
                        if '$ref' in node:node=schema['$defs'][node['$ref'].split('/')[-1]]
                        public=node['properties']['prediction_path']['x-doctore-artifact-schema']
                        Draft202012Validator.check_schema(public)
                        self.assertEqual(list(Draft202012Validator(public,format_checker=FormatChecker()).iter_errors(sample)),[])
                        self.assertIn('probability_selected_raw',public['properties']['calibration']['required'])
                        async def load(document,name='artifact.json',raw=None):
                            path=artifacts/name
                            path.write_text(json.dumps(document) if raw is None else raw)
                            result=await session.call_tool('doctore_load_model_prediction',{'params':{'prediction_path':str(path),'market_id':'public-synthetic-market','competition':'WNBA','target_market':'full_game_moneyline','settlement_rules':'full_game_including_overtime'}})
                            self.assertFalse(result.isError)
                            return result.structuredContent
                        valid=await load(sample)
                        self.assertTrue(valid['ok'],valid['error'])
                        self.assertEqual(valid['model_output']['probability_raw'],0.58)
                        self.assertEqual(valid['model_output']['probability_calibrated'],0.57)
                        self.assertEqual(valid['model_output']['model_artifact_sha256'],sample['model']['model_artifact_sha256'])
                        missing=deepcopy(sample);del missing['calibration']['probability_selected_raw']
                        invalid=await load(missing)
                        self.assertFalse(invalid['ok']);self.assertIn('calibration',invalid['error']);self.assertIn('probability_selected_raw',invalid['error'])
                        stripped=deepcopy(sample);del stripped['validation']
                        self.assertFalse((await load(stripped))['ok'])
                        degraded=deepcopy(sample);degraded['calibration']['status']='degraded'
                        self.assertEqual((await load(degraded))['model_output']['calibration_status'],'unknown')
                        nonfinite=json.dumps(sample).replace('0.58','NaN')
                        self.assertFalse((await load(sample,raw=nonfinite))['ok'])
                        self.assertFalse((await load([]))['ok'])
            asyncio.run(inspect())
            self.assertFalse(ledger.exists())

if __name__=='__main__':unittest.main()
