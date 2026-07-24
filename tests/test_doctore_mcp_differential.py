from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = json.loads((ROOT / "doctore_mcp" / "compatibility" / "golden_fixtures.json").read_text())["fixtures"]


def model_output(probability: float = 0.60, status: str = "validated") -> dict:
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": "WNBA-2026-07-24-MIN-NYL-1001",
        "market_id": "WNBA-2026-07-24-MIN-NYL-1001-moneyline-minnesota-lynx-pk",
        "model_name": "doctore-wnba-moneyline", "model_version": "2026.07.24.1",
        "sport": "WNBA", "competition": "WNBA", "market_type": "moneyline",
        "target_market": "full_game_moneyline", "period": "full_game", "line": None,
        "settlement_rules": "full_game_including_overtime", "selection": "Minnesota Lynx",
        "probability_raw": probability,
        "probability_calibrated": probability if status == "validated" else None,
        "calibration_status": status,
        "calibration_method": "sigmoid" if status == "validated" else "none",
        "prediction_generated_at": "2026-07-24T10:45:00+03:00",
        "feature_cutoff_at": "2026-07-24T10:40:00+03:00",
        "training_cutoff_at": "2026-07-23T23:59:59+03:00",
        "feature_schema_version": "wnba.moneyline.v1",
        "validation_domain": {
            "sport": "WNBA", "competition": "WNBA", "market_type": "moneyline",
            "target_market": "full_game_moneyline", "period": "full_game", "line": None,
            "settlement_rules": "full_game_including_overtime",
        },
        "validation_window": "2025-05-01/2026-07-20" if status == "validated" else None,
        "validation_sample_size": 500 if status == "validated" else None,
        "brier_score": 0.20 if status == "validated" else None,
        "log_loss": 0.58 if status == "validated" else None,
        "expected_calibration_error": 0.03 if status == "validated" else None,
    }


def market_snapshot() -> dict:
    return {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": "WNBA-2026-07-24-MIN-NYL-1001",
        "market_id": "WNBA-2026-07-24-MIN-NYL-1001-moneyline-minnesota-lynx-pk",
        "book": "Pinnacle", "book_market_id": "1001",
        "captured_at": "2026-07-24T10:59:00+03:00",
        "event_start_at": "2026-07-24T20:00:00+03:00",
        "sport": "WNBA", "competition": "WNBA", "market_type": "moneyline",
        "target_market": "full_game_moneyline", "period": "full_game", "line": None,
        "settlement_rules": "full_game_including_overtime", "selection": "Minnesota Lynx",
        "decimal_odds": 1.90, "market_status": "open", "is_complete": True,
        "outcomes": [
            {"selection": "Minnesota Lynx", "decimal_odds": 1.90},
            {"selection": "New York Liberty", "decimal_odds": 1.95},
        ],
        "correlation_group": "WNBA-2026-07-24-MIN-NYL-1001", "source": "golden-test",
    }


def portfolio_state() -> dict:
    return {
        "schema_version": "doctore.portfolio-state.v1", "portfolio_id": "primary-eur",
        "captured_at": "2026-07-24T10:59:30+03:00", "currency": "EUR",
        "bankroll": 50000.0, "available_balance": 45000.0, "stake_increment": 1.0,
        "league": "WNBA", "correlation_group": "WNBA-2026-07-24-MIN-NYL-1001",
        "drawdown_fraction": 0.02, "open_positions_count": 1,
        "exposures": {"open_amount": 500.0, "daily_turnover_amount": 1000.0,
                      "league_amount": 500.0, "rolling_3d_turnover_amount": 2000.0,
                      "correlation_group_amount": 0.0},
    }


