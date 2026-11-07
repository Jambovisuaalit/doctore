"""P0 real-code parity: direct canonical, Market Core bridge, and MCP route.

All inputs are synthetic and no ledger or bookmaker write tool is called.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from doctore_mcp.public_examples import build_examples
from doctore_mcp.runtime import REPO  # configures canonical src imports
from bet_decision_core import evaluate_bet_decision
from doctore_mcp.market_core_shadow_bridge import evaluate_shadow_canonical, _sha
from doctore_mcp.decision_adapter import run_decision
from doctore_mcp.schemas import DecisionInput
from doctore_mcp.tools import doctore_evaluate_bet


class TestP0MarketCoreMcpParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        examples = build_examples(Path(self.tmp.name))
        self.evaluation = examples["doctore_evaluate_bet"]

    def test_real_canonical_adapter_and_mcp_identical(self):
        direct = evaluate_bet_decision(**self.evaluation)
        shadow = evaluate_shadow_canonical(self.evaluation)
        mcp_adapter = run_decision(DecisionInput(**self.evaluation))
        mcp_tool_result = asyncio.run(doctore_evaluate_bet(DecisionInput(**self.evaluation)))

        self.assertEqual(direct, shadow["canonical_decision"])
        self.assertEqual(direct, mcp_adapter)
        self.assertEqual(direct, mcp_tool_result.decision_output)
        self.assertEqual(direct["decision_id"], shadow["canonical_decision_id"])
        self.assertEqual(direct["decision_id"], mcp_adapter["decision_id"])
        self.assertEqual(direct["decision_id"], mcp_tool_result.decision_output["decision_id"])
        self.assertEqual(_sha(direct), shadow["canonical_output_sha256"])
        for key in ("model_output_sha256", "market_snapshot_sha256",
                    "portfolio_state_sha256", "risk_policy_sha256"):
            self.assertEqual(direct["audit"][key], shadow["canonical_decision"]["audit"][key])
            self.assertEqual(direct["audit"][key], mcp_tool_result.decision_output["audit"][key])
        self.assertFalse(shadow["execution_authorized"])
        self.assertEqual(shadow["recommended_stake_eur"], 0.0)
        self.assertEqual(shadow["mode"], "SHADOW_ONLY")

    def test_bet_result_cannot_authorize_shadow_stake(self):
        direct = evaluate_bet_decision(**self.evaluation)
        self.assertEqual(direct["decision"], "BET")
        self.assertGreater(direct["staking"]["final_stake"], 0)
        shadow = evaluate_shadow_canonical(self.evaluation)
        self.assertEqual(shadow["recommended_stake_eur"], 0)
        self.assertFalse(shadow["execution_authorized"])

    def test_identity_mismatch_fails_closed(self):
        payload = json.loads(json.dumps(self.evaluation))
        payload["model_output"]["event_id"] = "SYNTHETIC-WRONG-EVENT"
        with self.assertRaisesRegex(ValueError, "CANONICAL_IDENTITY_MISMATCH"):
            evaluate_shadow_canonical(payload)


if __name__ == "__main__":
    unittest.main()
