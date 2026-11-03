"""Regression guard: canonical BET cannot bypass the registry hold."""
import unittest
from bet_decision_core import _finish, _base


class MandatoryRegistryHoldTests(unittest.TestCase):
    def test_bet_is_never_exposed_without_verified_registry(self):
        output = _base({}, {}, {}, {}, "2026-11-03T00:00:00Z", None)
        output["staking"]["final_stake"] = 10.0
        result = _finish(output, "BET", ["EDGE_QUALIFIES"])
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertIn("MODEL_REGISTRY_UNVERIFIED", result["reason_codes"])
        self.assertIsNone(result["staking"]["final_stake"])


if __name__ == "__main__":
    unittest.main()
