"""Bullpen-history supplements for played MLB games outside target domain."""
from __future__ import annotations

from typing import Any, Mapping

from mlb_v2_source_acquisition import (
    SourceAcquisitionError, canonical_bytes, normalize_game_source, sha256_bytes,
)

PLAYED_DOMAIN_REASONS = frozenset({
    "NON_NINE_INNING_DOMAIN", "COMPLETED_EARLY_DOMAIN", "TIED_FINAL_DOMAIN",
})
CANCELLED_STATUS_CODES = frozenset({"CR", "CA", "CO", "CI", "C9"})
COMPLETED_EARLY_STATUS_CODES = frozenset({"FR", "FO"})


class BullpenHistorySupplementError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def authoritative_played_domain_game(
    live_payload: Mapping[str, Any], *, expected_game_pk: int, expected_season: int
) -> tuple[dict[str, Any] | None, str]:
    """Classify authoritative live evidence for bullpen-only history."""
    game_data = live_payload.get("gameData") or {}
    live_data = live_payload.get("liveData") or {}
    game = game_data.get("game") or {}
    status = game_data.get("status") or {}
    datetime_data = game_data.get("datetime") or {}
    venue = game_data.get("venue") or {}
    teams = game_data.get("teams") or {}
    linescore = live_data.get("linescore") or {}
    line_teams = linescore.get("teams") or {}

    game_pk = _optional_int(live_payload.get("gamePk") or game.get("pk"))
    if game_pk != int(expected_game_pk):
        raise BullpenHistorySupplementError("LIVE_GAME_PK_MISMATCH", f"{game_pk!r} != {expected_game_pk}")
    if str(game.get("type") or "") != "R":
        raise BullpenHistorySupplementError("LIVE_NOT_REGULAR_SEASON", f"gamePk={game_pk}")

    official_date = str(datetime_data.get("officialDate") or "")
    if not official_date.startswith(str(expected_season)):
        raise BullpenHistorySupplementError(
            "LIVE_OFFICIAL_DATE_OUTSIDE_SEASON",
            f"gamePk={game_pk} official_date={official_date!r}",
        )

    code = str(status.get("statusCode") or status.get("codedGameState") or "").upper()
    detailed = str(status.get("detailedState") or "").strip()
    detailed_cf = detailed.casefold()
    scheduled_innings = _optional_int(linescore.get("scheduledInnings") or game.get("scheduledInnings"))

    if code in CANCELLED_STATUS_CODES and detailed_cf.startswith("cancelled"):
        return None, "CANCELLED_UNPLAYED_DOMAIN"
    if code == "FT" and detailed_cf.startswith("final: tied"):
        reason = "TIED_FINAL_DOMAIN"
    elif code in COMPLETED_EARLY_STATUS_CODES and detailed_cf.startswith("completed early"):
        reason = "COMPLETED_EARLY_DOMAIN"
    elif code == "F" and scheduled_innings is not None and scheduled_innings != 9:
        reason = "NON_NINE_INNING_DOMAIN"
    elif code == "F" and scheduled_innings == 9:
        return None, "STANDARD_TARGET_DOMAIN"
    else:
        raise BullpenHistorySupplementError(
            "TERMINAL_DOMAIN_UNVERIFIED",
            f"gamePk={game_pk} status={code!r} detailed={detailed!r} innings={scheduled_innings!r}",
        )

    values = {
        "game_pk": game_pk,
        "official_date": official_date,
        "event_start_at": str(datetime_data.get("dateTime") or "") or None,
        "scheduled_innings": scheduled_innings,
        "venue_id": _optional_int(venue.get("id")),
        "venue_name": str(venue.get("name") or "") or None,
        "away_team_id": _optional_int(_nested(teams, "away", "id")),
        "home_team_id": _optional_int(_nested(teams, "home", "id")),
        "away_score": _optional_int(_nested(line_teams, "away", "runs")),
        "home_score": _optional_int(_nested(line_teams, "home", "runs")),
    }
    required = ("official_date", "event_start_at", "scheduled_innings", "venue_id",
                "away_team_id", "home_team_id", "away_score", "home_score")
    missing = [field for field in required if values.get(field) in (None, "")]
    if missing:
        raise BullpenHistorySupplementError("LIVE_PLAYED_FIELDS_MISSING", f"gamePk={game_pk} missing={missing}")
    values["needs_hydration"] = False
    values["hydrated_from_live"] = True
    values["domain_exclusion_reason"] = reason
    return values, reason


def normalize_bullpen_history_source(
    schedule_game: Mapping[str, Any], *, domain_exclusion_reason: str,
    timestamps_bytes: bytes, boxscore_bytes: bytes, live_payload_bytes: bytes,
) -> dict[str, Any]:
    """Build one content-addressed bullpen-only record from complete evidence."""
    if domain_exclusion_reason not in PLAYED_DOMAIN_REASONS:
        raise BullpenHistorySupplementError("DOMAIN_REASON_NOT_PLAYED", repr(domain_exclusion_reason))
    try:
        record = normalize_game_source(
            schedule_game, timestamps_bytes=timestamps_bytes, boxscore_bytes=boxscore_bytes,
            hydration_sha256=sha256_bytes(live_payload_bytes),
        )
    except SourceAcquisitionError as exc:
        raise BullpenHistorySupplementError("SOURCE_NORMALIZATION_FAILED", str(exc)) from exc
    if record.get("bullpen_status") != "PASS":
        raise BullpenHistorySupplementError(
            "BULLPEN_SOURCE_BLOCKED",
            f"gamePk={schedule_game.get('game_pk')} reason={record.get('bullpen_reason')!r}",
        )

    payload = {key: value for key, value in record.items() if key not in {"source_record_id", "source_sha256"}}
    payload.update({
        "source_role": "BULLPEN_HISTORY_SUPPLEMENT",
        "target_domain_eligible": False,
        "park_status": "BLOCKED_DOMAIN",
        "park_reason": domain_exclusion_reason,
        "bullpen_history_eligible": True,
        "domain_exclusion_reason": domain_exclusion_reason,
    })
    digest = sha256_bytes(canonical_bytes(payload))
    return {
        **payload,
        "source_record_id": f"mlb-bullpen-history:{int(schedule_game['game_pk'])}:{digest[:16]}",
        "source_sha256": digest,
    }
