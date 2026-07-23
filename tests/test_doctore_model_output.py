from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from src.doctore_model_output import ModelOutputMappingError, to_canonical_model_output

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "contracts" / "model-output.schema.json").read_text(encoding="utf-8")
)
SAMPLE = json.loads(
    (ROOT / "examples" / "sample-versioned-prediction.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
KWARGS = {
    "market_id": "NBA-EXAMPLE-001-TOTAL-224.5-OVER",
    "competition": "NBA",
    "target_market": "full_game_total",
    "settlement_rules": "including_overtime_push_on_exact_integer_total",
}


class CanonicalModelOutputTests(unittest.TestCase):
    def assert_schema_valid(self, payload: dict) -> None:
        errors = sorted(
            VALIDATOR.iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual(
            [],
            errors,
            msg="\n".join(error.message for error in errors),
        )

    def test_degraded_pipeline_is_downgraded_to_uncalibrated(self) -> None:
        canonical = to_canonical_model_output(SAMPLE, **KWARGS)
        self.assert_schema_valid(canonical)
        self.assertEqual(canonical["calibration_status"], "uncalibrated")
        self.assertEqual(canonical["calibration_method"], "none")
        self.assertIsNone(canonical["probability_calibrated"])
        self.assertEqual(
            canonical["probability_raw"],
            SAMPLE["calibration"]["probability_selected_raw"],
        )

    def test_validated_requires_better_brier_and_log_loss(self) -> None:
        report = copy.deepcopy(SAMPLE)
        report["calibration"]["status"] = "validated"
        report["validation"].update(
            {
                "sample_size": 250,
                "model_brier_score": 0.20,
                "market_brier_score": 0.25,
                "model_log_loss": 0.60,
                "market_log_loss": 0.69,
                "model_ece": 0.03,
            }
        )
        canonical = to_canonical_model_output(report, **KWARGS)
        self.assert_schema_valid(canonical)
        self.assertEqual(canonical["calibration_status"], "validated")
        self.assertEqual(canonical["calibration_method"], "sigmoid")
        self.assertEqual(
            canonical["probability_calibrated"],
            report["calibration"]["probability_selected_calibrated"],
        )

    def test_claimed_validated_with_worse_market_metrics_is_downgraded(self) -> None:
        report = copy.deepcopy(SAMPLE)
        report["calibration"]["status"] = "validated"
        canonical = to_canonical_model_output(report, **KWARGS)
        self.assert_schema_valid(canonical)
        self.assertEqual(canonical["calibration_status"], "uncalibrated")
        self.assertIsNone(canonical["probability_calibrated"])

    def test_validation_domain_exactly_matches_prediction_target(self) -> None:
        canonical = to_canonical_model_output(SAMPLE, **KWARGS)
        self.assertEqual(
            canonical["validation_domain"],
            {
                "sport": canonical["sport"],
                "competition": canonical["competition"],
                "market_type": canonical["market_type"],
                "target_market": canonical["target_market"],
                "period": canonical["period"],
                "line": canonical["line"],
                "settlement_rules": canonical["settlement_rules"],
            },
        )

    def test_missing_required_provenance_is_not_invented(self) -> None:
        report = copy.deepcopy(SAMPLE)
        del report["model"]["feature_cutoff_at"]
        with self.assertRaises(ModelOutputMappingError):
            to_canonical_model_output(report, **KWARGS)

    def test_repository_canonical_sample_is_schema_valid(self) -> None:
        sample = json.loads(
            (ROOT / "examples" / "sample-canonical-model-output.json").read_text(
                encoding="utf-8"
            )
        )
        self.assert_schema_valid(sample)
        self.assertEqual(sample["calibration_status"], "uncalibrated")


if __name__ == "__main__":
    unittest.main()
