from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mlb_v2_aggregate_gate import validate_mlb_v2_source_collection_completeness


def encoded(unresolved):
    return json.dumps({
        "schema_version": "doctore.mlb-feature-source-manifest.v2",
        "unresolved_no_strict_played_final": unresolved,
    }).encode("utf-8")


class MlbV2AggregateGateTests(unittest.TestCase):
    def test_zero_unresolved_schedule_gamepks_passes(self) -> None:
        manifests = {"2012": encoded(0)}
        self.assertEqual(
            (),
            validate_mlb_v2_source_collection_completeness(
                manifests,
                required_collection_ids=["2012"],
            ),
        )

    def test_nonzero_unresolved_schedule_gamepks_blocks(self) -> None:
        manifests = {"2012": encoded(2)}
        reasons = validate_mlb_v2_source_collection_completeness(
            manifests,
            required_collection_ids=["2012"],
        )
        self.assertIn("SOURCE_COLLECTION_HAS_UNRESOLVED_SCHEDULE_GAMEPKS", reasons)

    def test_missing_counter_blocks_fail_closed(self) -> None:
        manifests = {"2012": json.dumps({
            "schema_version": "doctore.mlb-feature-source-manifest.v2"
        }).encode("utf-8")}
        reasons = validate_mlb_v2_source_collection_completeness(
            manifests,
            required_collection_ids=["2012"],
        )
        self.assertIn("SOURCE_COLLECTION_UNRESOLVED_SCHEDULE_COUNT_INVALID", reasons)

    def test_invalid_schema_blocks(self) -> None:
        manifests = {"2012": json.dumps({
            "schema_version": "legacy",
            "unresolved_no_strict_played_final": 0,
        }).encode("utf-8")}
        reasons = validate_mlb_v2_source_collection_completeness(
            manifests,
            required_collection_ids=["2012"],
        )
        self.assertIn("SOURCE_COLLECTION_SCHEMA_INVALID", reasons)

    def test_missing_collection_blocks(self) -> None:
        reasons = validate_mlb_v2_source_collection_completeness(
            {},
            required_collection_ids=["2012"],
        )
        self.assertIn("SOURCE_COLLECTION_MANIFEST_MISSING", reasons)


if __name__ == "__main__":
    unittest.main()
