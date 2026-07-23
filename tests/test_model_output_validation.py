from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "model-probability" / "scripts" / "validate_model_output.py"


def validated_payload() -> dict:
    return {
        "schema_version": "doctore.model-output.v1",
        "event_id": "nba-2026-07-23-bos-lal",
        "market_id": "nba-2026-07-23-bos-lal-ml-home",
        "model_name": "doctore-nba-moneyline",
        "model_version": "2.4.1+sha.abcdef0",
        "sport": "NBA",
        "competition": "NBA",
        "market_type": "moneyline",
        "target_market": "full_game_moneyline",
        "period": "full_game_including_overtime",
        "line": None,
        "settlement_rules": "including_overtime",
        "selection": "Boston Celtics",
        "probability_raw": 0.612,
        "probability_calibrated": 0.598,
        "calibration_status": "validated",
        "calibration_method": "sigmoid",
        "prediction_generated_at": "2026-07-23T12:00:00Z",
        "feature_cutoff_at": "2026-07-23T11:55:00Z",
        "training_cutoff_at": "2026-07-01T00:00:00Z",
        "feature_schema_version": "nba-features.v3",
        "validation_domain": {
            "sport": "NBA",
            "competition": "NBA",
            "market_type": "moneyline",
            "target_market": "full_game_moneyline",
            "period": "full_game_including_overtime",
            "line": None,
            "settlement_rules": "including_overtime",
        },
        "validation_window": "2025-10-01/2026-06-30",
        "validation_sample_size": 1248,
        "brier_score": 0.2134,
        "log_loss": 0.6112,
        "expected_calibration_error": 0.028,
    }


class ModelOutputValidationTests(unittest.TestCase):
    def run_validator(self, payload: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "model-output.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(input_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertTrue(result.stdout, msg=result.stderr)
        return result, json.loads(result.stdout)

    def test_validated_output_requires_complete_metrics_and_exact_domain(self):
        result, output = self.run_validator(validated_payload())
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(output["valid"])
        self.assertEqual(output["decision"], "VALIDATED")
        self.assertTrue(output["domain_match"])
        self.assertEqual(output["errors"], [])

    def test_validated_output_without_required_metrics_is_blocked(self):
        payload = validated_payload()
        payload["validation_sample_size"] = None
        payload["brier_score"] = None
        payload["log_loss"] = None
        payload["expected_calibration_error"] = None

        result, output = self.run_validator(payload)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output["valid"])
        self.assertEqual(output["decision"], "BLOCKED")
        error_paths = {error["path"] for error in output["errors"]}
        self.assertTrue(
            {
                "validation_sample_size",
                "brier_score",
                "log_loss",
                "expected_calibration_error",
            }.issubset(error_paths)
        )

    def test_uncalibrated_output_is_accepted_only_as_uncalibrated(self):
        payload = validated_payload()
        payload.update(
            {
                "probability_calibrated": None,
                "calibration_status": "uncalibrated",
                "calibration_method": "none",
                "validation_window": None,
                "validation_sample_size": None,
                "brier_score": None,
                "log_loss": None,
                "expected_calibration_error": None,
            }
        )

        result, output = self.run_validator(payload)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(output["valid"])
        self.assertEqual(output["decision"], "UNCALIBRATED")
        self.assertEqual(output["errors"], [])

    def test_unknown_calibration_status_is_blocked(self):
        payload = validated_payload()
        payload.update(
            {
                "probability_calibrated": None,
                "calibration_status": "unknown",
                "calibration_method": "none",
                "validation_window": None,
                "validation_sample_size": None,
                "brier_score": None,
                "log_loss": None,
                "expected_calibration_error": None,
            }
        )

        result, output = self.run_validator(payload)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output["valid"])
        self.assertEqual(output["decision"], "BLOCKED")
        self.assertIn("calibration_status.unknown", {error["code"] for error in output["errors"]})

    def test_validation_domain_must_exactly_match_prediction_target(self):
        payload = copy.deepcopy(validated_payload())
        payload["validation_domain"]["market_type"] = "spread"

        result, output = self.run_validator(payload)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output["domain_match"])
        self.assertEqual(output["decision"], "BLOCKED")
        self.assertIn("domain_mismatch.market_type", {error["code"] for error in output["errors"]})


if __name__ == "__main__":
    unittest.main()
