from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feature_provenance import validate_feature_provenance, validate_provenance_record
from mlb_feature_schema_v2 import ABLATION_ORDER, FEATURE_GROUPS, FEATURE_SCHEMA_VERSION


class FeatureSchemaV2Tests(unittest.TestCase):
    def test_schema_groups_are_disjoint_and_ordered(self) -> None:
        self.assertEqual("baseline", ABLATION_ORDER[0])
        seen: set[str] = set()
        for group in ABLATION_ORDER:
            columns = FEATURE_GROUPS[group].columns
            self.assertTrue(columns)
            self.assertFalse(seen.intersection(columns))
            seen.update(columns)

    def base_record(self) -> dict:
        return {
            "schema_version": "doctore.feature-provenance.v1",
            "event_id": "mlb:2",
            "feature_group": "starter",
            "source": "archived-pregame-snapshot",
            "source_record_id": "snapshot-1",
            "availability_mode": "PREGAME_SNAPSHOT",
            "feature_cutoff_at": "2026-07-01T18:00:00+00:00",
            "source_sha256": "a" * 64,
            "observed_at": "2026-07-01T17:30:00+00:00",
        }

    def test_pregame_snapshot_before_cutoff_passes(self) -> None:
        self.assertEqual((), validate_provenance_record(self.base_record()))

    def test_snapshot_after_cutoff_fails_closed(self) -> None:
        record = self.base_record()
        record["observed_at"] = "2026-07-01T18:00:01+00:00"
        self.assertIn("SNAPSHOT_AFTER_FEATURE_CUTOFF", validate_provenance_record(record))

    def test_current_event_result_cannot_be_feature_source(self) -> None:
        record = self.base_record()
        record.update({
            "feature_group": "bullpen",
            "availability_mode": "PRIOR_EVENT_FINAL",
            "source_event_id": "mlb:2",
            "source_event_end_at": "2026-07-01T17:00:00+00:00",
        })
        record.pop("observed_at")
        self.assertIn("CURRENT_EVENT_RESULT_LEAKAGE", validate_provenance_record(record))

    def test_prior_event_must_be_final_before_cutoff(self) -> None:
        record = self.base_record()
        record.update({
            "feature_group": "bullpen",
            "availability_mode": "PRIOR_EVENT_FINAL",
            "source_event_id": "mlb:1",
            "source_event_end_at": "2026-07-01T18:30:00+00:00",
        })
        record.pop("observed_at")
        self.assertIn("SOURCE_EVENT_NOT_FINAL_BEFORE_CUTOFF", validate_provenance_record(record))

    def test_forecast_must_have_been_issued_before_cutoff(self) -> None:
        record = self.base_record()
        record.update({
            "feature_group": "weather",
            "availability_mode": "FORECAST_RUN",
            "forecast_issued_at": "2026-07-01T18:01:00+00:00",
            "forecast_target_at": "2026-07-01T23:00:00+00:00",
        })
        record.pop("observed_at")
        self.assertIn("FORECAST_ISSUED_AFTER_FEATURE_CUTOFF", validate_provenance_record(record))

    def test_full_coverage_is_required_per_event_and_enabled_group(self) -> None:
        report = validate_feature_provenance(
            [self.base_record()],
            required_event_ids=["mlb:2", "mlb:3"],
            required_groups=["starter"],
            allowed_modes_by_group={"starter": ["PREGAME_SNAPSHOT"]},
        )
        self.assertEqual("BLOCKED_PROVENANCE", report["status"])
        self.assertEqual(1, report["missing_records"])


class FeatureContractSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.provenance_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "feature-provenance-record.schema.json").read_text()),
            format_checker=FormatChecker(),
        )
        cls.group_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "feature-group-manifest.schema.json").read_text()),
            format_checker=FormatChecker(),
        )
        cls.training_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "training-dataset-manifest.schema.json").read_text()),
            format_checker=FormatChecker(),
        )

    def test_feature_group_manifest_validates(self) -> None:
        manifest = {
            "schema_version": "doctore.feature-groups.v1",
            "dataset_id": "mlb-v2-test",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "created_at": "2026-09-11T00:00:00+00:00",
            "groups": [
                {
                    "name": name,
                    "status": spec.historical_2012_2021_status,
                    "columns": list(spec.columns),
                    "allowed_availability_modes": list(spec.allowed_availability_modes),
                    "source_policy": spec.source_policy,
                    "reason_codes": [],
                }
                for name, spec in FEATURE_GROUPS.items()
            ],
        }
        self.assertEqual([], list(self.group_validator.iter_errors(manifest)))

    def training_manifest(self) -> dict:
        return {
            "schema_version": "doctore.training-dataset.v1",
            "dataset_id": "mlb-v2-test",
            "dataset_version": "2",
            "sport": "MLB",
            "competition": "MLB",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "settlement_rules": "full_game_including_extra_innings_push_on_exact_integer_line",
            "target_definition": "away_final_runs + home_final_runs",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "created_at": "2026-09-11T00:00:00+00:00",
            "locked_at": "2026-09-11T00:00:00+00:00",
            "locked": True,
            "dataset_sha256": "b" * 64,
            "row_count": 10,
            "columns": ["f", "target", "line", "over", "under", "ts", "slate"],
            "feature_columns": ["f"],
            "target_column": "target",
            "line_column": "line",
            "over_odds_column": "over",
            "under_odds_column": "under",
            "timestamp_column": "ts",
            "slate_column": "slate",
            "sort_order": "timestamp_non_decreasing_grouped",
        }

    def test_v2_training_manifest_requires_sidecars(self) -> None:
        errors = list(self.training_validator.iter_errors(self.training_manifest()))
        messages = " ".join(error.message for error in errors)
        self.assertIn("feature_group_manifest", messages)
        self.assertIn("feature_provenance_file", messages)
        self.assertIn("ablation_plan", messages)

    def test_v2_training_manifest_with_sidecars_validates(self) -> None:
        manifest = self.training_manifest()
        manifest.update({
            "feature_group_manifest": "feature-groups.json",
            "feature_provenance_file": "feature-provenance.jsonl",
            "ablation_plan": "ablation-plan.json",
        })
        self.assertEqual([], list(self.training_validator.iter_errors(manifest)))


if __name__ == "__main__":
    unittest.main()
