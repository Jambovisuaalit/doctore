"""Exercise public discovery and the documented launcher via a real MCP client."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]


class DiscoveryTests(unittest.TestCase):
    def test_launcher_and_discovery_from_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / 'private' / 'bets.csv'
            env = dict(os.environ)
            env.pop('DOCTORE_BET_LOG', None)
            env.pop('DOCTORE_REPO_PATH', None)
            command = [sys.executable, str(REPO / 'doctore_mcp/launch.py'), '--bet-log', str(ledger)]
            config = json.loads(subprocess.check_output(command + ['--print-config'], cwd=directory, env=env))
            entry = config['mcpServers']['doctore']
            check = json.loads(subprocess.check_output(command + ['--check'], cwd=directory, env=env))
            self.assertEqual(len(check['tools']), 14)
            self.assertIn('review_market', check['prompts'])
            self.assertFalse(ledger.parent.exists())

            async def inspect():
                server = StdioServerParameters(command=entry['command'], args=entry['args'], env=env, cwd=directory)
                async with stdio_client(server) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        self.assertEqual(len((await session.list_tools()).tools), 14)
                        resources = await session.list_resources()
                        self.assertIn('doctore://workflow', [str(r.uri) for r in resources.resources])
                        workflow = await session.read_resource('doctore://workflow')
                        self.assertIn('must not invent', workflow.contents[0].text)
                        index = await session.read_resource('doctore://contracts')
                        names = json.loads(index.contents[0].text)['contracts']
                        self.assertTrue(names)
                        schema = await session.read_resource(names[0]['uri'])
                        self.assertIsInstance(json.loads(schema.contents[0].text), dict)
                        with self.assertRaises(Exception):
                            await session.read_resource('doctore://contracts/../../.env')
                        prompt = await session.get_prompt('review_market', {'sport': 'tennis', 'event': 'Example'})
                        self.assertIn('BLOCKED', prompt.messages[0].content.text)
            asyncio.run(inspect())
            self.assertFalse(ledger.parent.exists())

    def test_missing_ledger_fails_before_runtime_import(self):
        env = dict(os.environ)
        env.pop('DOCTORE_BET_LOG', None)
        result = subprocess.run([sys.executable, '-m', 'doctore_mcp', '--check'], cwd=REPO, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('DOCTORE_BET_LOG is required', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_mismatched_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'doctore_mcp', '--repo', directory, '--bet-log', str(Path(directory) / 'bets.csv'), '--print-config'], cwd=REPO, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('incomplete Doctore checkout', result.stderr)


if __name__ == '__main__':
    unittest.main()
