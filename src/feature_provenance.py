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
    except (TypeError, ValueError) as exc:
        raise FeatureProvenanceError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise FeatureProvenanceError(f"{field} must be timezone-aware")
    return parsed


def _validate_prior_source(
    *, target_event_id: str, source_event_id: str, source_event_end_at: str,
    cutoff: datetime, reasons: list[str], index: int | None = None,
) -> None:
    suffix = "" if index is None else f"[{index}]"
    if not source_event_id:
        reasons.append("MISSING_SOURCE_EVENT_ID")
        return
    if source_event_id == target_event_id:
        reasons.append("CURRENT_EVENT_RESULT_LEAKAGE")
    if not source_event_end_at:
        reasons.append("MISSING_SOURCE_EVENT_END_AT")
        return
    try:
        if _ts(source_event_end_at, f"source_event_end_at{suffix}") >= cutoff:
            reasons.append("SOURCE_EVENT_NOT_FINAL_BEFORE_CUTOFF")
    except FeatureProvenanceError:
        reasons.append("SOURCE_EVENT_END_INVALID")


def validate_provenance_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return reason codes; empty tuple means the record is admissible."""
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
        target_event_id = str(record["event_id"])
        has_multi = "source_events" in record
        has_scalar = "source_event_id" in record or "source_event_end_at" in record
        if has_multi and has_scalar:
            reasons.append("SOURCE_EVENT_REPRESENTATION_AMBIGUOUS")
        elif has_multi:
            source_events = record.get("source_events")
            if not isinstance(source_events, Sequence) or isinstance(source_events, (str, bytes)) or not source_events:
                reasons.append("SOURCE_EVENTS_EMPTY")
            else:
                seen_ids: set[str] = set()
                for index, source in enumerate(source_events):
                    if not isinstance(source, Mapping):
                        reasons.append("SOURCE_EVENT_INVALID")
                        continue
                    source_id = str(source.get("event_id", "")).strip()
                    end_at = str(source.get("end_at", "")).strip()
                    if source_id in seen_ids and source_id:
                        reasons.append("SOURCE_EVENT_DUPLICATE")
                    seen_ids.add(source_id)
                    _validate_prior_source(
                        target_event_id=target_event_id,
                        source_event_id=source_id,
                        source_event_end_at=end_at,
                        cutoff=cutoff,
                        reasons=reasons,
                        index=index,
                    )
        elif has_scalar:
            _validate_prior_source(
                target_event_id=target_event_id,
                source_event_id=str(record.get("source_event_id", "")).strip(),
                source_event_end_at=str(record.get("source_event_end_at", "")).strip(),
                cutoff=cutoff,
                reasons=reasons,
            )
        else:
            reasons.append("MISSING_SOURCE_EVENT_PROVENANCE")

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
    required_cutoffs_by_event: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate full row-level coverage for every enabled feature group.

    When ``required_cutoffs_by_event`` is supplied, provenance must use the exact
    dataset cutoff instant for that event. A later relaxed cutoff is never accepted.
    """
    normalized_events = [str(event_id) for event_id in required_event_ids]
    normalized_groups = [str(group) for group in required_groups]
    expected = {(event_id, group) for event_id in normalized_events for group in normalized_groups}
    seen: set[tuple[str, str]] = set()
    reason_counts: dict[str, int] = {}
    invalid_records = 0

    cutoff_map: dict[str, datetime] = {}
    if required_cutoffs_by_event is not None:
        for event_id in normalized_events:
            raw = required_cutoffs_by_event.get(event_id)
            if raw is None:
                reason_counts["MISSING_DATASET_FEATURE_CUTOFF"] = reason_counts.get("MISSING_DATASET_FEATURE_CUTOFF", 0) + 1
                continue
            try:
                cutoff_map[event_id] = _ts(raw, f"required_cutoff[{event_id}]")
            except FeatureProvenanceError:
                reason_counts["DATASET_FEATURE_CUTOFF_INVALID"] = reason_counts.get("DATASET_FEATURE_CUTOFF_INVALID", 0) + 1

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
        if group not in normalized_groups:
            reasons.append("UNREQUESTED_FEATURE_GROUP")
        elif str(record.get("availability_mode", "")) not in allowed:
            reasons.append("MODE_NOT_ALLOWED_FOR_FEATURE_GROUP")

        if required_cutoffs_by_event is not None and key[0] in cutoff_map:
            try:
                if _ts(str(record.get("feature_cutoff_at", "")), "feature_cutoff_at") != cutoff_map[key[0]]:
                    reasons.append("FEATURE_CUTOFF_MISMATCH")
            except FeatureProvenanceError:
                reasons.append("FEATURE_CUTOFF_INVALID")

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
