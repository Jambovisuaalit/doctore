"""Synthetic public examples regression (not independent blind evaluation)."""
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicExamplesTests(unittest.TestCase):
    def test_examples_cover_all_tools_and_reach_economics(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DOCTORE_REPO_PATH"] = str(ROOT)
            os.environ["DOCTORE_BET_LOG"] = str(Path(tmp) / "ledger.csv")
            os.environ["DOCTORE_MODEL_ARTIFACT_ROOT"] = tmp
            from doctore_mcp.public_examples import build_examples
            from doctore_mcp.schemas import DecisionInput, schema_errors
            from doctore_mcp.decision_adapter import evaluate
            examples = build_examples(Path(tmp))
            self.assertEqual(14, len(examples))
            for name in ("doctore_evaluate_bet", "doctore_calculate_edge_and_stake"):
                payload = examples[name]
                for key, contract in (("model_output", "model"), ("market_snapshot", "market"),
                                      ("portfolio_state", "portfolio"), ("risk_policy", "policy")):
                    self.assertEqual([], schema_errors(contract, payload[key]), (name, key))
            result = evaluate(DecisionInput(**examples["doctore_evaluate_bet"]))
            self.assertIsNotNone(result.decision_output["economics"]["ev"])
            self.assertIsNotNone(result.decision_output["market"]["no_vig_probability"])
            self.assertFalse(Path(os.environ["DOCTORE_BET_LOG"]).exists())


if __name__ == "__main__":
    unittest.main()
