"""Fail-closed point-in-time provenance validation for model features."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
ALLOWED_MODES = {
    "PRIOR_EVENT_FINAL",
    "PREGAME_SNAPSHOT",
    "FORECAST_RUN",
    "STATIC_KNOWN_BEFORE_CUTOFF",
}


class FeatureProvenanceError(ValueError):
    pass


def _ts(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeatureProvenanceError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise FeatureProvenanceError(f"{field} must be timezone-aware")
    return parsed


def validate_provenance_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return reason codes; empty tuple means the record is admissible.

    The validator deliberately treats timestamp/provenance uncertainty as a hard
    block. It never infers that postgame data must have been known pregame.
    """
    reasons: list[str] = []
    required = (
        "event_id", "feature_group", "source", "source_record_id",
        "availability_mode", "feature_cutoff_at", "source_sha256",
    )
    for field in required:
        if not str(record.get(field, "")).strip():
            reasons.append(f"MISSING_{field.upper()}")
    if reasons:
        return tuple(sorted(set(reasons)))

    mode = str(record["availability_mode"])
    if mode not in ALLOWED_MODES:
        reasons.append("AVAILABILITY_MODE_UNSUPPORTED")
        return tuple(reasons)
    if not SHA256_RE.fullmatch(str(record["source_sha256"])):
        reasons.append("SOURCE_SHA256_INVALID")

    try:
        cutoff = _ts(str(record["feature_cutoff_at"]), "feature_cutoff_at")
    except FeatureProvenanceError:
        reasons.append("FEATURE_CUTOFF_INVALID")
        return tuple(sorted(set(reasons)))

    if mode == "PRIOR_EVENT_FINAL":
        source_event_id = str(record.get("source_event_id", "")).strip()
        source_event_end_at = str(record.get("source_event_end_at", "")).strip()
        if not source_event_id:
            reasons.append("MISSING_SOURCE_EVENT_ID")
        if source_event_id == str(record["event_id"]):
            reasons.append("CURRENT_EVENT_RESULT_LEAKAGE")
        if not source_event_end_at:
            reasons.append("MISSING_SOURCE_EVENT_END_AT")
        else:
            try:
                if _ts(source_event_end_at, "source_event_end_at") >= cutoff:
                    reasons.append("SOURCE_EVENT_NOT_FINAL_BEFORE_CUTOFF")
            except FeatureProvenanceError:
                reasons.append("SOURCE_EVENT_END_INVALID")

    elif mode == "PREGAME_SNAPSHOT":
        observed_at = str(record.get("observed_at", "")).strip()
        if not observed_at:
            reasons.append("MISSING_OBSERVED_AT")
        else:
            try:
                if _ts(observed_at, "observed_at") > cutoff:
                    reasons.append("SNAPSHOT_AFTER_FEATURE_CUTOFF")
            except FeatureProvenanceError:
                reasons.append("OBSERVED_AT_INVALID")

    elif mode == "FORECAST_RUN":
        issued_at = str(record.get("forecast_issued_at", "")).strip()
        target_at = str(record.get("forecast_target_at", "")).strip()
        if not issued_at:
            reasons.append("MISSING_FORECAST_ISSUED_AT")
        if not target_at:
            reasons.append("MISSING_FORECAST_TARGET_AT")
        if issued_at:
            try:
                if _ts(issued_at, "forecast_issued_at") > cutoff:
                    reasons.append("FORECAST_ISSUED_AFTER_FEATURE_CUTOFF")
            except FeatureProvenanceError:
                reasons.append("FORECAST_ISSUED_AT_INVALID")
        if target_at:
            try:
                if _ts(target_at, "forecast_target_at") < cutoff:
                    reasons.append("FORECAST_TARGET_BEFORE_FEATURE_CUTOFF")
            except FeatureProvenanceError:
                reasons.append("FORECAST_TARGET_AT_INVALID")

    elif mode == "STATIC_KNOWN_BEFORE_CUTOFF":
        effective_at = str(record.get("effective_at", "")).strip()
        observed_at = str(record.get("observed_at", "")).strip()
        if not effective_at:
            reasons.append("MISSING_EFFECTIVE_AT")
        if not observed_at:
            reasons.append("MISSING_OBSERVED_AT")
        for field, value in (("effective_at", effective_at), ("observed_at", observed_at)):
            if value:
                try:
                    if _ts(value, field) > cutoff:
                        reasons.append(f"{field.upper()}_AFTER_FEATURE_CUTOFF")
                except FeatureProvenanceError:
                    reasons.append(f"{field.upper()}_INVALID")

    return tuple(sorted(set(reasons)))


def validate_feature_provenance(
    records: Sequence[Mapping[str, Any]],
    *,
    required_event_ids: Sequence[str],
    required_groups: Sequence[str],
    allowed_modes_by_group: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Validate full row-level coverage for every enabled feature group."""
    expected = {(str(event_id), str(group)) for event_id in required_event_ids for group in required_groups}
    seen: set[tuple[str, str]] = set()
    reason_counts: dict[str, int] = {}
    invalid_records = 0

    for record in records:
        key = (str(record.get("event_id", "")), str(record.get("feature_group", "")))
        if key in seen:
            reason_counts["DUPLICATE_EVENT_GROUP_PROVENANCE"] = reason_counts.get("DUPLICATE_EVENT_GROUP_PROVENANCE", 0) + 1
            invalid_records += 1
            continue
        seen.add(key)
        reasons = list(validate_provenance_record(record))
        group = key[1]
        allowed = set(allowed_modes_by_group.get(group, ()))
        if group not in required_groups:
            reasons.append("UNREQUESTED_FEATURE_GROUP")
        elif str(record.get("availability_mode", "")) not in allowed:
            reasons.append("MODE_NOT_ALLOWED_FOR_FEATURE_GROUP")
        if reasons:
            invalid_records += 1
            for reason in sorted(set(reasons)):
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    missing = expected - seen
    unexpected = seen - expected
    if missing:
        reason_counts["MISSING_EVENT_GROUP_PROVENANCE"] = len(missing)
    if unexpected:
        reason_counts["UNEXPECTED_EVENT_GROUP_PROVENANCE"] = len(unexpected)

    status = "PASS" if not reason_counts else "BLOCKED_PROVENANCE"
    return {
        "status": status,
        "expected_records": len(expected),
        "provided_records": len(records),
        "invalid_records": invalid_records,
        "missing_records": len(missing),
        "unexpected_records": len(unexpected),
        "reason_counts": dict(sorted(reason_counts.items())),
    }
