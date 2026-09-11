from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aggregate_feature_provenance import (
    POPULATION_RULE,
    canonical_bytes,
    sha256_bytes,
    validate_aggregate_feature_provenance,
)
from feature_provenance import validate_provenance_record


class AggregateFeatureProvenanceTests(unittest.TestCase):
    def source_rows(self) -> list[dict]:
        return [
            {
                "event_id": "mlb:1",
                "official_date": "2012-04-05",
                "final_event_at": "2012-04-05T22:00:00Z",
                "source_sha256": "a" * 64,
                "venue": {"id": 10, "name": "Target Park"},
                "final_total_runs": 8,
                "park_status": "PASS",
            },
            {
                "event_id": "mlb:2",
                "official_date": "2012-04-06",
                "final_event_at": "2012-04-06T22:00:00Z",
                "source_sha256": "b" * 64,
                "venue": {"id": 11, "name": "Other Park"},
                "final_total_runs": 10,
                "park_status": "PASS",
            },
            {
                "event_id": "mlb:future",
                "official_date": "2012-04-08",
                "final_event_at": "2012-04-08T22:00:00Z",
                "source_sha256": "c" * 64,
                "venue": {"id": 10, "name": "Target Park"},
                "final_total_runs": 4,
                "park_status": "PASS",
            },
        ]

    def source_manifest(self, records_bytes: bytes, *, unresolved: int = 0) -> dict:
        return {
            "schema_version": "doctore.mlb-feature-source-manifest.v2",
            "season": 2012,
            "strict_final_conflicts": unresolved,
            "hydration_reject_count": 0,
            "timestamp_or_core_reject_count": 0,
            "normalized_source_records": 3,
            "park_pass_records": 3,
            "records_sha256": sha256_bytes(records_bytes),
        }

    def evidence(self, *, unresolved: int = 0):
        rows = self.source_rows()
        records_bytes = b"".join(canonical_bytes(row) for row in rows)
        source_manifest_bytes = canonical_bytes(self.source_manifest(records_bytes, unresolved=unresolved))
        collection_id = "mlb-v2-source-2012:test"
        cutoff = "2012-04-07T18:00:00Z"
        contributors = [
            {
                "event_id": "mlb:1",
                "end_at": "2012-04-05T22:00:00Z",
                "source_sha256": "a" * 64,
                "venue_id": 10,
                "final_total_runs": 8,
            },
            {
                "event_id": "mlb:2",
                "end_at": "2012-04-06T22:00:00Z",
                "source_sha256": "b" * 64,
                "venue_id": 11,
                "final_total_runs": 10,
            },
        ]
        league_mean = 9.0
        venue_mean = 8.0
        aggregate = {
            "schema_version": "doctore.park-aggregate.v1",
            "event_id": "mlb:target",
            "feature_group": "park",
            "feature_cutoff_at": cutoff,
            "target_venue_id": 10,
            "derivation_version": "park-prior-mean-v1",
            "features": {
                "park_games_prior": 1,
                "park_total_runs_mean_prior": venue_mean,
                "park_run_factor_prior": venue_mean / league_mean,
            },
        }
        aggregate_artifact = canonical_bytes(aggregate)
        manifest = {
            "schema_version": "doctore.aggregate-contributors.v1",
            "manifest_id": "park:mlb:target:v1",
            "event_id": "mlb:target",
            "feature_group": "park",
            "feature_cutoff_at": cutoff,
            "derivation_version": "park-prior-mean-v1",
            "population_rule": POPULATION_RULE,
            "history_start_season": 2012,
            "history_end_season": 2012,
            "target_venue_id": 10,
            "contributor_count": len(contributors),
            "venue_contributor_count": 1,
            "latest_contributor_end_at": "2012-04-06T22:00:00Z",
            "contributors": contributors,
            "source_collections": [{
                "collection_id": collection_id,
                "season": 2012,
                "manifest_sha256": sha256_bytes(source_manifest_bytes),
                "records_sha256": sha256_bytes(records_bytes),
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
            "feature_cutoff_at": cutoff,
            "source_sha256": aggregate_sha,
            "contributor_manifest_id": manifest["manifest_id"],
            "contributor_manifest_sha256": sha256_bytes(canonical_bytes(manifest)),
            "aggregate_artifact_sha256": aggregate_sha,
            "contributor_count": len(contributors),
            "latest_contributor_end_at": "2012-04-06T22:00:00Z",
            "derivation_version": "park-prior-mean-v1",
        }
        return (
            record,
            manifest,
            aggregate_artifact,
            {collection_id: source_manifest_bytes},
            {collection_id: records_bytes},
        )

    def validate(self, record, manifest, artifact, manifests, records):
        return validate_aggregate_feature_provenance(
            record,
            contributor_manifest=manifest,
            aggregate_artifact_bytes=artifact,
            source_collection_manifest_bytes_by_id=manifests,
            source_collection_records_bytes_by_id=records,
        )

    def test_valid_aggregate_provenance_passes(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        self.assertEqual((), validate_provenance_record(record))
        self.assertEqual((), self.validate(record, manifest, artifact, manifests, records))

    def test_current_event_contributor_fails(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        manifest["contributors"][0]["event_id"] = "mlb:target"
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("CURRENT_EVENT_RESULT_LEAKAGE", reasons)

    def test_omitted_prior_event_fails_population_check(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        manifest["contributors"] = manifest["contributors"][:1]
        manifest["contributor_count"] = 1
        record["contributor_count"] = 1
        manifest["latest_contributor_end_at"] = "2012-04-05T22:00:00Z"
        record["latest_contributor_end_at"] = "2012-04-05T22:00:00Z"
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("CONTRIBUTOR_POPULATION_MISMATCH", reasons)

    def test_fabricated_contributor_value_fails_source_record_match(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        manifest["contributors"][0]["final_total_runs"] = 99
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("CONTRIBUTOR_SOURCE_RECORD_MISMATCH", reasons)

    def test_future_source_row_is_not_a_contributor(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        self.assertNotIn("mlb:future", {row["event_id"] for row in manifest["contributors"]})
        self.assertEqual((), self.validate(record, manifest, artifact, manifests, records))

    def test_bad_park_math_fails_recomputation(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        parsed = json.loads(artifact)
        parsed["features"]["park_run_factor_prior"] = 1.5
        artifact = canonical_bytes(parsed)
        new_sha = sha256_bytes(artifact)
        record["aggregate_artifact_sha256"] = new_sha
        record["source_sha256"] = new_sha
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("PARK_RUN_FACTOR_MISMATCH", reasons)

    def test_unresolved_source_collection_blocks_aggregate(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence(unresolved=1)
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("SOURCE_COLLECTION_HAS_UNRESOLVED_CANDIDATES", reasons)

    def test_records_sha_mismatch_fails(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        collection_id = next(iter(records))
        records[collection_id] = records[collection_id] + b"{}\n"
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("SOURCE_COLLECTION_RECORDS_SHA_MISMATCH", reasons)

    def test_missing_history_season_fails(self) -> None:
        record, manifest, artifact, manifests, records = self.evidence()
        manifest["history_start_season"] = 2011
        record["contributor_manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
        reasons = self.validate(record, manifest, artifact, manifests, records)
        self.assertIn("SOURCE_COLLECTION_SEASON_RANGE_INCOMPLETE", reasons)


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
        record, manifest, _, _, _ = case.evidence()
        self.assertEqual([], list(self.feature_validator.iter_errors(record)))
        self.assertEqual([], list(self.manifest_validator.iter_errors(manifest)))

    def test_aggregate_mode_cannot_embed_scalar_or_array_sources(self) -> None:
        case = AggregateFeatureProvenanceTests()
        record, _, _, _, _ = case.evidence()
        record["source_events"] = [{"event_id": "mlb:1", "end_at": "2012-04-05T22:00:00Z"}]
        self.assertNotEqual([], list(self.feature_validator.iter_errors(record)))


if __name__ == "__main__":
    unittest.main()
