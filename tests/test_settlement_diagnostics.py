"""Regression: unsupported settlement remains blocked with actionable public evidence."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SettlementDiagnosticTests(unittest.TestCase):
    def test_supported_and_unsupported_rules_keep_economics_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ['DOCTORE_REPO_PATH'] = str(ROOT)
            os.environ['DOCTORE_BET_LOG'] = str(Path(directory) / 'ledger.csv')
            os.environ['DOCTORE_MODEL_ARTIFACT_ROOT'] = directory
            from doctore_mcp.public_examples import build_examples
            from doctore_mcp.schemas import DecisionInput
            from doctore_mcp.decision_adapter import calculate_edge_and_stake, evaluate
            base = build_examples(Path(directory))['doctore_calculate_edge_and_stake']
            valid = calculate_edge_and_stake(DecisionInput(**base))
            self.assertNotIn('SETTLEMENT_RULES_UNSUPPORTED', valid.reason_codes)
            self.assertIsNotNone(valid.ev)
            for rule in ('standard', 'unknown', 'regulation_only'):
                data = deepcopy(base)
                for obj in (data['market_snapshot'], data['model_output'], data['model_output']['validation_domain']):
                    obj['settlement_rules'] = rule
                result = calculate_edge_and_stake(DecisionInput(**data))
                self.assertEqual(result.decision, 'BLOCKED')
                self.assertIn('SETTLEMENT_RULES_UNSUPPORTED', result.reason_codes)
                self.assertIn('MARKET_INCOMPLETE', result.reason_codes)
                self.assertTrue(any(rule in d and 'required explicit convention:' in d for d in result.diagnostics))
                self.assertEqual(result.recommended_stake, 0)
                for field in ('ev', 'full_kelly', 'no_vig_probability', 'overround'):
                    self.assertIsNone(getattr(result, field))
                canonical = evaluate(DecisionInput(**data)).decision_output
                self.assertIn('SETTLEMENT_RULES_UNSUPPORTED', canonical['reason_codes'])
                self.assertEqual(result.diagnostics, canonical['diagnostics'])
            self.assertFalse((Path(directory) / 'ledger.csv').exists())
