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
    command: Literal["get_scoreboard", "get_rankings", "get_calendar", "get_player_info", "get_capabilities", "analyze_supplied_market", "import_odds", "compare_odds"]
    tour: Literal["atp", "wta"]
    year: int | None = Field(default=None, ge=1900, le=2200)
    limit: int | None = Field(default=None, ge=1, le=100)
    player_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    market_snapshot: dict[str, Any] | None = None
    odds_import: dict[str, Any] | None = None
    comparison_snapshots: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def check_parameters(self):
        if (self.command == "import_odds") != (self.odds_import is not None):
            raise ValueError("odds_import is required only for import_odds")
        if (self.command == "compare_odds") != (self.comparison_snapshots is not None):
            raise ValueError("comparison_snapshots is required only for compare_odds")
        if (self.command == "analyze_supplied_market") != (self.market_snapshot is not None):
            raise ValueError("market_snapshot is required only for analyze_supplied_market")
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
    research_only: bool = True
    recommendation_available: bool = False
    live_decisions_enabled: bool = False
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


def tennis_mode():
    """Keyless research is the explicit default; unknown modes fail closed."""
    mode = os.environ.get("DOCTORE_TENNIS_MODE", "research")
    return mode if mode in ("research", "verified_prematch") else "disabled"


def capabilities():
    return {
        "mode": tennis_mode(), "default_source": "sports-skills/ESPN",
        "api_key_required": False, "background_data_commands": ["get_scoreboard", "get_rankings", "get_calendar", "get_player_info"],
        "local_commands": ["get_capabilities", "analyze_supplied_market", "import_odds", "compare_odds"],
        "odds_source": "user_supplied_timestamped_snapshot", "automatic_betting": False,
        "live_decisions_enabled": False, "research_recommendations_enabled": False,
        "verified_prematch_opt_in": tennis_mode() == "verified_prematch",
        "optional_provider": "sportradar", "optional_provider_required_for_research": False,
        "background_dependency_required": "requirements-tennis.txt",
        "note": "A current source read is not proof of match freshness or executable odds. Price-vector math does not model retirement/void settlement."
    }


def analyze_supplied_market(snapshot, now):
    from .schemas import schema_errors
    from .runtime import parse_time, content_sha256
    from src.market_probability import calculate_market_probabilities
    errors = schema_errors("market", snapshot)
    if errors or snapshot.get("sport") != "TENNIS":
        return None, ["TENNIS_SUPPLIED_MARKET_INVALID"]
    age = (now - parse_time(snapshot["captured_at"])).total_seconds()
    if age < 0 or age > 300:
        return None, ["TENNIS_SUPPLIED_PRICE_STALE"]
    if not snapshot["is_complete"] or snapshot["market_status"] != "open":
        return None, ["TENNIS_SUPPLIED_MARKET_INCOMPLETE"]
    try:
        # Deliberately use the public generic price-vector API. This is arithmetic
        # research only; canonical tennis retirement/void economics stays blocked.
        import math
        outcomes = snapshot["outcomes"]
        if len(outcomes) != 2 or len({row["selection"] for row in outcomes}) != 2 or any(not math.isfinite(row["decimal_odds"]) for row in outcomes):
            raise ValueError("two unique finite outcome prices required")
        vector = {key: snapshot[key] for key in ("selection", "decimal_odds", "outcomes")}
        baseline = calculate_market_probabilities(vector)
    except (ValueError, TypeError, KeyError):
        return None, ["TENNIS_SUPPLIED_MARKET_INVALID"]
    return {"scope": "price_vector_only", "source": "user_supplied", "book": snapshot["book"],
            "captured_at": snapshot["captured_at"], "age_seconds": age,
            "event_id": snapshot["event_id"], "market_id": snapshot["market_id"],
            "market_snapshot_sha256": content_sha256(snapshot),
            "market_baseline": baseline, "event_freshness_verified": False,
            "executable_price_verified": False, "model_probability": None, "stake": None,
            "recommendation": None, "settlement_payoff_verified": False}, []


def fetch_tennis_data(params: TennisDataInput, *, provider=None, clock=None) -> TennisDataOutput:
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    base = dict(command=params.command, tour=params.tour, requested_at=now.isoformat())
    if params.command in ("import_odds", "compare_odds"):
        from .tennis_odds import import_quotes, compare_quotes, OddsError
        try:
            data = (import_quotes(params.odds_import, params.tour, now) if params.command == "import_odds"
                    else compare_quotes(params.comparison_snapshots, now))
            reasons = (["TENNIS_ODDS_PARTIAL_IMPORT"] if data.get("rejected") else [])
            if params.command == "import_odds" and not data["snapshots"]:
                reasons = ["TENNIS_ODDS_NO_VALID_QUOTES"]
            return TennisDataOutput(status="BLOCKED" if reasons == ["TENNIS_ODDS_NO_VALID_QUOTES"] else "OK",
                reason_codes=reasons, data=data, source="supplied_odds_research", provider_version="not_used", **base)
        except OddsError as exc:
            return TennisDataOutput(status="BLOCKED", reason_codes=[str(exc)],
                source="supplied_odds_research", provider_version="not_used", **base)
    if params.command == "get_capabilities":
        return TennisDataOutput(status="OK", reason_codes=[], data=capabilities(), source="local_configuration",
                                provider_version="not_used", note="Local capabilities; no provider call or API key required.", **base)
    if params.command == "analyze_supplied_market":
        data, reasons = analyze_supplied_market(params.market_snapshot, now)
        return TennisDataOutput(status="BLOCKED" if reasons else "OK", reason_codes=reasons, data=data,
                                source="user_supplied", provider_version="not_used",
                                note="Timestamped supplied prices support arithmetic research only; source, execution and retirement/void payoffs are unverified.", **base)
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
