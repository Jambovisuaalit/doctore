"""MLB feature-schema v2 completeness gate for aggregate prior-event sources.

The generic aggregate validator checks strict-final conflicts and acquisition
rejects. MLB v3 schedule resolution additionally exposes non-strict schedule
rows that could not be proven as completed-early domain exclusions. Park
features must fail closed when any such gamePk remains unresolved.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


class MlbV2AggregateGateError(ValueError):
    pass


def unresolved_schedule_count(source_manifest: Mapping[str, Any]) -> int:
    value = source_manifest.get("unresolved_no_strict_played_final")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MlbV2AggregateGateError(
            f"invalid source manifest unresolved_no_strict_played_final: {value!r}"
        )
    return value


def validate_mlb_v2_source_collection_completeness(
    source_manifest_bytes_by_id: Mapping[str, bytes],
    *,
    required_collection_ids: Sequence[str],
) -> tuple[str, ...]:
    """Require explicit zero unresolved schedule gamePks for every MLB v2 collection."""
    reasons: list[str] = []
    seen: set[str] = set()
    for collection_id in required_collection_ids:
        collection_id = str(collection_id).strip()
        if not collection_id:
            reasons.append("SOURCE_COLLECTION_ID_MISSING")
            continue
        if collection_id in seen:
            reasons.append("SOURCE_COLLECTION_DUPLICATE")
            continue
        seen.add(collection_id)

        raw = source_manifest_bytes_by_id.get(collection_id)
        if raw is None:
            reasons.append("SOURCE_COLLECTION_MANIFEST_MISSING")
            continue
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            reasons.append("SOURCE_COLLECTION_MANIFEST_JSON_INVALID")
            continue
        if not isinstance(manifest, Mapping):
            reasons.append("SOURCE_COLLECTION_MANIFEST_INVALID")
            continue
        if manifest.get("schema_version") != "doctore.mlb-feature-source-manifest.v2":
            reasons.append("SOURCE_COLLECTION_SCHEMA_INVALID")
            continue
        try:
            unresolved = unresolved_schedule_count(manifest)
        except MlbV2AggregateGateError:
            reasons.append("SOURCE_COLLECTION_UNRESOLVED_SCHEDULE_COUNT_INVALID")
            continue
        if unresolved != 0:
            reasons.append("SOURCE_COLLECTION_HAS_UNRESOLVED_SCHEDULE_GAMEPKS")

    return tuple(sorted(set(reasons)))
