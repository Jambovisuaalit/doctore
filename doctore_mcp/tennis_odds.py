"""Research-only tennis quote ingestion; exact IDs, complete pairs, honest times."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import csv
import io
import math
import os
import re
from urllib.parse import urlencode, urlsplit, parse_qsl
from urllib.request import Request, HTTPRedirectHandler, build_opener
import json

from .runtime import content_sha256, parse_time
from .schemas import schema_errors


class OddsError(ValueError):
    pass


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise OddsError("TENNIS_ODDS_REQUIRED_FIELD_MISSING")
    return value.strip()


def decimal_price(value, price_format):
    if isinstance(value, bool):
        raise OddsError("TENNIS_ODDS_PRICE_INVALID")
    raw = str(value).strip().replace("−", "-")
    try:
        if price_format == "decimal":
            if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", raw):
                raise ValueError()
            result = Decimal(raw.replace(",", "."))
        elif price_format == "american":
            if not re.fullmatch(r"[+-][0-9]+", raw):
                raise ValueError()
            american = Decimal(raw)
            if abs(american) < 100:
                raise ValueError()
            result = 1 + american / 100 if american > 0 else 1 + 100 / abs(american)
        else:
            raise ValueError()
        converted = float(result)
        if not result.is_finite() or not math.isfinite(converted) or converted <= 1:
            raise ValueError()
        return converted
    except (ValueError, InvalidOperation, OverflowError):
        raise OddsError("TENNIS_ODDS_PRICE_INVALID") from None


def fresh(value, now):
    try:
        age = (now - parse_time(value)).total_seconds()
        if not 0 <= age <= 300:
            raise ValueError()
        return parse_time(value).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise OddsError("TENNIS_ODDS_TIMESTAMP_INVALID_OR_STALE") from None


def pair_snapshots(*, event_id, book, book_market_id, start, captured, competition, rules, outcomes, source, source_url=None):
    if len(outcomes) != 2 or len({o["selection"].casefold() for o in outcomes}) != 2:
        raise OddsError("TENNIS_ODDS_COMPLETE_UNIQUE_PAIR_REQUIRED")
    snapshots = []
    for outcome in outcomes:
        snapshot = dict(schema_version="doctore.market-snapshot.v1", event_id=event_id,
            market_id="research:"+content_sha256([event_id,book,book_market_id,competition,rules,"match_winner",outcome["selection"]]),
            book=book,captured_at=captured,event_start_at=start,sport="TENNIS",competition=competition,
            market_type="moneyline",target_market="full_match_winner",period="full_match",line=None,
            settlement_rules=rules,selection=outcome["selection"],decimal_odds=outcome["decimal_odds"],
            market_status="open",is_complete=True,outcomes=outcomes,source=source)
        if book_market_id:
            snapshot["book_market_id"] = book_market_id
        if source_url:
            snapshot["source_url"] = source_url
        if schema_errors("market",snapshot):
            raise OddsError("TENNIS_ODDS_SNAPSHOT_INVALID")
        snapshots.append(snapshot)
    return snapshots


def import_quotes(data, tour, now):
    """No network. API inputs must be explicitly exported as decimal prices."""
    try:
        if data["source_format"] == "copied_table":
            if len(text(data["raw_table"])) > 50_000:
                raise OddsError("TENNIS_ODDS_INPUT_TOO_LARGE")
            raw = data["raw_table"].strip()
            rows = list(csv.reader(io.StringIO(raw), delimiter="\t"))
            if "\t" not in raw and len(rows) == 4 and all(len(row)==1 for row in rows):
                rows = [[rows[0][0],rows[1][0]],[rows[2][0],rows[3][0]]]
            if len(rows) != 2 or any(len(row) != 2 for row in rows):
                raise OddsError("TENNIS_ODDS_EXPECT_TWO_TAB_SEPARATED_ROWS")
            captured = fresh(data["captured_at"],now)
            start = text(data["event_start_at"])
            if parse_time(start) <= now:
                raise OddsError("TENNIS_ODDS_PREMATCH_ONLY")
            book, event = text(data["book"]), text(data["book_event_id"])
            # Optional shared reference is an explicit user assertion, never a name join.
            event_id = data.get("event_reference") or "manual:"+content_sha256([book,event,start])
            outcomes = [{"selection":text(row[0]),"decimal_odds":decimal_price(row[1],data["price_format"])} for row in rows]
            source_url = text(data["source_url"])
            url = urlsplit(source_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or any(k.lower() in {"apikey","api_key","token","access_token","authorization"} for k,v in parse_qsl(url.query))):
                raise OddsError("TENNIS_ODDS_PUBLIC_HTTPS_SOURCE_REQUIRED")
            snapshots = pair_snapshots(event_id=text(event_id),book=book,book_market_id=data.get("book_market_id"),
                start=start,captured=captured,competition=text(data["competition"]),rules=text(data["settlement_rules"]),
                outcomes=outcomes,source="user_copied_table",source_url=source_url)
            return dict(snapshots=snapshots, rejected=[], source="user_copied_table", raw_input_sha256=content_sha256(data),
                research_only=True, identity_verified=False, executable_price_verified=False,
                received_at=now.isoformat(), recommendation=None, stake=None)
        if data["source_format"] != "odds_api_v4" or data.get("price_format") != "decimal":
            raise OddsError("TENNIS_ODDS_FORMAT_UNSUPPORTED")
        events = data["payload"]
        if not isinstance(events,list) or len(events) > 1000:
            raise OddsError("TENNIS_ODDS_API_PAYLOAD_INVALID")
        snapshots, rejected, seen = [], [], set()
        for event in events:
            try:
                event_id = text(event["id"])
                sport_key = text(event["sport_key"])
                if not sport_key.startswith("tennis_"+tour+"_"):
                    raise OddsError("TENNIS_ODDS_TOUR_MISMATCH")
                start = text(event["commence_time"])
                if parse_time(start) <= now:
                    raise OddsError("TENNIS_ODDS_PREMATCH_ONLY")
                participants = {text(event["home_team"]),text(event["away_team"])}
                if len(participants) != 2 or not isinstance(event["bookmakers"],list):
                    raise OddsError("TENNIS_ODDS_API_PAYLOAD_INVALID")
                for book in event["bookmakers"]:
                    try:
                        book_key = text(book["key"])
                        key = (event_id,book_key)
                        if key in seen:
                            snapshots = [s for s in snapshots if not (s["event_id"]=="oddsapi:"+event_id and s["book"]==book_key)]
                            raise OddsError("TENNIS_ODDS_DUPLICATE_MARKET")
                        seen.add(key)
                        markets = [m for m in book["markets"] if m.get("key") == "h2h"]
                        if len(markets) != 1:
                            raise OddsError("TENNIS_ODDS_COMPLETE_UNIQUE_PAIR_REQUIRED")
                        market = markets[0]
                        # Do not turn local import time into a quote timestamp.
                        captured = fresh(market.get("last_update") or book.get("last_update"),now)
                        outcomes = [{"selection":text(o["name"]),"decimal_odds":decimal_price(o["price"],"decimal")} for o in market["outcomes"]]
                        if {o["selection"] for o in outcomes} != participants:
                            raise OddsError("TENNIS_ODDS_PARTICIPANT_MISMATCH")
                        rules = data.get("settlement_rules_by_book",{}).get(book_key,"unverified")
                        snapshots.extend(pair_snapshots(event_id="oddsapi:"+event_id,book=book_key,book_market_id=None,
                            start=start,captured=captured,competition=sport_key,rules=text(rules),outcomes=outcomes,
                            source="the_odds_api_export"))
                    except (KeyError,TypeError,ValueError,AttributeError) as exc:
                        rejected.append({"event_id":event_id,"book":book.get("key") if isinstance(book,dict) else None,
                                         "reason":str(exc) if isinstance(exc,OddsError) else "TENNIS_ODDS_API_PAYLOAD_INVALID"})
            except (KeyError,TypeError,ValueError,AttributeError) as exc:
                rejected.append({"event_id":event.get("id") if isinstance(event,dict) else None,
                    "reason":str(exc) if isinstance(exc,OddsError) else "TENNIS_ODDS_API_PAYLOAD_INVALID"})
        return dict(snapshots=snapshots,rejected=rejected,source="the_odds_api_export",raw_input_sha256=content_sha256(data),
            research_only=True,identity_verified=False,executable_price_verified=False,received_at=now.isoformat(),
            recommendation=None,stake=None,note="Aggregator event IDs are not bookmaker event/market/player IDs. Retirement rules are unverified unless explicitly supplied.")
    except OddsError:
        raise
    except (KeyError,TypeError,ValueError,AttributeError):
        raise OddsError("TENNIS_ODDS_INPUT_INVALID") from None


def compare_quotes(snapshots, now):
    from .tennis_data import analyze_supplied_market
    if not isinstance(snapshots,list) or not 2 <= len(snapshots) <= 1000:
        raise OddsError("TENNIS_ODDS_COMPARISON_REQUIRES_QUOTES")
    domain = None; books = {}
    fields = ("event_id","event_start_at","sport","competition","market_type","target_market","period","line","settlement_rules","selection")
    for snapshot in snapshots:
        result,reasons=analyze_supplied_market(snapshot,now)
        if reasons:
            raise OddsError("TENNIS_ODDS_COMPARISON_INVALID_OR_STALE")
        if parse_time(snapshot["event_start_at"]) <= now:
            raise OddsError("TENNIS_ODDS_PREMATCH_ONLY")
        current=tuple(parse_time(snapshot[k]).astimezone(timezone.utc) if k=="event_start_at" else snapshot[k] for k in fields)
        current += (tuple(sorted(o["selection"] for o in snapshot["outcomes"])),)
        if domain is not None and current != domain:
            raise OddsError("TENNIS_ODDS_COMPARISON_DOMAIN_MISMATCH")
        domain=current
        if snapshot["settlement_rules"].lower() in {"unknown","unverified","unspecified"}:
            raise OddsError("TENNIS_ODDS_SETTLEMENT_RULES_REQUIRED")
        captured=parse_time(snapshot["captured_at"])
        old=books.get(snapshot["book"])
        if old and parse_time(old["captured_at"]) == captured and old != snapshot:
            raise OddsError("TENNIS_ODDS_CONFLICTING_SAME_TIME_QUOTES")
        if old is None or captured > parse_time(old["captured_at"]):
            books[snapshot["book"]]=snapshot
    if len(books)<2:
        raise OddsError("TENNIS_ODDS_COMPARISON_REQUIRES_DISTINCT_BOOKS")
    timestamps=[parse_time(s["captured_at"]) for s in books.values()]
    if (max(timestamps)-min(timestamps)).total_seconds()>60:
        raise OddsError("TENNIS_ODDS_COMPARISON_TIME_SKEW")
    ranked=sorted(books.values(),key=lambda s:s["decimal_odds"],reverse=True)
    return dict(research_only=True,identity_verified=False,executable_price_verified=False,
        event_id=ranked[0]["event_id"],selection=ranked[0]["selection"],
        quotes=[dict(book=s["book"],decimal_odds=s["decimal_odds"],captured_at=s["captured_at"]) for s in ranked],
        best_observed_book=ranked[0]["book"],best_observed_odds=ranked[0]["decimal_odds"],
        recommendation=None,stake=None,note="Best observed price is not a value-bet recommendation or proof of matching execution conditions.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise OddsError("TENNIS_ODDS_REDIRECT_REJECTED")


def fetch_once(sport_key, *, allow_one_credit=False):
    """Exactly one EU/h2h request, no retry/polling. Expected provider cost: 1 credit."""
    if not allow_one_credit:
        raise OddsError("TENNIS_ODDS_CREDIT_APPROVAL_REQUIRED")
    key=os.environ.get("ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY")
    if not key:
        raise OddsError("TENNIS_ODDS_API_KEY_REQUIRED")
    if not re.fullmatch(r"tennis_(atp|wta)_[a-z0-9_]+",sport_key):
        raise OddsError("TENNIS_ODDS_SPORT_KEY_INVALID")
    query=urlencode(dict(apiKey=key,regions="eu",markets="h2h",oddsFormat="decimal",dateFormat="iso"))
    try:
        with build_opener(NoRedirect()).open(Request(f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?{query}",headers={"Accept":"application/json"}),timeout=10) as response:
            raw=response.read(5_000_001)
            quota={k:response.headers.get(k) for k in ("x-requests-used","x-requests-remaining","x-requests-last")}
        if len(raw)>5_000_000:
            raise OddsError("TENNIS_ODDS_RESPONSE_TOO_LARGE")
        payload=json.loads(raw)
        if not isinstance(payload,list):
            raise OddsError("TENNIS_ODDS_API_PAYLOAD_INVALID")
        return {"source_format":"odds_api_v4","price_format":"decimal","payload":payload},quota
    except OddsError:
        raise
    except Exception:
        # URLs contain the provider-required query credential: never print them.
        raise OddsError("TENNIS_ODDS_REQUEST_FAILED") from None
