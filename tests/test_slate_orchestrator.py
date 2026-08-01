from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TEST_BET_LOG = Path(tempfile.gettempdir()) / "doctore-slate-orchestrator-test.csv"
os.environ.setdefault("DOCTORE_REPO_PATH", str(ROOT))
os.environ.setdefault("DOCTORE_BET_LOG", str(TEST_BET_LOG))

from doctore_mcp.governance import GovernanceResult
from doctore_mcp.orchestrator import SlateOrchestrator, SlateRunInput


class _Output(SimpleNamespace):
    def model_dump(self, mode="json"):
        return dict(self.__dict__)


class SlateOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        for path in (
            TEST_BET_LOG,
            TEST_BET_LOG.with_suffix(".decision-bundles.jsonl"),
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def test_bet_requires_human_approval_before_logging(self):
        """Exercise approval semantics with governance explicitly approved in-test.

        Production defaults remain fail-closed because the repository governance
        registries are intentionally empty. This unit test isolates the later
        approval boundary instead of depending on production registry contents.
        """
        calls = []

        async def parse(_):
            return _Output(snapshots=[{"market_id": "m1"}], diagnostics=[])

        async def quality(_):
            return _Output(status="PASS", reasons=[], age_minutes=0.1)

        async def load(_):
            return _Output(ok=True, model_output={"schema_version": "doctore.model-output.v1"}, error=None)

        async def edge(_):
            return _Output(
                decision_id="a" * 64,
                decision="BET",
                reason_codes=["EDGE_OK"],
                no_vig_probability=0.5,
                overround=0.02,
                ev=0.05,
                edge_vs_market_pp=3.0,
                full_kelly=0.02,
                recommended_stake=10.0,
                staking={},
                human_approval_required=True,
            )

        async def evaluate(_):
            return _Output(
                decision_output={
                    "decision_id": "a" * 64,
                    "decision": "BET",
                    "reason_codes": ["EDGE_OK"],
                },
                recommended_stake=10.0,
            )

        async def log(_):
            calls.append("log")
            return _Output(logged=True, decision_id="a" * 64, approved_stake=10.0, reason=None, log_path="x")

        async def settle(_):
            calls.append("settle")
            return _Output()

        async def portfolio(_):
            return _Output(
                open_bet_count=0,
                open_exposure=0.0,
                exposure_pct_of_bankroll=0.0,
                settled_bet_count=0,
                decisive_bet_count=0,
                win_rate=None,
                realized_profit_loss=0.0,
                avg_price_clv_pct=None,
                avg_clv_probability_points=None,
                result_counts={},
            )

        orchestrator = SlateOrchestrator(
            parse_pinnacle_table=parse,
            check_data_quality=quality,
            load_model_prediction=load,
            calculate_edge_and_stake=edge,
            evaluate_bet=evaluate,
            log_bet=log,
            settle_bet=settle,
            portfolio_status=portfolio,
        )
        approved_governance = GovernanceResult(
            ok=True,
            reason_codes=[],
            governance={"schema_version": "doctore.governance-result.v1", "test_fixture": True},
        )
        # Differential tests intentionally reload doctore_mcp modules. Patch the
        # exact globals dictionary bound to this imported SlateOrchestrator class,
        # not a potentially newer module instance in sys.modules.
        with patch.dict(
            SlateOrchestrator.run.__globals__,
            {"validate_market_governance": lambda **_: approved_governance},
        ):
            result = await orchestrator.run(
                SlateRunInput(
                    raw_table="header\nrow with enough content",
                    sport="mlb",
                    event_date="2026-07-29",
                    captured_at="2026-07-29T10:00:00+00:00",
                    bankroll=1000,
                    portfolio_state={},
                    risk_policy={},
                    markets=[
                        {
                            "market_id": "m1",
                            "prediction_path": "examples/model.json",
                            "competition": "MLB",
                            "target_market": "moneyline",
                            "market_snapshot": {},
                        }
                    ],
                )
            )
        self.assertEqual(result.items[0].status, "AWAITING_HUMAN_APPROVAL")
        self.assertIn("HUMAN_APPROVAL_REQUIRED", result.items[0].reason_codes)
        self.assertEqual(calls, [])

    async def test_missing_parser_snapshot_has_reason_code(self):
        async def parse(_):
            return _Output(snapshots=[], diagnostics=[])

        async def portfolio(_):
            return _Output(
                open_bet_count=0,
                open_exposure=0.0,
                exposure_pct_of_bankroll=0.0,
                settled_bet_count=0,
                decisive_bet_count=0,
                win_rate=None,
                realized_profit_loss=0.0,
                avg_price_clv_pct=None,
                avg_clv_probability_points=None,
                result_counts={},
            )

        async def unused(_):
            raise AssertionError("must not be called")

        orchestrator = SlateOrchestrator(
            parse_pinnacle_table=parse,
            check_data_quality=unused,
            load_model_prediction=unused,
            calculate_edge_and_stake=unused,
            evaluate_bet=unused,
            log_bet=unused,
            settle_bet=unused,
            portfolio_status=portfolio,
        )
        result = await orchestrator.run(
            SlateRunInput(
                raw_table="header\nrow with enough content",
                sport="mlb",
                event_date="2026-07-29",
                captured_at="2026-07-29T10:00:00+00:00",
                bankroll=1000,
                portfolio_state={},
                risk_policy={},
                markets=[
                    {
                        "market_id": "missing",
                        "prediction_path": "examples/model.json",
                        "competition": "MLB",
                        "target_market": "moneyline",
                        "market_snapshot": {},
                    }
                ],
            )
        )
        self.assertEqual(result.items[0].status, "REJECTED")
        self.assertEqual(result.items[0].reason_codes, ["SLATE_MARKET_NOT_IN_PARSED_INPUT"])


if __name__ == "__main__":
    unittest.main()
