"""Source-acquired NHL totals evidence and fail-closed, SHADOW-only quote scanner.

The Odds API supplies aggregated bookmaker observations (not executable odds).
The NHL public schedule supplies official event identity. Settlement metadata must
come from a separately reviewed *local* registry; it is never inferred from odds.
No model, decision, bankroll, or bet-placement interface is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field

ODDS_ENDPOINT = "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
NHL_SCHEDULE_PREFIX = "https://api-web.nhle.com/v1/schedule/"
MAX_RAW_BYTES = 3_000_000
REVIEWED_SCOPES = {"REGULATION_60", "REGULATION_OT", "REGULATION_OT_SO"}
TARGET_PAIRS = (
    "Anaheim Ducks|Ottawa Senators",
    "Edmonton Oilers|New York Rangers",
)


class CollectNhlTotalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regions: Literal["eu", "us", "uk", "eu,us", "us,eu", "eu,uk", "us,uk", "eu,us,uk"] = "eu,us"
    target_event_pairs: list[str] = Field(default_factory=lambda: list(TARGET_PAIRS), min_length=1, max_length=8)
    max_age_seconds: int = Field(default=300, ge=30, le=3600)


class CollectNhlTotalsOutput(BaseModel):
    schema_version: Literal["doctore.nhl-source-collection.v1"] = "doctore.nhl-source-collection.v1"
    execution_mode: Literal["SHADOW"] = "SHADOW"
    recommended_stake_eur: Literal[0] = 0
    status: str
    raw_evidence: list[dict[str, Any]] = Field(default_factory=list)
    input_event_count: int = 0
    normalized_quote_count: int = 0
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    scan: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RawDownload:
    raw: bytes
    fetched_at: datetime


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("UPSTREAM_REDIRECT_BLOCKED")


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("SOURCE_TIME_MISSING_OR_DATE_ONLY")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("SOURCE_TIME_INVALID") from exc
    if instant.tzinfo is None:
        raise ValueError("SOURCE_TIME_WITHOUT_TZ")
    return instant.astimezone(timezone.utc)


def _clean(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _team(team: Any) -> str:
    if not isinstance(team, dict):
        return ""

    def default(x):
        return x.get("default", "") if isinstance(x, dict) else x if isinstance(x, str) else ""

    name = default(team.get("name"))
    if name:
        return str(name)
    return " ".join(v for v in [default(team.get("placeName")), default(team.get("commonName"))] if v).strip()


def _target_pairs(values: list[str]) -> set[frozenset[str]]:
    output: set[frozenset[str]] = set()
    for item in values:
        pieces = item.split("|")
        if len(pieces) != 2 or not all(_clean(p) for p in pieces):
            raise ValueError("TARGET_PAIR_INVALID: use 'Home Team|Away Team'")
        output.add(frozenset((_clean(pieces[0]), _clean(pieces[1]))))
    return output


def _decode_json(raw: bytes) -> Any:
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("SOURCE_INVALID_JSON") from exc


def _official_games(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {}
    for payload in payloads:
        batches = [payload.get("games", [])]
        batches.extend(day.get("games", []) for day in payload.get("gameWeek", []) if isinstance(day, dict))
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for game in batch:
                try:
                    game_id, start = game["id"], _utc(game["startTimeUTC"])
                    home, away = _team(game["homeTeam"]), _team(game["awayTeam"])
                    if not isinstance(game_id, int) or isinstance(game_id, bool) or not home or not away:
                        continue
                    seen[game_id] = {"id": game_id, "start": start, "home": _clean(home), "away": _clean(away)}
                except (KeyError, TypeError, ValueError):
                    continue
    return list(seen.values())


def _match_official_event(odds_event: dict[str, Any], official: list[dict[str, Any]]) -> dict[str, Any]:
    start = _utc(odds_event.get("commence_time"))
    h, a = _clean(odds_event.get("home_team", "")), _clean(odds_event.get("away_team", ""))
    candidates = [x for x in official if x["home"] == h and x["away"] == a
                  and abs((x["start"] - start).total_seconds()) <= 1800]
    if len(candidates) != 1:
        raise ValueError("OFFICIAL_EVENT_ID_UNRESOLVED" if not candidates else "OFFICIAL_EVENT_ID_AMBIGUOUS")
    return candidates[0]


def _rule_registry(environment: dict[str, str], now: datetime) -> dict[str, dict[str, Any]]:
    path = environment.get("DOCTORE_NHL_SETTLEMENT_RULES", "").strip()
    if not path:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.stat().st_size > 500_000:
        raise ValueError("RULE_REGISTRY_UNAVAILABLE")
    try:
        registry = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("RULE_REGISTRY_INVALID_JSON") from exc
    if registry.get("schema_version") != "doctore.nhl-book-rules.v1" or not isinstance(registry.get("books"), dict):
        raise ValueError("RULE_REGISTRY_INVALID_SCHEMA")
    valid: dict[str, dict[str, Any]] = {}
    for key, rule in registry["books"].items():
        if not isinstance(rule, dict) or rule.get("reviewed") is not True:
            continue
        if rule.get("market_key") != "totals" or rule.get("period") != "full_game":
            continue
        if rule.get("scope") not in REVIEWED_SCOPES:
            continue
        src = str(rule.get("source_url", ""))
        if urlsplit(src).scheme != "https" or not urlsplit(src).hostname:
            continue
        fraction = rule.get("commission_fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (float, int)) or not (0 <= fraction < 1):
            continue
        try:
            review_at = _utc(rule.get("verified_at"))
        except ValueError:
            continue
        if review_at > now:
            continue
        valid[str(key)] = rule
    return valid


def normalize_provider_totals(
    events: list[dict[str, Any]], official: list[dict[str, Any]], rules: dict[str, dict[str, Any]],
    *, captured_at: datetime, raw_sha256: str, allowed_pairs: set[frozenset[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Return fully sourced normalized rows, excluded observations, and targeted games.

    Quote IDs marked local: are content digests, not sportsbook identifiers.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    count = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("sport_key") != "icehockey_nhl":
            continue
        home, away = _clean(event.get("home_team", "")), _clean(event.get("away_team", ""))
        if frozenset((home, away)) not in allowed_pairs:
            continue
        count += 1
        event_reference = str(event.get("id", ""))
        try:
            official_match = _match_official_event(event, official)
        except ValueError as exc:
            rejected.append({"event_id": event_reference, "reason_code": str(exc)})
            continue
        for bookmaker in event.get("bookmakers", []):
            if not isinstance(bookmaker, dict):
                continue
            book_key = bookmaker.get("key")
            if not isinstance(book_key, str) or not book_key:
                rejected.append({"event_id": event_reference, "reason_code": "BOOKMAKER_KEY_MISSING"})
                continue
            for market in bookmaker.get("markets", []):
                if not isinstance(market, dict) or market.get("key") != "totals":
                    continue
                prefix = {"event_id": event_reference, "bookmaker_key": book_key, "market": "totals"}
                try:
                    market_observed = _utc(market.get("last_update"))
                    outcomes = market.get("outcomes")
                    if not isinstance(outcomes, list) or len(outcomes) != 2:
                        raise ValueError("TOTAL_OUTCOMES_AMBIGUOUS")
                    by_name = {x.get("name"): x for x in outcomes if isinstance(x, dict)}
                    if set(by_name) != {"Over", "Under"}:
                        raise ValueError("TOTAL_OUTCOME_NAMES_MISMATCH")
                    line_over, line_under = by_name["Over"].get("point"), by_name["Under"].get("point")
                    if (isinstance(line_over, bool) or isinstance(line_under, bool)
                            or not isinstance(line_over, (float, int))
                            or not isinstance(line_under, (float, int))
                            or line_over <= 0 or line_over != line_under):
                        raise ValueError("TOTAL_LINES_MISMATCH")
                    prices = (by_name["Over"].get("price"), by_name["Under"].get("price"))
                    if any(isinstance(v, bool) or not isinstance(v, (float, int))
                           or not (1 < v < 1000) for v in prices):
                        raise ValueError("TOTAL_PRICES_INVALID")
                    rule = rules.get(book_key)
                    if rule is None:
                        raise ValueError("BOOK_MARKET_RULE_UNVERIFIED")
                    local_id = "local:sha256:" + hashlib.sha256(json.dumps(
                        [raw_sha256, event_reference, book_key, "totals", market_observed.isoformat(),
                         line_over, *prices], separators=(",", ":"), ensure_ascii=True,
                    ).encode("utf-8")).hexdigest()
                    accepted.append({
                        "canonical_event_id": f"nhl:{official_match['id']}",
                        "event_identity_verified": True,
                        "provider_event_id": event_reference,
                        "provider_quote_id": local_id,  # NOT a provider-native quote ID
                        "book": book_key,
                        "source_observed_at": market_observed.isoformat(),
                        "captured_at": captured_at.isoformat(),
                        "source_capture_method": "provider_api",
                        "scheduled_start_at": official_match["start"].isoformat(),
                        "market_state": "pregame" if market_observed < official_match["start"] else "inplay",
                        "quote_status": "open",  # Listed at aggregator; not confirmed executable at bookmaker
                        "sport": "NHL", "competition": "NHL", "market_type": "total",
                        "period": "full_game", "line": line_over, "line_role": "main",
                        "over_odds": prices[0], "under_odds": prices[1],
                        "settlement_scope": rule["scope"],
                        "settlement_rule_url": rule["source_url"],
                        "settlement_rule_verified_at": _utc(rule["verified_at"]).isoformat(),
                        "settlement_rule_verified": True,
                        "commission_fraction": rule["commission_fraction"],
                        "source_evidence_sha256": raw_sha256,
                        "quote_id_origin": "local_content_digest",
                    })
                except (TypeError, ValueError) as exc:
                    rejected.append(dict(prefix, reason_code=str(exc)))
    return accepted, rejected, count


def _archive(raw: bytes, *, root: Path, source: str, source_url: str, timestamp: datetime) -> dict[str, Any]:
    """Content-addressed raw bytes with append-only manifest, no credentials in metadata."""
    digest = hashlib.sha256(raw).hexdigest()
    blob_dir = root / "sha256"
    blob_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob = blob_dir / f"{digest}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(blob), flags, 0o600)
    except FileExistsError:
        if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
            raise ValueError("ARCHIVE_CONTENT_HASH_MISMATCH")
    else:
        with os.fdopen(descriptor, "wb") as writer:
            writer.write(raw)
            writer.flush()
            os.fsync(writer.fileno())
    record = {
        "schema_version": "doctore.raw-source-evidence.v1",
        "source": source, "source_url": source_url,  # Never include ?apiKey=...
        "retrieved_at": timestamp.isoformat(),
        "raw_sha256": digest, "bytes": len(raw),
        "relative_path": str(Path("sha256") / f"{digest}.json"),
    }
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    append_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        append_flags |= os.O_NOFOLLOW
    fd = os.open(str(root / "manifest.jsonl"), append_flags, 0o600)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def _http_get(url: str, expected_host: str) -> RawDownload:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != expected_host:
        raise ValueError("UNAPPROVED_SOURCE_ENDPOINT")
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Doctore-Research-Adapter/1.0"})
    try:
        with opener.open(request, timeout=12) as response:
            if response.status != 200:
                raise ValueError("UPSTREAM_NOT_OK")
            raw = response.read(MAX_RAW_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        # Never echo the request URL, which contains the Odds API credential.
        raise ValueError("UPSTREAM_FETCH_FAILED") from exc
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("UPSTREAM_RESPONSE_TOO_LARGE")
    return RawDownload(raw=raw, fetched_at=datetime.now(timezone.utc))


def collect_live_nhl_totals(
    params: CollectNhlTotalsInput,
    *, fetch: Callable[[str, str], RawDownload] = _http_get,
    current_time: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    env: dict[str, str] | None = None,
) -> CollectNhlTotalsOutput:
    """Network-enabled collection; no bet signals unless independent policy approves.

    The injected fetch and clock exist for deterministic offline regression tests.
    """
    environment = os.environ if env is None else env
    api_key = environment.get("DOCTORE_ODDS_API_KEY", "").strip()
    if not api_key:
        return CollectNhlTotalsOutput(status="BLOCKED_NO_ODDS_API_KEY", notes=[
            "Odds API key not configured; no network access or invented quotes."])
    try:
        target_pairs = _target_pairs(params.target_event_pairs)
    except ValueError as exc:
        return CollectNhlTotalsOutput(status=str(exc))
    root = Path(environment.get("DOCTORE_ODDS_EVIDENCE_ROOT", "artifacts/nhl-raw-evidence")).expanduser().resolve()
    evidences: list[dict[str, Any]] = []
    try:
        time_now = current_time()
        if time_now.tzinfo is None:
            raise ValueError("CLOCK_TIMEZONE_REQUIRED")
        now = time_now.astimezone(timezone.utc)
        rules = _rule_registry(environment, now)
        url = ODDS_ENDPOINT + "?" + urlencode({
            "apiKey": api_key, "regions": params.regions, "markets": "totals",
            "oddsFormat": "decimal", "dateFormat": "iso",
        })
        downloaded = fetch(url, "api.the-odds-api.com")
        evidences.append(_archive(downloaded.raw, root=root, source="the-odds-api-v4",
                                  source_url=ODDS_ENDPOINT, timestamp=downloaded.fetched_at))
        odds = _decode_json(downloaded.raw)
        if not isinstance(odds, list):
            raise ValueError("ODDS_RESPONSE_NOT_LIST")
        # Limit NHL schedule lookups to targeted events, and to four UTC dates.
        targets = [x for x in odds if isinstance(x, dict) and x.get("sport_key") == "icehockey_nhl"
                   and frozenset((_clean(x.get("home_team", "")), _clean(x.get("away_team", "")))) in target_pairs]
        dates: set[date] = set()
        for event in targets:
            dt = _utc(event.get("commence_time"))
            dates.add(dt.date())
        if len(dates) > 4:
            raise ValueError("TOO_MANY_TARGET_SCHEDULE_DATES")
        schedules = []
        for day in sorted(dates):
            schedule_url = NHL_SCHEDULE_PREFIX + day.isoformat()
            schedule_download = fetch(schedule_url, "api-web.nhle.com")
            evidences.append(_archive(schedule_download.raw, root=root,
                                      source="nhl-public-schedule", source_url=schedule_url,
                                      timestamp=schedule_download.fetched_at))
            payload = _decode_json(schedule_download.raw)
            if not isinstance(payload, dict):
                raise ValueError("NHL_SCHEDULE_INVALID")
            schedules.append(payload)
        official = _official_games(schedules)
        received_at = current_time()
        if received_at.tzinfo is None:
            raise ValueError("CLOCK_TIMEZONE_REQUIRED")
        received_at = received_at.astimezone(timezone.utc)
        normalized, excluded, count = normalize_provider_totals(
            targets, official, rules, captured_at=downloaded.fetched_at,
            raw_sha256=evidences[0]["raw_sha256"], allowed_pairs=target_pairs,
        )
        from .nhl_quote_scanner import scan_nhl_totals
        scan = scan_nhl_totals(normalized, received_at.isoformat(), params.max_age_seconds) if normalized else None
        return CollectNhlTotalsOutput(
            status="SHADOW_SCANNED" if scan and scan.eligible_quote_count else "BLOCKED_UNVERIFIED_QUOTES",
            raw_evidence=evidences, input_event_count=count,
            normalized_quote_count=len(normalized), excluded=excluded,
            scan=scan.model_dump() if scan else None,
            notes=["Provider last_update is aggregator market observation, not bookmaker-native timestamp.",
                   "Raw payload SHA256 is retained. Provider quote ID is a local hash, not sportsbook-native.",
                   "Source feed presence is not bookmaker execution confirmation.",
                   "Rule registry needs independently reviewed exact-market settlement and fee evidence."],
        )
    except (ValueError, OSError, TypeError) as exc:
        code = str(exc)
        # Never print upstream bodies, credentials, or arbitrary filesystem paths.
        if not (code.startswith("BLOCKED_") or code.isupper() or code.startswith("TARGET_PAIR")):
            code = "SOURCE_VALIDATION_FAILED"
        return CollectNhlTotalsOutput(
            status="SOURCE_ERROR", raw_evidence=evidences,
            excluded=[{"reason_code": code}], notes=["Any successfully fetched raw responses were preserved."])
