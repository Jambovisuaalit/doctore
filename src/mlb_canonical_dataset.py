"""Build a leakage-audited MLB full-game totals training dataset.

The builder is intentionally fail-closed. Historical odds rows are resolved
against an authoritative schedule cache by MLB ``gamePk``. Row adjacency is
never used as an event identity rule.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import csv
from hashlib import sha256
import io
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class DatasetBuildError(ValueError):
    """Raised when event identity, provenance or point-in-time rules fail."""


TEAM_CODE_TO_ID: dict[str, int] = {
    "ARI": 109, "AZ": 109,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CWS": 145, "CHW": 145,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KC": 118, "KCR": 118,
    "LAA": 108, "ANA": 108,
    "LAD": 119,
    "MIA": 146, "FLA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYY": 147,
    "OAK": 133, "ATH": 133,
    "PHI": 143,
    "PIT": 134,
    "SD": 135, "SDP": 135,
    "SEA": 136,
    "SF": 137, "SFG": 137,
    "STL": 138,
    "TB": 139, "TBR": 139,
    "TEX": 140,
    "TOR": 141,
    "WSH": 120, "WAS": 120,
}

FEATURE_COLUMNS: tuple[str, ...] = (
    "market_total_line",
    "away_games_prior",
    "home_games_prior",
    "away_season_runs_for_pg",
    "away_season_runs_against_pg",
    "home_season_runs_for_pg",
    "home_season_runs_against_pg",
    "away_rolling5_runs_for",
    "away_rolling5_runs_against",
    "home_rolling5_runs_for",
    "home_rolling5_runs_against",
    "away_rolling10_runs_for",
    "away_rolling10_runs_against",
    "home_rolling10_runs_for",
    "home_rolling10_runs_against",
    "away_rolling20_runs_for",
    "away_rolling20_runs_against",
    "home_rolling20_runs_for",
    "home_rolling20_runs_against",
    "away_rolling10_win_pct",
    "home_rolling10_win_pct",
    "away_rest_days",
    "home_rest_days",
)

CANONICAL_COLUMNS: tuple[str, ...] = (
    "event_id",
    "game_pk",
    "official_date",
    "cutoff_group_at",
    "event_start_at",
    "away_team_id",
    "home_team_id",
    *FEATURE_COLUMNS,
    "final_total_runs",
    "total_line",
    "over_odds_decimal",
    "under_odds_decimal",
)


@dataclass(frozen=True)
class OddsRow:
    official_date: date
    side: str
    team_id: int
    team_code: str
    game_number: int
    total_line: float
    over_odds_decimal: float
    under_odds_decimal: float
    source_line: int


@dataclass(frozen=True)
class ScheduleGame:
    game_pk: int
    official_date: date
    start_at: str
    away_team_id: int
    home_team_id: int
    away_score: int
    home_score: int
    game_number: int
    scheduled_innings: int
    status: str


@dataclass(frozen=True)
class JoinedGame:
    game: ScheduleGame
    total_line: float
    over_odds_decimal: float
    under_odds_decimal: float
    away_source_line: int
    home_source_line: int


@dataclass(frozen=True)
class TeamGame:
    official_date: date
    runs_for: int
    runs_against: int
    won: bool


def american_to_decimal(value: str | int | float) -> float:
    try:
        american = float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetBuildError(f"invalid American odds: {value!r}") from exc
    if not math.isfinite(american) or american == 0:
        raise DatasetBuildError(f"invalid American odds: {value!r}")
    decimal = 1.0 + (american / 100.0 if american > 0 else 100.0 / abs(american))
    if decimal <= 1.0:
        raise DatasetBuildError(f"decimal odds must exceed 1: {decimal}")
    return round(decimal, 12)


def _normalise_odds_csv_text(text: str) -> str:
    """Accept a normal CSV or a one-column sheet export containing CSV lines."""
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        raise DatasetBuildError("odds input is empty")
    if lines[0].count(",") >= 9:
        return "\n".join(lines) + "\n"
    decoded: list[str] = []
    for line in lines:
        parsed = next(csv.reader([line]))
        if len(parsed) != 1:
            raise DatasetBuildError("unsupported odds CSV layout")
        decoded.append(parsed[0])
    return "\n".join(decoded) + "\n"


def parse_odds_csv(path: str | Path) -> tuple[list[OddsRow], dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(_normalise_odds_csv_text(text)))
    expected = {
        "date", "at", "team", "gameNumber", "total", "overOdds", "underOdds"
    }
    if not expected.issubset(set(reader.fieldnames or [])):
        raise DatasetBuildError(
            f"odds columns missing: {sorted(expected - set(reader.fieldnames or []))}"
        )
    parsed: list[OddsRow] = []
    rejected: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], OddsRow] = {}
    for source_line, raw in enumerate(reader, start=2):
        try:
            code = str(raw["team"]).strip().upper()
            team_id = TEAM_CODE_TO_ID[code]
            side = str(raw["at"]).strip().upper()
            if side not in {"V", "H"}:
                raise DatasetBuildError("at must be V or H")
            if str(raw["overOdds"]).upper() == "NA" or str(raw["underOdds"]).upper() == "NA":
                raise DatasetBuildError("two-sided total odds missing")
            row = OddsRow(
                official_date=date.fromisoformat(str(raw["date"]).strip()),
                side=side,
                team_id=team_id,
                team_code=code,
                game_number=int(float(str(raw["gameNumber"]).strip())),
                total_line=float(str(raw["total"]).strip()),
                over_odds_decimal=american_to_decimal(str(raw["overOdds"]).strip()),
                under_odds_decimal=american_to_decimal(str(raw["underOdds"]).strip()),
                source_line=source_line,
            )
            if not math.isfinite(row.total_line) or row.total_line <= 0:
                raise DatasetBuildError("total line must be positive")
            key = (row.official_date, row.side, row.team_id, row.game_number)
            previous = seen.get(key)
            if previous is not None:
                if previous != row:
                    raise DatasetBuildError(f"conflicting duplicate odds key: {key}")
                continue
            seen[key] = row
            parsed.append(row)
        except (KeyError, TypeError, ValueError, DatasetBuildError) as exc:
            rejected.append({"source_line": source_line, "error": str(exc), "row": dict(raw)})
    if not parsed:
        raise DatasetBuildError("no valid odds rows")
    return parsed, {
        "input_rows": len(parsed) + len(rejected),
        "valid_rows": len(parsed),
        "rejected_rows": rejected,
        "date_min": min(row.official_date for row in parsed).isoformat(),
        "date_max": max(row.official_date for row in parsed).isoformat(),
    }


def parse_statsapi_schedule(paths: Sequence[str | Path]) -> list[ScheduleGame]:
    games: dict[int, ScheduleGame] = {}
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping) or not isinstance(payload.get("dates"), list):
            raise DatasetBuildError(f"invalid StatsAPI schedule payload: {path}")
        for date_block in payload["dates"]:
            for raw in date_block.get("games", []):
                status = str(raw.get("status", {}).get("detailedState", ""))
                away = raw.get("teams", {}).get("away", {})
                home = raw.get("teams", {}).get("home", {})
                try:
                    item = ScheduleGame(
                        game_pk=int(raw["gamePk"]),
                        official_date=date.fromisoformat(str(raw["officialDate"])),
                        start_at=str(raw["gameDate"]),
                        away_team_id=int(away["team"]["id"]),
                        home_team_id=int(home["team"]["id"]),
                        away_score=int(away["score"]),
                        home_score=int(home["score"]),
                        game_number=int(raw.get("gameNumber", 1)),
                        scheduled_innings=int(raw.get("scheduledInnings", 9)),
                        status=status,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise DatasetBuildError(
                        f"schedule game is missing required final fields in {path}"
                    ) from exc
                previous = games.get(item.game_pk)
                if previous is not None and previous != item:
                    raise DatasetBuildError(f"conflicting gamePk payload: {item.game_pk}")
                games[item.game_pk] = item
    if not games:
        raise DatasetBuildError("schedule cache contains no games")
    return sorted(games.values(), key=lambda game: (game.official_date, game.start_at, game.game_pk))


def join_odds_to_schedule(
    odds_rows: Sequence[OddsRow], schedule_games: Sequence[ScheduleGame]
) -> tuple[list[JoinedGame], dict[str, Any]]:
    index = {
        (row.official_date, row.side, row.team_id, row.game_number): row
        for row in odds_rows
    }
    joined: list[JoinedGame] = []
    rejected: list[dict[str, Any]] = []
    used_lines: set[int] = set()
    for game in schedule_games:
        reasons: list[str] = []
        if game.status not in {"Final", "Game Over", "Completed Early"}:
            reasons.append("GAME_NOT_FINAL")
        if game.scheduled_innings != 9:
            reasons.append("NON_NINE_INNING_DOMAIN")
        away = index.get((game.official_date, "V", game.away_team_id, game.game_number))
        home = index.get((game.official_date, "H", game.home_team_id, game.game_number))
        if away is None:
            reasons.append("AWAY_ODDS_NOT_FOUND")
        if home is None:
            reasons.append("HOME_ODDS_NOT_FOUND")
        if away and home:
            if abs(away.total_line - home.total_line) > 1e-12:
                reasons.append("TOTAL_LINE_CONTRADICTION")
            if abs(away.over_odds_decimal - home.over_odds_decimal) > 1e-12:
                reasons.append("OVER_PRICE_CONTRADICTION")
            if abs(away.under_odds_decimal - home.under_odds_decimal) > 1e-12:
                reasons.append("UNDER_PRICE_CONTRADICTION")
        if reasons:
            rejected.append({"game_pk": game.game_pk, "reasons": reasons})
            continue
        assert away is not None and home is not None
        used_lines.update({away.source_line, home.source_line})
        joined.append(JoinedGame(
            game=game,
            total_line=away.total_line,
            over_odds_decimal=away.over_odds_decimal,
            under_odds_decimal=away.under_odds_decimal,
            away_source_line=away.source_line,
            home_source_line=home.source_line,
        ))
    unmatched = [row.source_line for row in odds_rows if row.source_line not in used_lines]
    return joined, {
        "schedule_games": len(schedule_games),
        "joined_games": len(joined),
        "rejected_games": rejected,
        "unmatched_odds_source_lines": unmatched,
    }


def _mean(items: Iterable[float]) -> float:
    values = list(items)
    if not values:
        raise DatasetBuildError("feature history is empty")
    return sum(values) / len(values)


def _team_features(history: Sequence[TeamGame], current_date: date) -> dict[str, float]:
    if len(history) < 20:
        raise DatasetBuildError("minimum 20 prior same-season games required")
    last5 = history[-5:]
    last10 = history[-10:]
    last20 = history[-20:]
    rest_days = max(0, min(10, (current_date - history[-1].official_date).days - 1))
    return {
        "games_prior": float(len(history)),
        "season_runs_for_pg": _mean(item.runs_for for item in history),
        "season_runs_against_pg": _mean(item.runs_against for item in history),
        "rolling5_runs_for": _mean(item.runs_for for item in last5),
        "rolling5_runs_against": _mean(item.runs_against for item in last5),
        "rolling10_runs_for": _mean(item.runs_for for item in last10),
        "rolling10_runs_against": _mean(item.runs_against for item in last10),
        "rolling20_runs_for": _mean(item.runs_for for item in last20),
        "rolling20_runs_against": _mean(item.runs_against for item in last20),
        "rolling10_win_pct": _mean(1.0 if item.won else 0.0 for item in last10),
        "rest_days": float(rest_days),
    }


def build_canonical_rows(
    joined_games: Sequence[JoinedGame], *, minimum_prior_games: int = 20
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if minimum_prior_games != 20:
        raise DatasetBuildError("feature schema v1 is locked to 20 prior games")
    histories: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    grouped_by_date: dict[date, list[JoinedGame]] = defaultdict(list)
    for joined in joined_games:
        grouped_by_date[joined.game.official_date].append(joined)

    for official_date in sorted(grouped_by_date):
        day_games = sorted(grouped_by_date[official_date], key=lambda item: item.game.game_pk)
        pending_history: list[tuple[int, int, TeamGame]] = []
        for joined in day_games:
            game = joined.game
            season = official_date.year
            away_history = histories[(season, game.away_team_id)]
            home_history = histories[(season, game.home_team_id)]
            if len(away_history) < minimum_prior_games or len(home_history) < minimum_prior_games:
                skipped.append({
                    "game_pk": game.game_pk,
                    "reason": "INSUFFICIENT_PRIOR_GAMES",
                    "away_prior": len(away_history),
                    "home_prior": len(home_history),
                })
            else:
                away = _team_features(away_history, official_date)
                home = _team_features(home_history, official_date)
                row: dict[str, Any] = {
                    "event_id": f"mlb:{game.game_pk}",
                    "game_pk": game.game_pk,
                    "official_date": official_date.isoformat(),
                    "cutoff_group_at": f"{official_date.isoformat()}T00:00:00+00:00",
                    "event_start_at": game.start_at,
                    "away_team_id": game.away_team_id,
                    "home_team_id": game.home_team_id,
                    "market_total_line": joined.total_line,
                    "final_total_runs": game.away_score + game.home_score,
                    "total_line": joined.total_line,
                    "over_odds_decimal": joined.over_odds_decimal,
                    "under_odds_decimal": joined.under_odds_decimal,
                }
                for name, value in away.items():
                    row[f"away_{name}"] = value
                for name, value in home.items():
                    row[f"home_{name}"] = value
                if set(FEATURE_COLUMNS) - set(row):
                    raise DatasetBuildError("feature construction did not satisfy locked schema")
                rows.append(row)
            pending_history.extend([
                (season, game.away_team_id, TeamGame(
                    official_date=official_date,
                    runs_for=game.away_score,
                    runs_against=game.home_score,
                    won=game.away_score > game.home_score,
                )),
                (season, game.home_team_id, TeamGame(
                    official_date=official_date,
                    runs_for=game.home_score,
                    runs_against=game.away_score,
                    won=game.home_score > game.away_score,
                )),
            ])
        for season, team_id, item in pending_history:
            histories[(season, team_id)].append(item)

    rows.sort(key=lambda row: (row["cutoff_group_at"], row["game_pk"]))
    return rows, {"canonical_rows": len(rows), "skipped_rows": skipped}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def write_dataset_bundle(
    *,
    rows: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    dataset_id: str,
    dataset_version: str,
    created_at: str,
    source_manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    if not rows:
        raise DatasetBuildError("cannot lock an empty canonical dataset")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=list(CANONICAL_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in CANONICAL_COLUMNS})
    csv_bytes = csv_buffer.getvalue().encode("utf-8")
    dataset_sha = _sha256_bytes(csv_bytes)
    csv_path = destination / "mlb-full-game-totals.csv"
    csv_path.write_bytes(csv_bytes)

    manifest = {
        "schema_version": "doctore.training-dataset.v1",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "sport": "MLB",
        "competition": "MLB",
        "market_type": "total",
        "target_market": "full_game_total",
        "period": "full_game",
        "settlement_rules": "full_game_including_extra_innings_push_on_exact_integer_line",
        "target_definition": "away_final_runs + home_final_runs",
        "feature_schema_version": "mlb.full-game-total.prior-results.v1",
        "created_at": created_at,
        "locked_at": created_at,
        "locked": True,
        "dataset_sha256": dataset_sha,
        "row_count": len(rows),
        "columns": list(CANONICAL_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "target_column": "final_total_runs",
        "line_column": "total_line",
        "over_odds_column": "over_odds_decimal",
        "under_odds_column": "under_odds_decimal",
        "timestamp_column": "cutoff_group_at",
        "sort_order": "timestamp_nondecreasing_grouped",
        "source_manifest": "source-manifest.json",
        "notes": "Same official-date games form one leakage boundary; no same-day result enters another row.",
    }
    files = {
        "training-dataset-manifest.json": manifest,
        "source-manifest.json": dict(source_manifest),
        "leakage-audit.json": dict(audit),
    }
    hashes = {csv_path.name: dataset_sha}
    for name, payload in files.items():
        content = (_canonical_json(payload) + "\n").encode("utf-8")
        path = destination / name
        path.write_bytes(content)
        hashes[name] = _sha256_bytes(content)
    for path in destination.iterdir():
        path.chmod(0o444)
    return {"manifest": manifest, "artifact_sha256": hashes}
