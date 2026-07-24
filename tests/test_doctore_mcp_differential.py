from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = json.loads((ROOT / "doctore_mcp" / "compatibility" / "golden_fixtures.json").read_text())["fixtures"]
HELPERS = runpy.run_path(str(ROOT / "tests" / "test_doctore_mcp.py"))


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
        shutil.copy2(ROOT / "doctore_mcp" / "baseline" / "session_v1" / "pinnacle_parser.py", baseline_dir / "pinnacle_parser.py")
        sys.path.insert(0, str(baseline_dir))
        sys.modules.pop("pinnacle_parser", None)
        spec = importlib.util.spec_from_file_location("doctore_session_v1_server", baseline_dir / "server.py")
        assert spec and spec.loader
        cls.baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.baseline
        spec.loader.exec_module(cls.baseline)
        sys.path.remove(str(baseline_dir))

        os.environ["DOCTORE_BET_LOG"] = str(temp / "hardened.csv")
        preserved = {
            "doctore_mcp.baseline", "doctore_mcp.baseline.session_v1",
            "doctore_mcp.baseline.session_v1.materialize",
        }
        for name in list(sys.modules):
            if name == "doctore_mcp.server" or (name.startswith("doctore_mcp.") and name not in preserved):
                sys.modules.pop(name, None)
        cls.hardened = importlib.import_module("doctore_mcp.server")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def decision_input(self, status: str = "validated"):
        model = HELPERS["model_output"]()
        if status != "validated":
            model.update({
                "probability_calibrated": None,
                "calibration_status": status,
                "calibration_method": "none",
                "validation_window": None,
                "validation_sample_size": None,
                "brier_score": None,
                "log_loss": None,
                "expected_calibration_error": None,
            })
        return self.hardened.DecisionInput(
            model_output=model,
            market_snapshot=HELPERS["market_snapshot"](),
            portfolio_state=HELPERS["portfolio_state"](),
            risk_policy=HELPERS["risk_policy"](),
            evaluated_at="2026-07-24T11:00:00+03:00",
        )

    def test_baseline_source_is_exactly_locked(self) -> None:
        from doctore_mcp.baseline.session_v1.materialize import SOURCE_SHA256, source_bytes
        self.assertEqual(SOURCE_SHA256, hashlib.sha256(source_bytes()).hexdigest())

    def test_parser_granularity_and_header_handling_are_classified_breaks(self) -> None:
        f = FIXTURES["pinnacle_one_game"]
        old = json.loads(asyncio.run(self.baseline.doctore_parse_pinnacle_table(
            self.baseline.ParsePinnacleInput(raw_table=f["raw_table_without_header"], sport="mlb", event_date=f["event_date"])
        )))
        new = asyncio.run(self.hardened.doctore_parse_pinnacle_table(
            self.hardened.ParsePinnacleInput(raw_table=f["raw_table_without_header"], sport="mlb", event_date=f["event_date"], captured_at=f["captured_at"])
        ))
        self.assertEqual(3, old["snapshot_count"])
        self.assertEqual(6, new.snapshot_count)

        old_header = json.loads(asyncio.run(self.baseline.doctore_parse_pinnacle_table(
            self.baseline.ParsePinnacleInput(raw_table=f["raw_table_with_header"], sport="mlb", event_date=f["event_date"])
        )))
        new_header = asyncio.run(self.hardened.doctore_parse_pinnacle_table(
            self.hardened.ParsePinnacleInput(raw_table=f["raw_table_with_header"], sport="mlb", event_date=f["event_date"], captured_at=f["captured_at"])
        ))
        self.assertTrue(any(item["event_id"].endswith("away-vs-home") for item in old_header["snapshots"]))
        self.assertEqual((1, 1), (new_header.parsed_game_count, new_header.skipped_row_count))

    def test_material_contradiction_remains_compatible(self) -> None:
        f = FIXTURES["quality_contradiction"]
        old = json.loads(asyncio.run(self.baseline.doctore_check_data_quality(self.baseline.QualityGateInput(**f))))
        new = asyncio.run(self.hardened.doctore_check_data_quality(self.hardened.QualityGateInput(**f)))
        self.assertEqual(("BLOCKED", "BLOCKED"), (old["status"], new.status))

    def test_missing_selection_is_intentional_safety_break(self) -> None:
        f = FIXTURES["quality_missing_selection"]
        old = json.loads(asyncio.run(self.baseline.doctore_check_data_quality(self.baseline.QualityGateInput(**f))))
        new = asyncio.run(self.hardened.doctore_check_data_quality(self.hardened.QualityGateInput(**f)))
        self.assertEqual(("PASS", "BLOCKED"), (old["status"], new.status))

    def test_validated_stake_is_capped_by_canonical_policy(self) -> None:
        f = FIXTURES["edge_validated"]
        old = json.loads(asyncio.run(self.baseline.doctore_calculate_edge_and_stake(
            self.baseline.EdgeCalculationInput(model_probability=f["model_probability"], offered_odds=f["offered_odds"], calibration_status=f["calibration_status"], bankroll=f["bankroll"])
        )))
        new = asyncio.run(self.hardened.doctore_calculate_edge_and_stake(self.decision_input()))
        self.assertEqual(f["expected_baseline_stake"], old["recommended_stake"])
        self.assertEqual(f["expected_hardened_stake"], new.recommended_stake)
        self.assertEqual("per_bet", new.staking["binding_cap"])

    def test_unknown_status_changes_nonzero_pass_to_zero_block(self) -> None:
        f = FIXTURES["edge_unknown"]
        old = json.loads(asyncio.run(self.baseline.doctore_calculate_edge_and_stake(
            self.baseline.EdgeCalculationInput(model_probability=f["model_probability"], offered_odds=f["offered_odds"], calibration_status=f["calibration_status"], bankroll=f["bankroll"])
        )))
        new = asyncio.run(self.hardened.doctore_calculate_edge_and_stake(self.decision_input("unknown")))
        self.assertEqual(("PASS", f["expected_baseline_stake"]), (old["verdict"], old["recommended_stake"]))
        self.assertEqual(("BLOCKED", 0.0), (new.decision, new.recommended_stake))

    def test_exact_domain_mismatch_is_newly_blocked(self) -> None:
        from datetime import datetime, timezone
        old = json.loads(asyncio.run(self.baseline.doctore_evaluate_bet(
            self.baseline.EvaluateBetInput(
                market_snapshot={
                    "event_id": "EVENT-A", "market_id": "MARKET-A",
                    "snapshot_at": datetime.now(timezone.utc).isoformat(),
                    "outcomes": [{"selection": "Minnesota Lynx", "odds_decimal": 1.90}, {"selection": "New York Liberty", "odds_decimal": 1.95}],
                },
                model_output={
                    "event_id": "EVENT-B", "probability_calibrated": 0.60,
                    "calibration_status": "validated", "validation_sample_size": 500,
                    "model_version": "golden", "brier_score": 0.20,
                },
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
