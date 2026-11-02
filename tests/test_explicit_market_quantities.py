"""Independent formula cases for additive public output names, not blind tasks."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ExplicitQuantityTests(unittest.TestCase):
    def test_complete_market_sum_and_excess_keep_legacy_value(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ['DOCTORE_REPO_PATH']=str(ROOT)
            os.environ['DOCTORE_BET_LOG']=str(Path(directory)/'ledger.csv')
            os.environ['DOCTORE_MODEL_ARTIFACT_ROOT']=directory
            from doctore_mcp.public_examples import build_examples
            from doctore_mcp.schemas import DecisionInput
            from doctore_mcp.decision_adapter import calculate_edge_and_stake
            base=build_examples(Path(directory))['doctore_calculate_edge_and_stake']
            for odds in ((1.50,2.80),(2.0,2.0),(2.50,1.50)):
                data=deepcopy(base)
                outcomes=data['market_snapshot']['outcomes']
                for outcome,price in zip(outcomes,odds):outcome['decimal_odds']=price
                data['market_snapshot']['decimal_odds']=odds[0]
                result=calculate_edge_and_stake(DecisionInput(**data))
                expected=sum(1/price for price in odds)
                self.assertAlmostEqual(result.implied_probability_sum,expected,places=10)
                self.assertAlmostEqual(result.overround_excess,expected-1,places=10)
                self.assertEqual(result.overround,result.overround_excess)
            self.assertFalse((Path(directory)/'ledger.csv').exists())

if __name__=='__main__':unittest.main()
