from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feature_provenance import validate_feature_provenance, validate_provenance_record


class MultiSourceFeatureProvenanceTests(unittest.TestCase):
    def record(self) -> dict:
        return {
            "schema_version": "doctore.feature-provenance.v1",
            "event_id": "mlb:target",
            "feature_group": "bullpen",
            "source": "mlb-statsapi-prior-boxscores",
            "source_record_id": "bullpen:mlb:target:3d",
            "availability_mode": "PRIOR_EVENT_FINAL",
            "feature_cutoff_at": "2021-07-10T00:00:00+00:00",
            "source_sha256": "a" * 64,
            "source_events": [
                {"event_id": "mlb:prior-1", "end_at": "2021-07-08T23:00:00+00:00"},
                {"event_id": "mlb:prior-2", "end_at": "2021-07-09T22:00:00+00:00"},
            ],
        }

    def test_valid_multi_source_aggregate_passes(self) -> None:
        self.assertEqual((), validate_provenance_record(self.record()))

    def test_one_late_source_blocks_entire_aggregate(self) -> None:
        record = self.record()
        record["source_events"][1]["end_at"] = "2021-07-10T00:00:00+00:00"
        self.assertIn("SOURCE_EVENT_NOT_FINAL_BEFORE_CUTOFF", validate_provenance_record(record))

    def test_current_event_in_any_source_blocks(self) -> None:
        record = self.record()
        record["source_events"][1]["event_id"] = "mlb:target"
        self.assertIn("CURRENT_EVENT_RESULT_LEAKAGE", validate_provenance_record(record))

    def test_duplicate_source_event_blocks(self) -> None:
        record = self.record()
        record["source_events"][1]["event_id"] = "mlb:prior-1"
        self.assertIn("SOURCE_EVENT_DUPLICATE", validate_provenance_record(record))

    def test_scalar_and_multi_source_representation_is_ambiguous(self) -> None:
        record = self.record()
        record["source_event_id"] = "mlb:legacy"
        record["source_event_end_at"] = "2021-07-09T20:00:00+00:00"
        self.assertIn("SOURCE_EVENT_REPRESENTATION_AMBIGUOUS", validate_provenance_record(record))

    def test_exact_dataset_cutoff_is_required(self) -> None:
        record = self.record()
        report = validate_feature_provenance(
            [record],
            required_event_ids=["mlb:target"],
            required_groups=["bullpen"],
            allowed_modes_by_group={"bullpen": ["PRIOR_EVENT_FINAL"]},
            required_cutoffs_by_event={"mlb:target": "2021-07-09T23:59:00+00:00"},
        )
        self.assertEqual("BLOCKED_PROVENANCE", report["status"])
        self.assertEqual(1, report["reason_counts"]["FEATURE_CUTOFF_MISMATCH"])

    def test_equivalent_iso_cutoff_representation_passes(self) -> None:
        record = self.record()
        report = validate_feature_provenance(
            [record],
            required_event_ids=["mlb:target"],
            required_groups=["bullpen"],
            allowed_modes_by_group={"bullpen": ["PRIOR_EVENT_FINAL"]},
            required_cutoffs_by_event={"mlb:target": "2021-07-10T00:00:00Z"},
        )
        self.assertEqual("PASS", report["status"])


class MultiSourceFeatureProvenanceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "feature-provenance-record.schema.json").read_text(encoding="utf-8")
        )
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def record(self) -> dict:
        return MultiSourceFeatureProvenanceTests().record()

    def test_multi_source_shape_validates(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(self.record())))

    def test_legacy_scalar_shape_still_validates(self) -> None:
        record = self.record()
        record.pop("source_events")
        record["source_event_id"] = "mlb:prior-1"
        record["source_event_end_at"] = "2021-07-09T22:00:00+00:00"
        self.assertEqual([], list(self.validator.iter_errors(record)))

    def test_schema_rejects_both_representations(self) -> None:
        record = self.record()
        record["source_event_id"] = "mlb:legacy"
        record["source_event_end_at"] = "2021-07-09T22:00:00+00:00"
        self.assertTrue(list(self.validator.iter_errors(record)))

    def test_schema_rejects_empty_source_events(self) -> None:
        record = self.record()
        record["source_events"] = []
        self.assertTrue(list(self.validator.iter_errors(record)))


if __name__ == "__main__":
    unittest.main()
