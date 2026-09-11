"""Point-in-time MLB bullpen feature materialization for feature-schema v2.

The materializer intentionally supports only the bullpen group. Park aggregates
require a scalable aggregate-lineage contract before they can be promoted from
READY_TO_ACQUIRE.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class BullpenMaterializationError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BullpenMaterializationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BullpenMaterializationError(f"{field} must be timezone-aware")
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _canonical_sha(value: Any) -> str:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    return sha256(raw).hexdigest()


def derive_slate_cutoffs(
    target_events: Sequence[Mapping[str, Any]],
    *,
    slate_field: str = "official_date",
) -> dict[str, str]:
    """Use the earliest scheduled start in each slate as the exact common cutoff."""
    grouped: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    for event in target_events:
        event_id = str(event.get("event_id", "")).strip()
        slate = str(event.get(slate_field, "")).strip()
        if not event_id:
            raise BullpenMaterializationError("target event_id missing")
        if not slate:
            raise BullpenMaterializationError(f"target {event_id} missing {slate_field}")
        grouped[slate].append((event_id, _ts(event.get("event_start_at"), f"event_start_at[{event_id}]")))

    cutoffs: dict[str, str] = {}
    for events in grouped.values():
        cutoff = min(start for _, start in events)
        cutoff_iso = _iso(cutoff)
        for event_id, _ in events:
            cutoffs[event_id] = cutoff_iso
    return cutoffs


def _record_has_team(record: Mapping[str, Any], team_id: int) -> bool:
    return int(record.get("away_team_id", -1)) == team_id or int(record.get("home_team_id", -1)) == team_id


def _team_pitching(record: Mapping[str, Any], team_id: int) -> Mapping[str, Any]:
    if int(record.get("away_team_id", -1)) == team_id:
        value = record.get("away_pitching")
    elif int(record.get("home_team_id", -1)) == team_id:
        value = record.get("home_pitching")
    else:
        raise BullpenMaterializationError(f"team {team_id} not present in source event {record.get('event_id')}")
    if not isinstance(value, Mapping):
        raise BullpenMaterializationError(f"pitching payload missing for team {team_id} in {record.get('event_id')}")
    return value


def _eligible_reject_precedes_cutoff(
    reject: Mapping[str, Any],
    *,
    team_id: int,
    cutoff: datetime,
) -> bool:
    if "reason" not in reject:
        return False
    try:
        away = int(reject.get("away_team_id", -1))
        home = int(reject.get("home_team_id", -1))
    except (TypeError, ValueError):
        return False
    if team_id not in {away, home}:
        return False
    try:
        start = _ts(reject.get("event_start_at"), "reject.event_start_at")
    except BullpenMaterializationError:
        return True
    return start < cutoff


def _back_to_back_count(records: Sequence[Mapping[str, Any]], team_id: int) -> int:
    relievers_by_date: dict[date, set[int]] = defaultdict(set)
    for record in records:
        try:
            day = date.fromisoformat(str(record["official_date"]))
        except (KeyError, ValueError) as exc:
            raise BullpenMaterializationError(f"invalid official_date in {record.get('event_id')}") from exc
        pitching = _team_pitching(record, team_id)
        for pitcher_id in pitching.get("reliever_ids", []):
            relievers_by_date[day].add(int(pitcher_id))

    days = sorted(relievers_by_date)
    if len(days) < 2:
        return 0
    previous, latest = days[-2], days[-1]
    if (latest - previous).days != 1:
        return 0
    return len(relievers_by_date[previous].intersection(relievers_by_date[latest]))


def _team_features(records_3d: Sequence[Mapping[str, Any]], team_id: int, cutoff: datetime) -> dict[str, int]:
    window_1d = cutoff - timedelta(hours=24)
    records_1d = [record for record in records_3d if _ts(record["final_event_at"], "final_event_at") >= window_1d]

    def total(field: str, rows: Sequence[Mapping[str, Any]]) -> int:
        return sum(int(_team_pitching(record, team_id).get(field, 0)) for record in rows)

    return {
        "pitches_1d": total("bullpen_pitches", records_1d),
        "pitches_3d": total("bullpen_pitches", records_3d),
        "appearances_1d": total("bullpen_appearances", records_1d),
        "appearances_3d": total("bullpen_appearances", records_3d),
        "back_to_back_count": _back_to_back_count(records_3d, team_id),
    }


def materialize_bullpen_group(
    target_event: Mapping[str, Any],
    *,
    feature_cutoff_at: str,
    source_records: Sequence[Mapping[str, Any]],
    eligible_rejects: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Materialize one target event or fail closed with explicit reason codes."""
    event_id = str(target_event.get("event_id", "")).strip()
    if not event_id:
        raise BullpenMaterializationError("target event_id missing")
    cutoff = _ts(feature_cutoff_at, "feature_cutoff_at")
    try:
        away_team_id = int(target_event["away_team_id"])
        home_team_id = int(target_event["home_team_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BullpenMaterializationError("target team ids missing") from exc
    if away_team_id == home_team_id:
        raise BullpenMaterializationError("target team ids must differ")

    reason_codes: set[str] = set()
    for team_id, side in ((away_team_id, "AWAY"), (home_team_id, "HOME")):
        if any(_eligible_reject_precedes_cutoff(reject, team_id=team_id, cutoff=cutoff) for reject in eligible_rejects):
            reason_codes.add(f"{side}_BULLPEN_HISTORY_HAS_ELIGIBLE_REJECT")

    lower = cutoff - timedelta(hours=72)
    records_3d: dict[int, list[Mapping[str, Any]]] = {away_team_id: [], home_team_id: []}
    contributing: dict[str, Mapping[str, Any]] = {}

    for record in source_records:
        relevant_sides = [
            (team_id, side)
            for team_id, side in ((away_team_id, "AWAY"), (home_team_id, "HOME"))
            if _record_has_team(record, team_id)
        ]
        if not relevant_sides:
            continue

        source_event_id = str(record.get("event_id", "")).strip()
        try:
            final_at = _ts(record.get("final_event_at"), f"final_event_at[{source_event_id}]")
        except BullpenMaterializationError:
            for _, side in relevant_sides:
                reason_codes.add(f"{side}_BULLPEN_SOURCE_FINAL_AT_INVALID")
            continue
        if not (lower <= final_at < cutoff):
            continue
        if source_event_id == event_id:
            reason_codes.add("CURRENT_EVENT_RESULT_LEAKAGE")
            continue

        for team_id, side in relevant_sides:
            if record.get("bullpen_status") != "PASS":
                reason_codes.add(f"{side}_BULLPEN_SOURCE_BLOCKED_IN_3D")
                continue
            if not SHA256_RE.fullmatch(str(record.get("source_sha256", ""))):
                reason_codes.add(f"{side}_BULLPEN_SOURCE_SHA_INVALID")
                continue
            records_3d[team_id].append(record)
            contributing[source_event_id] = record

    if not records_3d[away_team_id]:
        reason_codes.add("AWAY_BULLPEN_NO_PROVEN_PRIOR_GAME_3D")
    if not records_3d[home_team_id]:
        reason_codes.add("HOME_BULLPEN_NO_PROVEN_PRIOR_GAME_3D")

    if reason_codes:
        return {
            "event_id": event_id,
            "feature_group": "bullpen",
            "status": "BLOCKED_PROVENANCE",
            "feature_cutoff_at": _iso(cutoff),
            "reason_codes": sorted(reason_codes),
            "features": {},
            "provenance": None,
        }

    away = _team_features(records_3d[away_team_id], away_team_id, cutoff)
    home = _team_features(records_3d[home_team_id], home_team_id, cutoff)
    features = {
        "away_bullpen_pitches_1d": away["pitches_1d"],
        "home_bullpen_pitches_1d": home["pitches_1d"],
        "away_bullpen_pitches_3d": away["pitches_3d"],
        "home_bullpen_pitches_3d": home["pitches_3d"],
        "away_bullpen_appearances_1d": away["appearances_1d"],
        "home_bullpen_appearances_1d": home["appearances_1d"],
        "away_bullpen_appearances_3d": away["appearances_3d"],
        "home_bullpen_appearances_3d": home["appearances_3d"],
        "away_bullpen_back_to_back_count": away["back_to_back_count"],
        "home_bullpen_back_to_back_count": home["back_to_back_count"],
    }

    ordered_sources = sorted(
        contributing.values(),
        key=lambda record: (_ts(record["final_event_at"], "final_event_at"), str(record["event_id"])),
    )
    evidence = {
        "event_id": event_id,
        "feature_group": "bullpen",
        "feature_cutoff_at": _iso(cutoff),
        "source_records": [
            {
                "event_id": str(record["event_id"]),
                "end_at": str(record["final_event_at"]),
                "source_sha256": str(record["source_sha256"]),
            }
            for record in ordered_sources
        ],
    }
    evidence_sha = _canonical_sha(evidence)
    provenance = {
        "schema_version": "doctore.feature-provenance.v1",
        "event_id": event_id,
        "feature_group": "bullpen",
        "source": "MLB StatsAPI normalized feature sources v1",
        "source_record_id": f"mlb-bullpen-features:{event_id}:{evidence_sha[:16]}",
        "availability_mode": "PRIOR_EVENT_FINAL",
        "feature_cutoff_at": _iso(cutoff),
        "source_sha256": evidence_sha,
        "source_events": [
            {"event_id": item["event_id"], "end_at": item["end_at"]}
            for item in evidence["source_records"]
        ],
    }
    return {
        "event_id": event_id,
        "feature_group": "bullpen",
        "status": "PASS",
        "feature_cutoff_at": _iso(cutoff),
        "reason_codes": [],
        "features": features,
        "provenance": provenance,
    }
