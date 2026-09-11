"""Fail-closed validation for compact aggregate prior-event provenance."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from feature_provenance import validate_provenance_record

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


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


def validate_aggregate_feature_provenance(
    record: Mapping[str, Any],
    *,
    contributor_manifest: Mapping[str, Any],
    aggregate_artifact_bytes: bytes,
    source_collection_manifest_bytes_by_id: Mapping[str, bytes],
) -> tuple[str, ...]:
    """Validate compact row provenance against all referenced immutable evidence.

    This function is intentionally stronger than ``validate_provenance_record``:
    it opens the contributor manifest, verifies every prior event against the
    exact cutoff, verifies the aggregate artifact digest, and verifies each
    referenced MLB source-collection manifest is v2 and has zero unresolved
    strict-final acquisition failures.
    """
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

    contributors = contributor_manifest.get("contributors")
    if not isinstance(contributors, Sequence) or isinstance(contributors, (str, bytes)) or not contributors:
        reasons.append("CONTRIBUTORS_EMPTY")
        contributors = []

    seen_event_ids: set[str] = set()
    parsed_end_times: list[datetime] = []
    for contributor in contributors:
        if not isinstance(contributor, Mapping):
            reasons.append("CONTRIBUTOR_INVALID")
            continue
        event_id = str(contributor.get("event_id", "")).strip()
        if not event_id:
            reasons.append("CONTRIBUTOR_EVENT_ID_MISSING")
        elif event_id in seen_event_ids:
            reasons.append("CONTRIBUTOR_EVENT_DUPLICATE")
        elif event_id == target_event_id:
            reasons.append("CURRENT_EVENT_RESULT_LEAKAGE")
        seen_event_ids.add(event_id)

        if not SHA256_RE.fullmatch(str(contributor.get("source_sha256", ""))):
            reasons.append("CONTRIBUTOR_SOURCE_SHA_INVALID")
        try:
            end_at = _ts(contributor.get("end_at"), f"contributor[{event_id}].end_at")
            parsed_end_times.append(end_at)
            if end_at >= cutoff:
                reasons.append("CONTRIBUTOR_NOT_FINAL_BEFORE_CUTOFF")
        except AggregateProvenanceError:
            reasons.append("CONTRIBUTOR_END_AT_INVALID")

    count = len(contributors)
    if contributor_manifest.get("contributor_count") != count:
        reasons.append("MANIFEST_CONTRIBUTOR_COUNT_MISMATCH")
    if record.get("contributor_count") != count:
        reasons.append("RECORD_CONTRIBUTOR_COUNT_MISMATCH")

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

    source_collections = contributor_manifest.get("source_collections")
    if not isinstance(source_collections, Sequence) or isinstance(source_collections, (str, bytes)) or not source_collections:
        reasons.append("SOURCE_COLLECTIONS_EMPTY")
        source_collections = []

    seen_collection_ids: set[str] = set()
    seen_seasons: set[int] = set()
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
        elif season in seen_seasons:
            reasons.append("SOURCE_COLLECTION_SEASON_DUPLICATE")
        else:
            seen_seasons.add(season)

        expected_sha = str(collection.get("manifest_sha256", ""))
        if not SHA256_RE.fullmatch(expected_sha):
            reasons.append("SOURCE_COLLECTION_MANIFEST_SHA_INVALID")
        raw_manifest = source_collection_manifest_bytes_by_id.get(collection_id)
        if raw_manifest is None:
            reasons.append("SOURCE_COLLECTION_MANIFEST_MISSING")
            continue
        if sha256_bytes(raw_manifest) != expected_sha:
            reasons.append("SOURCE_COLLECTION_MANIFEST_SHA_MISMATCH")
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

    return tuple(sorted(set(reasons)))
