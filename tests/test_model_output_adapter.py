from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model_output_adapter import to_model_output_contract

VALIDATOR = ROOT / "skills" / "model-probability" / "scripts" / "validate_model_output.py"
SAMPLE = ROOT / "examples" / "sample-versioned-prediction.json"


class ModelOutputAdapterTests(unittest.TestCase):
    def load_sample(self) -> dict:
        return json.loads(SAMPLE.read_text(encoding="utf-8"))

    def adapt(self, payload: dict) -> dict:
        return to_model_output_contract(
            payload,
            market_id="NBA-EXAMPLE-001-GAME-TOTAL-224.5-OVER",
            competition="NBA",
            target_market="full_game_total_224.5_over_including_overtime",
            settlement_rules="including_overtime_push_on_exact_integer_line",
        )

    def validate(self, payload: dict) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model-output.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        return result.returncode, json.loads(result.stdout)

    def test_validated_rich_prediction_passes_canonical_validator(self):
        rich = self.load_sample()
        rich["calibration"]["status"] = "validated"
        canonical = self.adapt(rich)

        code, result = self.validate(canonical)

        self.assertEqual(code, 0, msg=result)
        self.assertEqual(result["decision"], "VALIDATED")
        self.assertTrue(result["domain_match"])
        self.assertEqual(canonical["validation_sample_size"], rich["validation"]["sample_size"])
        self.assertEqual(canonical["brier_score"], rich["validation"]["model_brier_score"])
        self.assertEqual(canonical["log_loss"], rich["validation"]["model_log_loss"])
        self.assertEqual(canonical["expected_calibration_error"], rich["validation"]["model_ece"])

    def test_degraded_rich_prediction_is_blocked(self):
        canonical = self.adapt(self.load_sample())

        code, result = self.validate(canonical)

        self.assertEqual(code, 1)
        self.assertEqual(canonical["calibration_status"], "unknown")
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertIn("calibration_status.unknown", {error["code"] for error in result["errors"]})

    def test_adapter_requires_explicit_market_domain(self):
        with self.assertRaises(ValueError):
            to_model_output_contract(
                copy.deepcopy(self.load_sample()),
                market_id="",
                competition="NBA",
                target_market="full_game_total",
                settlement_rules="including_overtime",
            )


if __name__ == "__main__":
    unittest.main()
