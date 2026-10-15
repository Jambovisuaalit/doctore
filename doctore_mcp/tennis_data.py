"""Explicit-tour tennis source adapter; never produces odds or probabilities.

Provider responses can be cached. Retrieval time is not event freshness.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any, Literal
import multiprocessing
import os
from urllib.parse import urlsplit, urlunsplit

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
    source_message: str | None = None
    note: str = "Source may be cached; request time is not event freshness. No odds or model probability."


def _https_espn_reference(url):
    """ESPN publishes HTTP athlete refs; fetch the same resource over HTTPS."""
    parts = urlsplit(url)
    if (parts.scheme == "http" and parts.hostname == "sports.core.api.espn.com"
            and parts.username is None and parts.password is None and parts.port in (None, 80)):
        return urlunsplit(("https", parts.hostname, parts.path, parts.query, parts.fragment))
    return url


def _source_worker(connection, command, kwargs):
    try:
        from sports_skills import tennis, _espn_base
        from sports_skills.tennis import _connector
        original_fetch = _espn_base._http_fetch
        def secure_fetch(url, *args, **kwargs):
            kwargs["timeout"] = min(kwargs.get("timeout", 10), 10)
            kwargs["max_retries"] = 0
            return original_fetch(_https_espn_reference(url), *args, **kwargs)
        # Scoped to this disposable provider process, never global application state.
        _espn_base._http_fetch = secure_fetch
        _connector._http_fetch = secure_fetch
        connection.send(getattr(tennis, command)(**kwargs))
    except Exception:
        connection.send({"status": False, "data": None})
    finally:
        connection.close()


def _bounded_source_call(command, kwargs, timeout_seconds=45):
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_source_worker, args=(writer, command, kwargs), daemon=True)
    process.start()
    writer.close()
    try:
        if not reader.poll(timeout_seconds):
            raise TimeoutError("tennis provider exceeded request deadline")
        return reader.recv()
    finally:
        reader.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        process.close()


def fetch_tennis_data(params: TennisDataInput, *, provider=None, clock=None) -> TennisDataOutput:
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    base = dict(command=params.command, tour=params.tour, requested_at=now.isoformat())
    if provider is None:
        if os.environ.get("DOCTORE_TENNIS_OFFLINE") == "1":
            return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_NETWORK_DISABLED"], **base)
        try:
            if version("sports-skills") != PROVIDER_VERSION:
                return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_PROVIDER_VERSION_MISMATCH"], **base)
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
        response = (_bounded_source_call(params.command, kwargs) if provider is None
                    else getattr(provider, params.command)(**kwargs))
    except TimeoutError:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_TIMEOUT"], **base)
    except Exception:
        # Do not expose transport errors with possible URLs or credentials.
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_ERROR"], **base)
    if isinstance(response, dict) and response.get("status") is False:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_UNAVAILABLE"],
                                source_message=str(response.get("message", "Source unavailable"))[:200], **base)
    if not isinstance(response, dict) or response.get("status") is not True or not isinstance(response.get("data"), dict):
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_INVALID_SOURCE_RESPONSE"], **base)
    data = response["data"]
    key = {"get_scoreboard": "tournaments", "get_calendar": "tournaments", "get_rankings": "rankings"}.get(params.command)
    if key is not None and (not isinstance(data.get(key), list) or any(not isinstance(row, dict) for row in data[key])):
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_SOURCE_SCHEMA_CHANGED"], **base)
    if params.command == "get_rankings" and any(not str(row.get("id", "")).strip() or not str(row.get("name", "")).strip() for row in data["rankings"]):
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_RANKING_IDENTITY_INCOMPLETE"], **base)
    if params.command == "get_player_info" and str(data.get("id")) != params.player_id:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_PLAYER_ID_MISMATCH"], **base)
    if data.get("tour") and str(data["tour"]).lower() != params.tour:
        return TennisDataOutput(status="BLOCKED", reason_codes=["TENNIS_TOUR_MISMATCH"], **base)
    return TennisDataOutput(status="OK", reason_codes=[], data=data, **base)
