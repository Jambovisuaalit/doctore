"""Fail-closed validation for compact aggregate prior-event provenance.

Aggregate provenance is accepted only when the referenced source collections
prove an exact contributor population. The validator re-opens immutable source
manifests + source-record JSONL, reconstructs the expected prior-event set, and
recomputes the park aggregate. This prevents a syntactically valid manifest
from silently omitting inconvenient prior games.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Sequence

from feature_provenance import validate_provenance_record

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
POPULATION_RULE = "all_source_collection_events_final_before_cutoff_v1"
PARK_ARTIFACT_SCHEMA = "doctore.park-aggregate.v1"


class AggregateProvenanceError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AggregateProvenanceError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise AggregateProvenanceError(f"{field} must be timezone-aware")
    return parsed


def unresolved_candidate_reject_count(source_manifest: Mapping[str, Any]) -> int:
    """Return unresolved strict-final source failures; domain exclusions do not count."""
    required = (
        "strict_final_conflicts",
        "hydration_reject_count",
        "timestamp_or_core_reject_count",
    )
    total = 0
    for field in required:
        value = source_manifest.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AggregateProvenanceError(f"invalid source manifest {field}: {value!r}")
        total += value
    return total


def _parse_jsonl(raw: bytes, *, collection_id: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for index, line in enumerate(raw.splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AggregateProvenanceError(
                f"invalid source record JSONL {collection_id}[{index}]"
            ) from exc
        if not isinstance(row, Mapping):
            raise AggregateProvenanceError(
                f"source record must be object: {collection_id}[{index}]"
            )
        rows.append(row)
    return rows


def _project_source_record(row: Mapping[str, Any]) -> dict[str, Any]:
    event_id = str(row.get("event_id", "")).strip()
    source_sha = str(row.get("source_sha256", "")).strip()
    venue = row.get("venue")
    if not event_id:
        raise AggregateProvenanceError("source event_id missing")
    if not SHA256_RE.fullmatch(source_sha):
        raise AggregateProvenanceError(f"source_sha256 invalid for {event_id}")
    if not isinstance(venue, Mapping):
        raise AggregateProvenanceError(f"venue missing for {event_id}")
    try:
        venue_id = int(venue["id"])
        total_runs = int(row["final_total_runs"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AggregateProvenanceError(f"park fields invalid for {event_id}") from exc
    if venue_id <= 0 or total_runs < 0:
        raise AggregateProvenanceError(f"park fields out of range for {event_id}")
    if row.get("park_status") != "PASS":
        raise AggregateProvenanceError(f"park source not PASS for {event_id}")
    end_at = str(row.get("final_event_at", "")).strip()
    _ts(end_at, f"source[{event_id}].final_event_at")
    return {
        "event_id": event_id,
        "end_at": end_at,
        "source_sha256": source_sha,
        "venue_id": venue_id,
        "final_total_runs": total_runs,
    }


def _float_matches(actual: Any, expected: float) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-12)


def validate_aggregate_feature_provenance(
    record: Mapping[str, Any],
    *,
    contributor_manifest: Mapping[str, Any],
    aggregate_artifact_bytes: bytes,
    source_collection_manifest_bytes_by_id: Mapping[str, bytes],
    source_collection_records_bytes_by_id: Mapping[str, bytes],
) -> tuple[str, ...]:
    """Validate aggregate row provenance against exact immutable source populations."""
    reasons = list(validate_provenance_record(record))
    if str(record.get("availability_mode", "")) != "AGGREGATE_PRIOR_EVENT_FINAL":
        reasons.append("AGGREGATE_MODE_REQUIRED")
        return tuple(sorted(set(reasons)))

    target_event_id = str(record.get("event_id", ""))
    feature_group = str(record.get("feature_group", ""))
    derivation_version = str(record.get("derivation_version", ""))
    manifest_id = str(record.get("contributor_manifest_id", ""))

    try:
        cutoff = _ts(record.get("feature_cutoff_at"), "feature_cutoff_at")
    except AggregateProvenanceError:
        reasons.append("FEATURE_CUTOFF_INVALID")
        return tuple(sorted(set(reasons)))

    actual_manifest_sha = sha256_bytes(canonical_bytes(contributor_manifest))
    if actual_manifest_sha != str(record.get("contributor_manifest_sha256", "")):
        reasons.append("CONTRIBUTOR_MANIFEST_SHA_MISMATCH")

    if contributor_manifest.get("schema_version") != "doctore.aggregate-contributors.v1":
        reasons.append("CONTRIBUTOR_MANIFEST_SCHEMA_INVALID")
    if str(contributor_manifest.get("manifest_id", "")) != manifest_id:
        reasons.append("CONTRIBUTOR_MANIFEST_ID_MISMATCH")
    if str(contributor_manifest.get("event_id", "")) != target_event_id:
        reasons.append("CONTRIBUTOR_TARGET_EVENT_MISMATCH")
    if str(contributor_manifest.get("feature_group", "")) != feature_group:
        reasons.append("CONTRIBUTOR_FEATURE_GROUP_MISMATCH")
    if str(contributor_manifest.get("derivation_version", "")) != derivation_version:
        reasons.append("CONTRIBUTOR_DERIVATION_VERSION_MISMATCH")
    if contributor_manifest.get("population_rule") != POPULATION_RULE:
        reasons.append("CONTRIBUTOR_POPULATION_RULE_INVALID")
    try:
        manifest_cutoff = _ts(contributor_manifest.get("feature_cutoff_at"), "manifest.feature_cutoff_at")
        if manifest_cutoff != cutoff:
            reasons.append("CONTRIBUTOR_FEATURE_CUTOFF_MISMATCH")
    except AggregateProvenanceError:
        reasons.append("CONTRIBUTOR_FEATURE_CUTOFF_INVALID")

    aggregate_sha = sha256_bytes(aggregate_artifact_bytes)
    if aggregate_sha != str(record.get("aggregate_artifact_sha256", "")):
        reasons.append("AGGREGATE_ARTIFACT_SHA_MISMATCH")
    if aggregate_sha != str(record.get("source_sha256", "")):
        reasons.append("SOURCE_SHA256_AGGREGATE_MISMATCH")

    try:
        start_season = int(contributor_manifest.get("history_start_season"))
        end_season = int(contributor_manifest.get("history_end_season"))
    except (TypeError, ValueError):
        reasons.append("HISTORY_SEASON_RANGE_INVALID")
        start_season = end_season = -1
    if start_season > end_season:
        reasons.append("HISTORY_SEASON_RANGE_INVALID")

    try:
        target_venue_id = int(contributor_manifest.get("target_venue_id"))
        if target_venue_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        reasons.append("TARGET_VENUE_ID_INVALID")
        target_venue_id = -1

    source_collections = contributor_manifest.get("source_collections")
    if not isinstance(source_collections, Sequence) or isinstance(source_collections, (str, bytes)) or not source_collections:
        reasons.append("SOURCE_COLLECTIONS_EMPTY")
        source_collections = []

    seen_collection_ids: set[str] = set()
    seen_seasons: set[int] = set()
    expected_by_event: dict[str, dict[str, Any]] = {}

    for collection in source_collections:
        if not isinstance(collection, Mapping):
            reasons.append("SOURCE_COLLECTION_INVALID")
            continue
        collection_id = str(collection.get("collection_id", "")).strip()
        if not collection_id:
            reasons.append("SOURCE_COLLECTION_ID_MISSING")
            continue
        if collection_id in seen_collection_ids:
            reasons.append("SOURCE_COLLECTION_DUPLICATE")
        seen_collection_ids.add(collection_id)

        season = collection.get("season")
        if not isinstance(season, int) or isinstance(season, bool):
            reasons.append("SOURCE_COLLECTION_SEASON_INVALID")
            season = -1
        elif season in seen_seasons:
            reasons.append("SOURCE_COLLECTION_SEASON_DUPLICATE")
        else:
            seen_seasons.add(season)

        expected_manifest_sha = str(collection.get("manifest_sha256", ""))
        expected_records_sha = str(collection.get("records_sha256", ""))
        if not SHA256_RE.fullmatch(expected_manifest_sha):
            reasons.append("SOURCE_COLLECTION_MANIFEST_SHA_INVALID")
        if not SHA256_RE.fullmatch(expected_records_sha):
            reasons.append("SOURCE_COLLECTION_RECORDS_SHA_INVALID")

        raw_manifest = source_collection_manifest_bytes_by_id.get(collection_id)
        raw_records = source_collection_records_bytes_by_id.get(collection_id)
        if raw_manifest is None:
            reasons.append("SOURCE_COLLECTION_MANIFEST_MISSING")
            continue
        if raw_records is None:
            reasons.append("SOURCE_COLLECTION_RECORDS_MISSING")
            continue
        if sha256_bytes(raw_manifest) != expected_manifest_sha:
            reasons.append("SOURCE_COLLECTION_MANIFEST_SHA_MISMATCH")
            continue
        if sha256_bytes(raw_records) != expected_records_sha:
            reasons.append("SOURCE_COLLECTION_RECORDS_SHA_MISMATCH")
            continue

        try:
            source_manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            reasons.append("SOURCE_COLLECTION_MANIFEST_JSON_INVALID")
            continue
        if source_manifest.get("schema_version") != "doctore.mlb-feature-source-manifest.v2":
            reasons.append("SOURCE_COLLECTION_SCHEMA_INVALID")
            continue
        if isinstance(season, int) and source_manifest.get("season") != season:
            reasons.append("SOURCE_COLLECTION_SEASON_MISMATCH")
        if source_manifest.get("records_sha256") != expected_records_sha:
            reasons.append("SOURCE_COLLECTION_RECORDS_SHA_MANIFEST_MISMATCH")

        try:
            actual_unresolved = unresolved_candidate_reject_count(source_manifest)
        except AggregateProvenanceError:
            reasons.append("SOURCE_COLLECTION_UNRESOLVED_COUNT_INVALID")
            continue
        declared_unresolved = collection.get("unresolved_candidate_reject_count")
        if declared_unresolved != actual_unresolved:
            reasons.append("SOURCE_COLLECTION_UNRESOLVED_COUNT_MISMATCH")
        if actual_unresolved != 0:
            reasons.append("SOURCE_COLLECTION_HAS_UNRESOLVED_CANDIDATES")

        try:
            source_rows = _parse_jsonl(raw_records, collection_id=collection_id)
        except AggregateProvenanceError:
            reasons.append("SOURCE_COLLECTION_RECORDS_JSON_INVALID")
            continue
        if source_manifest.get("normalized_source_records") != len(source_rows):
            reasons.append("SOURCE_COLLECTION_RECORD_COUNT_MISMATCH")
        if source_manifest.get("park_pass_records") != len(source_rows):
            reasons.append("SOURCE_COLLECTION_PARK_COVERAGE_INCOMPLETE")

        for row in source_rows:
            try:
                projected = _project_source_record(row)
                end_at = _ts(projected["end_at"], "projected.end_at")
            except AggregateProvenanceError:
                reasons.append("SOURCE_RECORD_INVALID")
                continue
            if end_at >= cutoff:
                continue
            event_id = projected["event_id"]
            if event_id == target_event_id:
                reasons.append("CURRENT_EVENT_RESULT_LEAKAGE")
                continue
            if event_id in expected_by_event:
                reasons.append("SOURCE_EVENT_DUPLICATE_ACROSS_COLLECTIONS")
                continue
            expected_by_event[event_id] = projected

    if start_season <= end_season:
        expected_seasons = set(range(start_season, end_season + 1))
        if seen_seasons != expected_seasons:
            reasons.append("SOURCE_COLLECTION_SEASON_RANGE_INCOMPLETE")

    contributors = contributor_manifest.get("contributors")
    if not isinstance(contributors, Sequence) or isinstance(contributors, (str, bytes)) or not contributors:
        reasons.append("CONTRIBUTORS_EMPTY")
        contributors = []

    actual_by_event: dict[str, Mapping[str, Any]] = {}
    parsed_end_times: list[datetime] = []
    for contributor in contributors:
        if not isinstance(contributor, Mapping):
            reasons.append("CONTRIBUTOR_INVALID")
            continue
        event_id = str(contributor.get("event_id", "")).strip()
        if not event_id:
            reasons.append("CONTRIBUTOR_EVENT_ID_MISSING")
            continue
        if event_id in actual_by_event:
            reasons.append("CONTRIBUTOR_EVENT_DUPLICATE")
            continue
        if event_id == target_event_id:
            reasons.append("CURRENT_EVENT_RESULT_LEAKAGE")
        actual_by_event[event_id] = contributor
        if not SHA256_RE.fullmatch(str(contributor.get("source_sha256", ""))):
            reasons.append("CONTRIBUTOR_SOURCE_SHA_INVALID")
        try:
            end_at = _ts(contributor.get("end_at"), f"contributor[{event_id}].end_at")
            parsed_end_times.append(end_at)
            if end_at >= cutoff:
                reasons.append("CONTRIBUTOR_NOT_FINAL_BEFORE_CUTOFF")
            int(contributor.get("venue_id"))
            if int(contributor.get("final_total_runs")) < 0:
                raise ValueError
        except (AggregateProvenanceError, TypeError, ValueError):
            reasons.append("CONTRIBUTOR_FIELDS_INVALID")

    if set(actual_by_event) != set(expected_by_event):
        reasons.append("CONTRIBUTOR_POPULATION_MISMATCH")
    else:
        for event_id, expected in expected_by_event.items():
            actual = actual_by_event[event_id]
            for field in ("end_at", "source_sha256", "venue_id", "final_total_runs"):
                if actual.get(field) != expected[field]:
                    reasons.append("CONTRIBUTOR_SOURCE_RECORD_MISMATCH")
                    break

    count = len(contributors)
    if contributor_manifest.get("contributor_count") != count:
        reasons.append("MANIFEST_CONTRIBUTOR_COUNT_MISMATCH")
    if record.get("contributor_count") != count:
        reasons.append("RECORD_CONTRIBUTOR_COUNT_MISMATCH")
    if expected_by_event and len(expected_by_event) != count:
        reasons.append("EXPECTED_CONTRIBUTOR_COUNT_MISMATCH")

    expected_venue_count = sum(
        1 for item in expected_by_event.values() if item["venue_id"] == target_venue_id
    )
    if expected_venue_count < 1:
        reasons.append("TARGET_VENUE_PRIOR_HISTORY_EMPTY")
    if contributor_manifest.get("venue_contributor_count") != expected_venue_count:
        reasons.append("VENUE_CONTRIBUTOR_COUNT_MISMATCH")

    if parsed_end_times:
        latest = max(parsed_end_times)
        for field, raw in (
            ("manifest", contributor_manifest.get("latest_contributor_end_at")),
            ("record", record.get("latest_contributor_end_at")),
        ):
            try:
                if _ts(raw, f"{field}.latest_contributor_end_at") != latest:
                    reasons.append(f"{field.upper()}_LATEST_CONTRIBUTOR_MISMATCH")
            except AggregateProvenanceError:
                reasons.append(f"{field.upper()}_LATEST_CONTRIBUTOR_INVALID")

    try:
        artifact = json.loads(aggregate_artifact_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reasons.append("AGGREGATE_ARTIFACT_JSON_INVALID")
        artifact = {}
    if not isinstance(artifact, Mapping):
        reasons.append("AGGREGATE_ARTIFACT_INVALID")
        artifact = {}
    if artifact.get("schema_version") != PARK_ARTIFACT_SCHEMA:
        reasons.append("AGGREGATE_ARTIFACT_SCHEMA_INVALID")
    if str(artifact.get("event_id", "")) != target_event_id:
        reasons.append("AGGREGATE_ARTIFACT_EVENT_MISMATCH")
    if str(artifact.get("feature_group", "")) != feature_group:
        reasons.append("AGGREGATE_ARTIFACT_GROUP_MISMATCH")
    if str(artifact.get("feature_cutoff_at", "")) != str(record.get("feature_cutoff_at", "")):
        reasons.append("AGGREGATE_ARTIFACT_CUTOFF_MISMATCH")
    if artifact.get("target_venue_id") != target_venue_id:
        reasons.append("AGGREGATE_ARTIFACT_VENUE_MISMATCH")
    if str(artifact.get("derivation_version", "")) != derivation_version:
        reasons.append("AGGREGATE_ARTIFACT_DERIVATION_MISMATCH")

    if expected_by_event and expected_venue_count > 0:
        league_mean = sum(item["final_total_runs"] for item in expected_by_event.values()) / len(expected_by_event)
        venue_rows = [
            item for item in expected_by_event.values() if item["venue_id"] == target_venue_id
        ]
        venue_mean = sum(item["final_total_runs"] for item in venue_rows) / len(venue_rows)
        if league_mean <= 0:
            reasons.append("LEAGUE_RUN_MEAN_NONPOSITIVE")
        else:
            expected_factor = venue_mean / league_mean
            features = artifact.get("features") if isinstance(artifact.get("features"), Mapping) else {}
            if features.get("park_games_prior") != expected_venue_count:
                reasons.append("PARK_GAMES_PRIOR_MISMATCH")
            if not _float_matches(features.get("park_total_runs_mean_prior"), venue_mean):
                reasons.append("PARK_TOTAL_RUNS_MEAN_MISMATCH")
            if not _float_matches(features.get("park_run_factor_prior"), expected_factor):
                reasons.append("PARK_RUN_FACTOR_MISMATCH")

    return tuple(sorted(set(reasons)))
