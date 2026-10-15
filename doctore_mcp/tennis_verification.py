"""Explicit Sportradar acquisition and server-owned tennis evidence.

No network during evaluation; no request time is substituted for provider time.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import sqlite3
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .runtime import BET_LOG_PATH, REPO, content_sha256, parse_time


class VerificationError(ValueError):
    pass


def database_path():
    return Path(os.environ.get("DOCTORE_TENNIS_EVIDENCE_DB", str(BET_LOG_PATH) + ".tennis-evidence.sqlite3")).expanduser().resolve()


def load_registry():
    path = Path(os.environ.get("DOCTORE_TENNIS_IDENTITY_REGISTRY", str(REPO / "governance/tennis-identity-registry.json")))
    try:
        registry = json.loads(path.read_text())
        if registry.get("schema_version") != "doctore.tennis-identity-registry.v1" or not isinstance(registry.get("mappings"), list):
            raise ValueError()
        return registry
    except (OSError, ValueError, AttributeError):
        return {"schema_version": "doctore.tennis-identity-registry.v1", "mappings": []}


def approved_mapping(registry, book, book_market_id, now):
    try:
        mappings = [m for m in registry["mappings"] if m.get("book") == book and m.get("book_market_id") == book_market_id]
        if len(mappings) != 1:
            raise ValueError()
        mapping = mappings[0]
        required = ("canonical_event_id", "source_event_id", "book_event_id", "tour", "format", "tournament_id", "round", "event_start_at")
        if (mapping.get("status") != "APPROVED" or not str(mapping.get("reviewer", "")).strip()
                or mapping.get("source") != "sportradar" or any(not mapping.get(k) for k in required)
                or mapping["format"] != "singles" or mapping["tour"] not in ("atp", "wta")
                or parse_time(mapping["valid_until"]) < now):
            raise ValueError()
        for key in ("source_player_ids", "book_player_ids"):
            values = mapping[key]
            if not isinstance(values, list) or len(values) != 2 or len(set(values)) != 2 or not all(isinstance(v, str) and v.strip() for v in values):
                raise ValueError()
        if not re.fullmatch(r"sr:sport_event:[1-9][0-9]*", mapping["source_event_id"]):
            raise ValueError()
        return mapping
    except (KeyError, ValueError, TypeError, AttributeError):
        raise VerificationError("TENNIS_APPROVED_MAPPING_REQUIRED") from None


def normalize_summary(payload, mapping, received_at, evaluated_at):
    try:
        event = payload["sport_event"]
        context = event["sport_event_context"]
        competition = context["competition"]
        status = payload["sport_event_status"]
        generated = parse_time(payload["generated_at"])
        received, now = parse_time(received_at), parse_time(evaluated_at)
        # Provider-generated snapshot time, NOT event last-change or HTTP receipt.
        if not generated <= received <= now or (now-generated).total_seconds() > 120:
            raise VerificationError("TENNIS_PROVIDER_SNAPSHOT_STALE")
        if (event["id"] != mapping["source_event_id"] or competition["id"] != mapping["tournament_id"]
                or competition["type"] != "singles" or context["category"]["name"].lower() != mapping["tour"]
                or context["round"]["name"] != mapping["round"]
                or parse_time(event["start_time"]) != parse_time(mapping["event_start_at"])):
            raise VerificationError("TENNIS_PROVIDER_IDENTITY_MISMATCH")
        if (event.get("start_time_confirmed") is not True or event.get("estimated") is True
                or event.get("replaced_by") or event.get("resume_time") or event.get("replaced")
                or context.get("season", {}).get("disabled") is True
                or status["status"] != "not_started" or status.get("match_status") != "not_started"
                or now >= parse_time(event["start_time"])):
            raise VerificationError("TENNIS_PROVIDER_NOT_CONFIRMED_PREMATCH")
        competitors = event["competitors"]
        if len(competitors) != 2 or {c.get("qualifier") for c in competitors} != {"home", "away"}:
            raise VerificationError("TENNIS_PROVIDER_PLAYERS_AMBIGUOUS")
        ordered = sorted(competitors, key=lambda c: 0 if c["qualifier"] == "home" else 1)
        if any(c.get("virtual") is True or c.get("players") for c in ordered):
            raise VerificationError("TENNIS_PROVIDER_PLAYERS_AMBIGUOUS")
        ids = [c["id"] for c in ordered]
        if ids != mapping["source_player_ids"]:
            raise VerificationError("TENNIS_PROVIDER_PLAYER_MISMATCH")
        result = {k: mapping[k] for k in ("source", "source_event_id", "book_event_id", "tour", "format", "tournament_id", "round", "event_start_at", "source_player_ids", "book_player_ids")}
        result.update(status="scheduled", source_updated_at=None,
            freshness_basis="provider_generated_at", provider_generated_at=payload["generated_at"],
            received_at=received_at, source_snapshot_sha256=content_sha256(payload))
        return result
    except VerificationError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VerificationError("TENNIS_PROVIDER_SCHEMA_INVALID") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise VerificationError("TENNIS_PROVIDER_REDIRECT_REJECTED")


def fetch_summary(source_event_id, api_key, access_level):
    if not re.fullmatch(r"sr:sport_event:[1-9][0-9]*", source_event_id) or access_level not in ("trial", "production"):
        raise VerificationError("TENNIS_PROVIDER_CONFIG_INVALID")
    url = f"https://api.sportradar.com/tennis/{access_level}/v3/en/sport_events/{source_event_id}/summary.json"
    request = Request(url, headers={"x-api-key": api_key, "Accept": "application/json"})
    try:
        # Fixed HTTPS host, no credential-bearing URL, no redirect and no retries.
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise VerificationError("TENNIS_PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except VerificationError:
        raise
    except Exception:
        # Never expose provider error bodies, request headers or credentials.
        raise VerificationError("TENNIS_PROVIDER_REQUEST_FAILED") from None


def acquire(book, book_market_id, *, allow_live_fetch=False, clock=None):
    if not allow_live_fetch:
        raise VerificationError("TENNIS_EXPLICIT_FETCH_REQUIRED")
    if not os.environ.get("SPORTRADAR_API_KEY", "").strip() or os.environ.get("SPORTRADAR_ACCESS_LEVEL") not in ("trial", "production"):
        raise VerificationError("TENNIS_PROVIDER_CREDENTIALS_REQUIRED")
    try:
        import fcntl
    except ImportError:
        raise VerificationError("TENNIS_ACQUISITION_LOCK_UNAVAILABLE") from None
    lock_path = database_path().with_suffix(".acquisition.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize source observations: an older concurrent request must not overwrite
    # a withdrawal/failure observed by a newer request.
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return _acquire(book, book_market_id, allow_live_fetch=allow_live_fetch, clock=clock)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _acquire(book, book_market_id, *, allow_live_fetch=False, clock=None):
    if not allow_live_fetch:
        raise VerificationError("TENNIS_EXPLICIT_FETCH_REQUIRED")
    key = os.environ.get("SPORTRADAR_API_KEY", "").strip()
    level = os.environ.get("SPORTRADAR_ACCESS_LEVEL", "").strip()
    if not key or level not in ("trial", "production"):
        raise VerificationError("TENNIS_PROVIDER_CREDENTIALS_REQUIRED")
    clock = clock or (lambda: datetime.now(timezone.utc))
    mapping = approved_mapping(load_registry(), book, book_market_id, clock())
    # Invalidate older evidence durably BEFORE requesting a new observation.
    # If persistence fails after the network read, the in-progress marker remains
    # fail-closed rather than letting an older success reappear.
    store_observation(book, book_market_id, mapping,
                      {"blocked_reason": "TENNIS_ACQUISITION_IN_PROGRESS"}, clock().isoformat())
    try:
        payload = fetch_summary(mapping["source_event_id"], key, level)
    except VerificationError as exc:
        # New failure invalidates older cached success immediately.
        store_observation(book, book_market_id, mapping, {"blocked_reason": str(exc)}, clock().isoformat())
        raise
    received = clock().isoformat()
    # Persist negative/malformed/withdrawn snapshots too; never resurrect an older
    # scheduled observation after the provider has reported a changed state.
    store_observation(book, book_market_id, mapping, payload, received)
    return normalize_summary(payload, mapping, received, received)


def store_observation(book, book_market_id, mapping, payload, received):
    db_path = database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS observations (seq INTEGER PRIMARY KEY, book TEXT, market_id TEXT, mapping_hash TEXT, payload TEXT, payload_hash TEXT, received_at TEXT)")
        db.execute("INSERT INTO observations(book,market_id,mapping_hash,payload,payload_hash,received_at) VALUES (?,?,?,?,?,?)",
            (book, book_market_id, content_sha256(mapping), json.dumps(payload, sort_keys=True), content_sha256(payload), received))


def verified_context(market, evaluated_at):
    """Ignore caller evidence. Revalidate stored provider bytes against current mapping."""
    registry = load_registry()
    context = {"identity_registry": registry}
    try:
        mapping = approved_mapping(registry, market["book"], market["book_market_id"], parse_time(evaluated_at))
        target = database_path()
        if not target.exists():
            return context
        # URI read-only prevents evaluation from creating an empty database.
        with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT payload,payload_hash,received_at FROM observations WHERE book=? AND market_id=? AND mapping_hash=? ORDER BY seq DESC LIMIT 1",
                (market["book"], market["book_market_id"], content_sha256(mapping))).fetchone()
        if row is None:
            return context
        payload = json.loads(row[0])
        if content_sha256(payload) != row[1]:
            return context
        context["tennis_event"] = normalize_summary(payload, mapping, row[2], evaluated_at)
    except (VerificationError, OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        pass
    return context
