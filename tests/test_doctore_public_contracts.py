"""Contract visibility regression; no blind evaluation tasks are imported."""
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicContractsTests(unittest.TestCase):
    def test_nested_contracts_are_visible_and_self_contained(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["DOCTORE_REPO_PATH"] = str(ROOT)
            os.environ["DOCTORE_BET_LOG"] = str(Path(temp) / "ledger.csv")
            from doctore_mcp.schemas import DecisionInput
            schema = DecisionInput.model_json_schema()
            properties = schema["properties"]
            for name, required in (
                ("model_output", {"probability_raw", "validation_domain"}),
                ("market_snapshot", {"outcomes", "correlation_group"}),
                ("portfolio_state", {"exposures", "bankroll"}),
                ("risk_policy", {"caps", "kelly_fraction", "freshness_seconds"}),
            ):
                obj = properties[name]
                self.assertEqual("object", obj["type"])
                self.assertTrue(required.issubset(set(obj["properties"])))
                self.assertFalse(obj.get("additionalProperties", True))
                self.assertTrue(set(obj["required"]))
                self.assertNotIn("$ref", str(obj))


if __name__ == "__main__":
    unittest.main()
