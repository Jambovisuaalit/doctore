"""Completeness proof for MLB bullpen workload history across target and supplement sources."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


class BullpenHistoryUniverseError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _pks(records: Sequence[Mapping[str, Any]], label: str) -> set[int]:
    values=[]
    for row in records:
        try:
            values.append(int(row["game_pk"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise BullpenHistoryUniverseError(f"{label} game_pk invalid") from exc
    if len(values) != len(set(values)):
        raise BullpenHistoryUniverseError(f"{label} duplicate game_pk")
    return set(values)


def validate_season_history_universe(
    *, target_manifest: Mapping[str, Any], target_records: Sequence[Mapping[str, Any]],
    supplement_manifest: Mapping[str, Any], supplement_records: Sequence[Mapping[str, Any]],
    supplement_skips: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    season = int(target_manifest.get("season"))
    if supplement_manifest.get("season") != season:
        raise BullpenHistoryUniverseError("season mismatch")
    if target_manifest.get("acquisition_policy") != "authoritative_live_schedule_resolution_v4":
        raise BullpenHistoryUniverseError("target acquisition policy is not v4")
    for field in ("strict_final_conflicts", "unresolved_no_strict_played_final",
                  "timestamp_or_core_reject_count", "bullpen_blocked_records", "hydration_reject_count"):
        if target_manifest.get(field) != 0:
            raise BullpenHistoryUniverseError(f"target hard gate failed: {field}={target_manifest.get(field)!r}")
    if target_manifest.get("normalized_source_records") != len(target_records):
        raise BullpenHistoryUniverseError("target record count mismatch")
    if any(row.get("bullpen_status") != "PASS" for row in target_records):
        raise BullpenHistoryUniverseError("target bullpen record not PASS")

    if supplement_manifest.get("policy") != "authoritative_played_target_exclusions_bullpen_history_v1":
        raise BullpenHistoryUniverseError("supplement policy invalid")
    if supplement_manifest.get("reject_count") != 0 or supplement_manifest.get("bullpen_blocked_records") != 0:
        raise BullpenHistoryUniverseError("supplement hard gate failed")
    if supplement_manifest.get("supplemental_records") != len(supplement_records):
        raise BullpenHistoryUniverseError("supplement record count mismatch")
    if any(row.get("bullpen_status") != "PASS" or row.get("bullpen_history_eligible") is not True for row in supplement_records):
        raise BullpenHistoryUniverseError("supplement record not bullpen-history eligible")

    target_pks = _pks(target_records, "target")
    supplement_pks = _pks(supplement_records, "supplement")
    if target_pks.intersection(supplement_pks):
        raise BullpenHistoryUniverseError("target and supplement overlap")

    standard_skip: set[int] = set()
    cancelled: set[int] = set()
    for item in supplement_skips:
        try:
            pk=int(item["game_pk"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BullpenHistoryUniverseError("skip game_pk invalid") from exc
        reason=item.get("reason")
        if reason == "STANDARD_TARGET_DOMAIN":
            standard_skip.add(pk)
        elif reason == "CANCELLED_UNPLAYED_DOMAIN":
            cancelled.add(pk)
        else:
            raise BullpenHistoryUniverseError(f"unexpected supplement skip reason: {reason!r}")
    if not standard_skip.issubset(target_pks):
        raise BullpenHistoryUniverseError("standard target skip absent from target source records")
    if cancelled.intersection(target_pks | supplement_pks):
        raise BullpenHistoryUniverseError("cancelled event entered played history")

    unique_schedule = target_manifest.get("unique_schedule_game_pks")
    if not isinstance(unique_schedule, int) or isinstance(unique_schedule, bool):
        raise BullpenHistoryUniverseError("unique schedule count invalid")
    partition = target_pks | supplement_pks | cancelled
    if len(partition) != unique_schedule:
        raise BullpenHistoryUniverseError(
            f"schedule partition incomplete: partition={len(partition)} unique_schedule={unique_schedule}"
        )

    return {
        "season": season,
        "unique_schedule_game_pks": unique_schedule,
        "played_event_count": len(target_pks) + len(supplement_pks),
        "target_event_count": len(target_pks),
        "supplement_event_count": len(supplement_pks),
        "cancelled_unplayed_count": len(cancelled),
        "standard_revision_overlap_count": len(standard_skip),
    }


def build_history_universe_manifest(
    season_proofs: Sequence[Mapping[str, Any]], *, source_sha: str
) -> dict[str, Any]:
    if not season_proofs:
        raise BullpenHistoryUniverseError("season proofs empty")
    seasons=sorted(int(item["season"]) for item in season_proofs)
    if seasons != list(range(min(seasons), max(seasons)+1)):
        raise BullpenHistoryUniverseError("season range is not contiguous")
    body={
        "schema_version": "doctore.mlb-bullpen-history-universe.v1",
        "source_sha": source_sha,
        "season_start": seasons[0],
        "season_end": seasons[-1],
        "season_proofs": sorted((dict(item) for item in season_proofs), key=lambda x: x["season"]),
        "played_event_count": sum(int(item["played_event_count"]) for item in season_proofs),
        "cancelled_unplayed_count": sum(int(item["cancelled_unplayed_count"]) for item in season_proofs),
        "completeness_status": "PASS",
    }
    seed=sha256_bytes(canonical_bytes(body))
    manifest={**body, "manifest_id": f"mlb-bullpen-history-universe:{seasons[0]}-{seasons[-1]}:{seed[:16]}"}
    return manifest
