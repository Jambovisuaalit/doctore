from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aggregate_feature_provenance import (
    canonical_bytes,
    sha256_bytes,
    validate_aggregate_feature_provenance,
)
from feature_provenance import validate_provenance_record


class AggregateFeatureProvenanceTests(unittest.TestCase):
    def source_manifest(self, *, unresolved: int = 0) -> dict:
        return {
            "schema_version": "doctore.mlb-feature-source-manifest.v2",
            "season": 2012,
            "strict_final_conflicts": unresolved,
            "hydration_reject_count": 0,
            "timestamp_or_core_reject_count": 0,
        }

    def evidence(self, *, unresolved: int = 0) -> tuple[dict, dict, bytes, dict[str, bytes]]:
        source_manifest_bytes = canonical_bytes(self.source_manifest(unresolved=unresolved))
        collection_id = "mlb-v2-source-2012:test"
        aggregate_artifact = canonical_bytes({
            "event_id": "mlb:target",
            "feature_group": "park",
            "features": {
                "park_games_prior": 2,
                "park_total_runs_mean_prior": 8.5,
                "park_run_factor_prior": 1.0,
            },
        })
        contributors = [
            {"event_id": "mlb:1", "end_at": "2021-07-08T20:00:00Z", "source_sha256": "a" * 64},
            {"event_id": "mlb:2", "end_at": "2021-07-09T20:00:00Z", "source_sha256": "b" * 64},
        ]
        manifest = {
            "schema_version": "doctore.aggregate-contributors.v1",
            "manifest_id": "park:mlb:target:v1",
            "event_id": "mlb:target",
            "feature_group": "park",
            "feature_cutoff_at": "2021-07-10T18:00:00Z",
            "derivation_version": "park-prior-mean-v1",
            "contributor_count": len(contributors),
            "latest_contributor_end_at": "2021-07-09T20:00:00Z",
            "contributors": contributors,
            "source_collections": [{
                "collection_id": collection_id,
                "season": 2012,
                "manifest_sha256": sha256_bytes(source_manifest_bytes),
                "unresolved_candidate_reject_count": unresolved,
            }],
        }
        aggregate_sha = sha256_bytes(aggregate_artifact)
        record = {
            "schema_version": "doctore.feature-provenance.v1",
            "event_id": "mlb:target",
            "feature_group": "park",
            "source": "Doctore prior-only park aggregate",
            "source_record_id": "park:mlb:target:v1",
            "availability_mode": "AGGREGATE_PRIOR_EVENT_FINAL",
            "feature_cutoff_at": "2021-07-10T18:00:00Z",
            "source_sha256": aggregate_sha,
            "contributor_manifest_id": manifest["manifest_id"],
            "contributor_manifest_sha256": sha256_bytes(canonical_bytes(manifest)),
            "aggregate_artifact_sha256": aggregate_sha,
            "contributor_count": len(contributors),
            "latest_contributor_end_at": "2021-07-09T20:00:00Z",
            "derivation_version": "park-prior-mean-v1",
        }
        return record, manifest, aggregate_artifact, {collection_id: source_manifest_bytes}

    def test_valid_aggregate_provenance_passes(self) -> None:
        record, manifest, artifact, collections = self.evidence()
        self.assertEqual((), validate_provenance_record(record))
        self.assertEqual((), validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        ))

    def test_current_event_contributor_fails(self) -> None:
        record, manifest, artifact, collections = self.evidence()
        manifest["contributors"][0]["event_id"] = "mlb:target"
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("CURRENT_EVENT_RESULT_LEAKAGE", reasons)

    def test_late_contributor_fails(self) -> None:
        record, manifest, artifact, collections = self.evidence()
        manifest["contributors"][1]["end_at"] = "2021-07-10T18:00:00Z"
        manifest["latest_contributor_end_at"] = "2021-07-10T18:00:00Z"
        record["latest_contributor_end_at"] = "2021-07-10T18:00:00Z"
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("CONTRIBUTOR_NOT_FINAL_BEFORE_CUTOFF", reasons)
        self.assertIn("LATEST_CONTRIBUTOR_NOT_FINAL_BEFORE_CUTOFF", reasons)

    def test_duplicate_contributor_fails(self) -> None:
        record, manifest, artifact, collections = self.evidence()
        manifest["contributors"][1]["event_id"] = "mlb:1"
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("CONTRIBUTOR_EVENT_DUPLICATE", reasons)

    def test_manifest_sha_mismatch_fails(self) -> None:
        record, manifest, artifact, collections = self.evidence()
        record["contributor_manifest_sha256"] = "c" * 64
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("CONTRIBUTOR_MANIFEST_SHA_MISMATCH", reasons)

    def test_aggregate_artifact_sha_mismatch_fails(self) -> None:
        record, manifest, _, collections = self.evidence()
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=b"different\n",
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("AGGREGATE_ARTIFACT_SHA_MISMATCH", reasons)

    def test_unresolved_source_collection_blocks_aggregate(self) -> None:
        record, manifest, artifact, collections = self.evidence(unresolved=1)
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=collections,
        )
        self.assertIn("SOURCE_COLLECTION_HAS_UNRESOLVED_CANDIDATES", reasons)

    def test_missing_source_collection_manifest_fails(self) -> None:
        record, manifest, artifact, _ = self.evidence()
        reasons = validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id={},
        )
        self.assertIn("SOURCE_COLLECTION_MANIFEST_MISSING", reasons)


class AggregateProvenanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.feature_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "feature-provenance-record.schema.json").read_text()),
            format_checker=FormatChecker(),
        )
        cls.manifest_validator = Draft202012Validator(
            json.loads((ROOT / "contracts" / "aggregate-contributor-manifest.schema.json").read_text()),
            format_checker=FormatChecker(),
        )

    def test_aggregate_contracts_accept_valid_evidence(self) -> None:
        case = AggregateFeatureProvenanceTests()
        record, manifest, _, _ = case.evidence()
        self.assertEqual([], list(self.feature_validator.iter_errors(record)))
        self.assertEqual([], list(self.manifest_validator.iter_errors(manifest)))

    def test_aggregate_mode_cannot_embed_scalar_or_array_sources(self) -> None:
        case = AggregateFeatureProvenanceTests()
        record, _, _, _ = case.evidence()
        record["source_events"] = [{"event_id": "mlb:1", "end_at": "2021-07-08T20:00:00Z"}]
        self.assertNotEqual([], list(self.feature_validator.iter_errors(record)))


if __name__ == "__main__":
    unittest.main()
