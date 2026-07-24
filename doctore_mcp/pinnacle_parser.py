"""Parse manually copied Pinnacle tables into canonical Doctore market snapshots."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

BASEBALL_SCHEMA = [
    "away", "home", "time",
    "ml_away", "ml_home",
    "rl_away_label", "rl_away_price",
    "rl_home_label", "rl_home_price",
    "total_line", "total_over", "total_under",
    "btn", "href",
]

BASKETBALL_SCHEMA = [
    "away", "home", "time",
    "spread_away_label", "spread_away_price",
    "spread_home_label", "spread_home_price",
    "ml_away", "ml_home",
    "total_line", "total_over", "total_under",
    "btn", "href",
]

SCHEMAS = {
    "mlb": BASEBALL_SCHEMA,
    "kbo": BASEBALL_SCHEMA,
    "npb": BASEBALL_SCHEMA,
    "wnba": BASKETBALL_SCHEMA,
    "nba": BASKETBALL_SCHEMA,
}

_HEADER_TOKENS = (
    "ellipsis", "metadata-", "matchupdate-", "price-", "label-", "btn-", "href",
)


@dataclass(frozen=True)
class ParseDiagnostic:
    row_number: int
    status: str
    reason: str
    raw_row: list[str]


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def _number(value: str) -> float:
    normalized = value.strip().replace("−", "-")
    if "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")
    result = float(normalized)
    if result <= 0:
        raise ValueError("number must be positive")
    return result


def _handicap(value: str) -> float:
    return float(value.strip().replace("−", "-").replace(",", "."))


def _looks_like_header(row: list[str], schema: list[str]) -> bool:
    lowered = [cell.strip().lower() for cell in row]
    if lowered == schema:
        return True
    joined = "\t".join(lowered)
    token_hits = sum(token in joined for token in _HEADER_TOKENS)
    numeric_fields = [cell for index, cell in enumerate(row) if index >= 3 and cell.strip()]
    numeric_success = 0
    for cell in numeric_fields:
        try:
            _number(cell)
            numeric_success += 1
        except ValueError:
            pass
    return token_hits >= 2 and numeric_success == 0


def _parse_event_start(event_date: date, raw_time: str, timezone_name: str) -> datetime:
    value = raw_time.strip()
    zone = ZoneInfo(timezone_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed
    except ValueError:
        pass
    for fmt in ("%H:%M", "%H.%M"):
        try:
            parsed_time = datetime.strptime(value, fmt).time()
            return datetime.combine(event_date, parsed_time, tzinfo=zone)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=zone)
        except ValueError:
            continue
    raise ValueError(f"unsupported event time: {raw_time!r}")


def _book_identifier(href: str) -> str | None:
    numbers = re.findall(r"(?<!\d)(\d{7,})(?!\d)", href)
    return numbers[-1] if numbers else None


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _event_id(
    *, sport: str, event_start: datetime, away: str, home: str,
    book_id: str | None, row_number: int,
) -> str:
    identity = book_id or f"row-{row_number}"
    return "-".join([
        sport.upper(), event_start.strftime("%Y%m%d-%H%M"),
        _slug(away), "vs", _slug(home), identity,
    ])


def _market_id(event_id: str, market_code: str, selection: str, line: float | None) -> str:
    line_token = "pk" if line is None else str(line).replace("-", "m").replace(".", "p")
    return f"{event_id}-{market_code}-{_slug(selection)}-{line_token}"


def _settlement_rules(sport: str, market_type: str) -> str:
    if sport in {"MLB", "KBO", "NPB"}:
        if market_type == "moneyline":
            return "action_including_extra_innings"
        return "full_game_including_extra_innings"
    return "full_game_including_overtime"


def _candidate_snapshot(
    *, event_id: str, book_market_id: str | None, captured_at: datetime,
    event_start_at: datetime, sport: str, competition: str,
    market_type: str, target_market: str, line: float | None,
    selection: str, decimal_odds: float, outcomes: list[dict[str, Any]],
    source_url: str | None,
) -> dict[str, Any]:
    snapshot = {
        "schema_version": "doctore.market-snapshot.v1",
        "event_id": event_id,
        "market_id": _market_id(event_id, market_type, selection, line),
        "book": "Pinnacle",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "event_start_at": event_start_at.isoformat(timespec="seconds"),
        "sport": sport,
        "competition": competition,
        "market_type": market_type,
        "target_market": target_market,
        "period": "full_game",
        "line": line,
        "settlement_rules": _settlement_rules(sport, market_type),
        "selection": selection,
        "decimal_odds": decimal_odds,
        "market_status": "open",
        "is_complete": True,
        "outcomes": outcomes,
        "correlation_group": event_id,
        "source": "pinnacle-manual-table",
    }
    if book_market_id:
        snapshot["book_market_id"] = book_market_id
    if source_url and _valid_url(source_url):
        snapshot["source_url"] = source_url
    return snapshot


def parse_pinnacle_table(
    raw_text: str,
    sport: str,
    *,
    event_date: date,
    captured_at: datetime,
    timezone_name: str = "Europe/Helsinki",
    competition: str | None = None,
) -> tuple[list[dict[str, Any]], list[ParseDiagnostic]]:
    """Return selected-side snapshots and a diagnostic for every source row.

    One source game produces six candidates: two moneyline, two spread/run-line,
    and two totals. Each candidate preserves the full outcome set for no-vig.
    """
    key = sport.lower()
    if key not in SCHEMAS:
        raise ValueError(f"unsupported sport: {sport}")
    schema = SCHEMAS[key]
    sport_upper = key.upper()
    competition_value = (competition or sport_upper).strip()
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must include timezone")

    snapshots: list[dict[str, Any]] = []
    diagnostics: list[ParseDiagnostic] = []
    reader = csv.reader(io.StringIO(raw_text), delimiter="\t")

    for row_number, raw_row in enumerate(reader, start=1):
        row = [cell.strip() for cell in raw_row]
        if not row or not any(row):
            diagnostics.append(ParseDiagnostic(row_number, "SKIPPED", "empty row", raw_row))
            continue
        if _looks_like_header(row, schema):
            diagnostics.append(ParseDiagnostic(row_number, "SKIPPED", "header row", raw_row))
            continue
        if len(row) != len(schema):
            diagnostics.append(ParseDiagnostic(
                row_number, "REJECTED",
                f"expected {len(schema)} columns, received {len(row)}", raw_row,
            ))
            continue

        game = dict(zip(schema, row))
        try:
            away = game["away"].strip()
            home = game["home"].strip()
            if not away or not home:
                raise ValueError("away and home are required")
            event_start = _parse_event_start(event_date, game["time"], timezone_name)
            href = game.get("href", "").strip()
            book_id = _book_identifier(href)
            event_id = _event_id(
                sport=sport_upper, event_start=event_start, away=away, home=home,
                book_id=book_id, row_number=row_number,
            )

            ml_away = _number(game["ml_away"])
            ml_home = _number(game["ml_home"])
            ml_outcomes = [
                {"selection": away, "decimal_odds": ml_away},
                {"selection": home, "decimal_odds": ml_home},
            ]
            snapshots.extend([
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type="moneyline", target_market="full_game_moneyline", line=None,
                    selection=away, decimal_odds=ml_away, outcomes=ml_outcomes, source_url=href,
                ),
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type="moneyline", target_market="full_game_moneyline", line=None,
                    selection=home, decimal_odds=ml_home, outcomes=ml_outcomes, source_url=href,
                ),
            ])

            if key in {"mlb", "kbo", "npb"}:
                away_label = _handicap(game["rl_away_label"])
                home_label = _handicap(game["rl_home_label"])
                away_price = _number(game["rl_away_price"])
                home_price = _number(game["rl_home_price"])
                spread_type = "run_line"
                target_market = "full_game_run_line"
            else:
                away_label = _handicap(game["spread_away_label"])
                home_label = _handicap(game["spread_home_label"])
                away_price = _number(game["spread_away_price"])
                home_price = _number(game["spread_home_price"])
                spread_type = "spread"
                target_market = "full_game_spread"
            if not abs(away_label + home_label) < 1e-12:
                raise ValueError(f"spread labels are not opposites: {away_label} vs {home_label}")
            spread_outcomes = [
                {"selection": away, "decimal_odds": away_price},
                {"selection": home, "decimal_odds": home_price},
            ]
            snapshots.extend([
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type=spread_type, target_market=target_market, line=away_label,
                    selection=away, decimal_odds=away_price, outcomes=spread_outcomes, source_url=href,
                ),
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type=spread_type, target_market=target_market, line=home_label,
                    selection=home, decimal_odds=home_price, outcomes=spread_outcomes, source_url=href,
                ),
            ])

            total_line = _number(game["total_line"])
            total_over = _number(game["total_over"])
            total_under = _number(game["total_under"])
            total_outcomes = [
                {"selection": "over", "decimal_odds": total_over},
                {"selection": "under", "decimal_odds": total_under},
            ]
            snapshots.extend([
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type="total", target_market="full_game_total", line=total_line,
                    selection="over", decimal_odds=total_over, outcomes=total_outcomes, source_url=href,
                ),
                _candidate_snapshot(
                    event_id=event_id, book_market_id=book_id, captured_at=captured_at,
                    event_start_at=event_start, sport=sport_upper, competition=competition_value,
                    market_type="total", target_market="full_game_total", line=total_line,
                    selection="under", decimal_odds=total_under, outcomes=total_outcomes, source_url=href,
                ),
            ])
            diagnostics.append(ParseDiagnostic(
                row_number, "PARSED", "six candidate snapshots created", raw_row,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            diagnostics.append(ParseDiagnostic(row_number, "REJECTED", str(exc), raw_row))

    return snapshots, diagnostics