def risk_policy() -> dict:
    return {
        "schema_version": "doctore.risk-policy.v1", "policy_id": "doctore-default",
        "policy_version": "2026.07.24", "minimum_ev": 0.03,
        "minimum_edge_probability_points": 0.015, "minimum_stake": 1.0,
        "allowed_calibration_statuses": ["validated", "uncalibrated"],
        "kelly_fraction": {"validated": 0.25, "uncalibrated": 0.10, "unknown": 0},
        "sizing_model_weight": {"validated": 0.85, "uncalibrated": 0.35, "unknown": 0},
        "caps": {"max_stake_fraction_per_bet": 0.02, "max_open_exposure_fraction": 0.10,
                 "max_daily_turnover_fraction": 0.25, "max_league_exposure_fraction": 0.15,
                 "max_rolling_3d_turnover_fraction": 0.40,
                 "max_correlation_group_fraction": 0.04},
        "freshness_seconds": {"market_snapshot": 300, "portfolio_state": 60,
                              "model_output": 1800, "mlb_context": 900},
        "drawdown": {"warning_fraction": 0.10, "review_fraction": 0.15, "pause_fraction": 0.20},
        "human_approval_required": True, "block_unknown_correlation": True,
    }


class DifferentialGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="doctore-differential-")
        temp = Path(cls.temp.name)
        os.environ["DOCTORE_REPO_PATH"] = str(ROOT)
        os.environ["DOCTORE_BET_LOG"] = str(temp / "baseline.csv")

        from doctore_mcp.baseline.session_v1.materialize import source_bytes
        baseline_dir = temp / "baseline"
        baseline_dir.mkdir()
        (baseline_dir / "server.py").write_bytes(source_bytes())
        shutil.copy2(
            ROOT / "doctore_mcp" / "baseline" / "session_v1" / "pinnacle_parser.py",
            baseline_dir / "pinnacle_parser.py",
        )
        sys.path.insert(0, str(baseline_dir))
        sys.modules.pop("pinnacle_parser", None)
        spec = importlib.util.spec_from_file_location("doctore_session_v1_server", baseline_dir / "server.py")
        assert spec and spec.loader
        cls.baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.baseline)
        sys.path.remove(str(baseline_dir))

        os.environ["DOCTORE_BET_LOG"] = str(temp / "hardened.csv")
        for name in list(sys.modules):
            if name == "doctore_mcp.server" or (
                name.startswith("doctore_mcp.")
                and name not in {
                    "doctore_mcp.baseline", "doctore_mcp.baseline.session_v1",
                    "doctore_mcp.baseline.session_v1.materialize",
                }
            ):
                sys.modules.pop(name, None)
        cls.hardened = importlib.import_module("doctore_mcp.server")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def decision_input(self, status: str = "validated"):
        return self.hardened.DecisionInput(
            model_output=model_output(status=status), market_snapshot=market_snapshot(),
            portfolio_state=portfolio_state(), risk_policy=risk_policy(),
            evaluated_at="2026-07-24T11:00:00+03:00",
        )

    def test_baseline_source_is_exactly_locked(self) -> None:
        from doctore_mcp.baseline.session_v1.materialize import SOURCE_SHA256, source_bytes
        import hashlib
        self.assertEqual(SOURCE_SHA256, hashlib.sha256(source_bytes()).hexdigest())

    def test_parser_granularity_and_header_handling_are_classified_breaks(self) -> None:
        fixture = FIXTURES["pinnacle_one_game"]
        old = json.loads(asyncio.run(self.baseline.doctore_parse_pinnacle_table(
            self.baseline.ParsePinnacleInput(
                raw_table=fixture["raw_table_without_header"], sport="mlb", event_date=fixture["event_date"]
            )
        )))
        new = asyncio.run(self.hardened.doctore_parse_pinnacle_table(
            self.hardened.ParsePinnacleInput(
                raw_table=fixture["raw_table_without_header"], sport="mlb",
                event_date=fixture["event_date"], captured_at=fixture["captured_at"],
            )
        ))
        self.assertEqual(3, old["snapshot_count"])
        self.assertEqual(6, new.snapshot_count)

        old_header = json.loads(asyncio.run(self.baseline.doctore_parse_pinnacle_table(
            self.baseline.ParsePinnacleInput(
                raw_table=fixture["raw_table_with_header"], sport="mlb", event_date=fixture["event_date"]
            )
        )))
        new_header = asyncio.run(self.hardened.doctore_parse_pinnacle_table(
            self.hardened.ParsePinnacleInput(
                raw_table=fixture["raw_table_with_header"], sport="mlb",
                event_date=fixture["event_date"], captured_at=fixture["captured_at"],
            )
        ))
        self.assertTrue(any(item["event_id"].endswith("away-vs-home") for item in old_header["snapshots"]))
        self.assertEqual(1, new_header.parsed_game_count)
        self.assertEqual(1, new_header.skipped_row_count)

    def test_material_contradiction_remains_compatible(self) -> None:
        fixture = FIXTURES["quality_contradiction"]
        old = json.loads(asyncio.run(self.baseline.doctore_check_data_quality(
            self.baseline.QualityGateInput(**fixture)
        )))
        new = asyncio.run(self.hardened.doctore_check_data_quality(
            self.hardened.QualityGateInput(**fixture)
        ))
        self.assertEqual("BLOCKED", old["status"])
        self.assertEqual("BLOCKED", new.status)

    def test_missing_selection_is_intentional_safety_break(self) -> None:
        fixture = FIXTURES["quality_missing_selection"]
        old = json.loads(asyncio.run(self.baseline.doctore_check_data_quality(
            self.baseline.QualityGateInput(**fixture)
        )))
        new = asyncio.run(self.hardened.doctore_check_data_quality(
            self.hardened.QualityGateInput(**fixture)
        ))
        self.assertEqual("PASS", old["status"])
        self.assertEqual("BLOCKED", new.status)

    def test_validated_stake_is_capped_by_canonical_policy(self) -> None:
        fixture = FIXTURES["edge_validated"]
        old = json.loads(asyncio.run(self.baseline.doctore_calculate_edge_and_stake(
            self.baseline.EdgeCalculationInput(
                model_probability=fixture["model_probability"], offered_odds=fixture["offered_odds"],
                calibration_status=fixture["calibration_status"], bankroll=fixture["bankroll"],
            )
        )))
        new = asyncio.run(self.hardened.doctore_calculate_edge_and_stake(self.decision_input()))
        self.assertEqual(fixture["expected_baseline_stake"], old["recommended_stake"])
        self.assertEqual(fixture["expected_hardened_stake"], new.recommended_stake)
        self.assertEqual("per_bet", new.staking["binding_cap"])

    def test_unknown_status_changes_nonzero_pass_to_zero_block(self) -> None:
        fixture = FIXTURES["edge_unknown"]
        old = json.loads(asyncio.run(self.baseline.doctore_calculate_edge_and_stake(
            self.baseline.EdgeCalculationInput(
                model_probability=fixture["model_probability"], offered_odds=fixture["offered_odds"],
                calibration_status=fixture["calibration_status"], bankroll=fixture["bankroll"],
            )
        )))
        new = asyncio.run(self.hardened.doctore_calculate_edge_and_stake(self.decision_input("unknown")))
        self.assertEqual("PASS", old["verdict"])
        self.assertEqual(fixture["expected_baseline_stake"], old["recommended_stake"])
        self.assertEqual("BLOCKED", new.decision)
        self.assertEqual(fixture["expected_hardened_stake"], new.recommended_stake)

    def test_exact_domain_mismatch_is_newly_blocked(self) -> None:
        from datetime import datetime, timezone
        old_market = {
            "event_id": "EVENT-A", "market_id": "MARKET-A",
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "outcomes": [{"selection": "Minnesota Lynx", "odds_decimal": 1.90},
                         {"selection": "New York Liberty", "odds_decimal": 1.95}],
        }
        old_model = {"event_id": "EVENT-B", "probability_calibrated": 0.60,
                     "calibration_status": "validated", "validation_sample_size": 500,
                     "model_version": "golden", "brier_score": 0.20}
        old = json.loads(asyncio.run(self.baseline.doctore_evaluate_bet(
            self.baseline.EvaluateBetInput(
                market_snapshot=old_market, model_output=old_model,
                selection="Minnesota Lynx", bankroll=50000,
            )
        )))
        new_params = self.decision_input()
        new_params.market_snapshot["line"] = 1.5
        new = asyncio.run(self.hardened.doctore_evaluate_bet(new_params))
        self.assertEqual("BET", old["verdict"])
        self.assertEqual("BLOCKED", new.decision_output["decision"])
        self.assertIn("DOMAIN_MISMATCH", new.decision_output["reason_codes"])


if __name__ == "__main__":
    unittest.main()
