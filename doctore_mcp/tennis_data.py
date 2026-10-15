"""Explicit-tour tennis source adapter; never produces odds or probabilities.

Provider responses can be cached. Retrieval time is not event freshness.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROVIDER_VERSION = "0.37.1"
REVIEWED_COMMIT = "39092bbb6f146cc9d5631dabcf53f57f601fde6c"


class TennisDataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["get_scoreboard", "get_rankings", "get_calendar", "get_player_info"]
    tour: Literal["atp", "wta"]
    year: int | None = Field(default=None, ge=1900, le=2200)
    limit: int | None = Field(default=None, ge=1, le=100)
    player_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")

    @model_validator(mode="after")
    def check_parameters(self):
        if (self.command == "get_player_info") != (self.player_id is not None):
            raise ValueError("player_id is required only for get_player_info")
        if self.year is not None and self.command != "get_calendar":
            raise ValueError("year is only supported by get_calendar")
        if self.limit is not None and self.command != "get_rankings":
            raise ValueError("limit is only supported by get_rankings")
        return self


class TennisDataOutput(BaseModel):
    status: Literal["OK", "BLOCKED"]
    reason_codes: list[str]
    source: str = "sports-skills/ESPN"
    provider_version: str = PROVIDER_VERSION
    command: str
    tour: str
    requested_at: str
    source_updated_at: None = None
    event_freshness_verified: bool = False
    data: dict[str, Any] | None = None
    note: str = "Source may be cached; request time is not event freshness. No odds or model probability."


def fetch_tennis_data(params: TennisDataInput, *, provider=None, clock=None) -> TennisDataOutput:
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    base = dict(command=params.command, tour=params.tour, requested_at=now.isoformat())
    if provider is None:
        try:
            if version("sports-skills") != PROVIDER_VERSION:
                return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_PROVIDER_VERSION_MISMATCH"], **base)
            from sports_skills import tennis as provider
        except (ImportError, ModuleNotFoundError):
            return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_PROVIDER_NOT_INSTALLED"], **base)
    kwargs: dict[str, Any] = {}
    # The reviewed player endpoint has no tour argument. Keep the requested tour
    # as scope only; do not claim that the profile verified tour membership.
    if params.command == "get_player_info":
        kwargs["player_id"] = params.player_id
    else:
        kwargs["tour"] = params.tour
    if params.command == "get_calendar":
        kwargs["year"] = params.year if params.year is not None else now.year
    if params.command == "get_rankings" and params.limit is not None:
        kwargs["limit"] = params.limit
    try:
        response = getattr(provider, params.command)(**kwargs)
    except Exception:
        # Do not expose transport errors with possible URLs or credentials.
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_ERROR"], **base)
    if not isinstance(response, dict) or response.get("status") is not True or not isinstance(response.get("data"), dict):
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_INVALID_SOURCE_RESPONSE"], **base)
    data = response["data"]
    key = {"get_scoreboard": "tournaments", "get_calendar": "tournaments", "get_rankings": "rankings"}.get(params.command)
    if key is not None and (not isinstance(data.get(key), list) or any(not isinstance(row, dict) for row in data[key])):
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_SCHEMA_CHANGED"], **base)
    if params.command == "get_player_info" and str(data.get("id")) != params.player_id:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_PLAYER_ID_MISMATCH"], **base)
    if data.get("tour") and str(data["tour"]).lower() != params.tour:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_TOUR_MISMATCH"], **base)
    return TennisDataOutput(status="OK", reason_codes=[], data=data, **base)
