"""Canonical MLB full-game totals dataset builder.

The builder is intentionally fail-closed. It accepts legacy team-level closing
odds and one-row-per-game final results, joins on the full event identity, and
emits only transparent pre-game market features. It never joins on date and
team alone and never treats post-game box-score fields as features.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ODDS_COLUMNS = (
    "date", "at", "team", "gameNumber", "line", "runLine",
    "runLineOdds", "total", "overOdds", "underOdds",
)
RESULT_COLUMNS = (
    "source_game_id", "game_date", "game_number", "away_team", "home_team",
    "away_runs", "home_runs", "event_start_at", "status",
)
DATASET_COLUMNS = (
    "event_id", "source_game_id", "game_date", "game_number", "away_team",
    "home_team", "event_start_at", "feature_cutoff_at", "slate_id",
    "market_timestamp_method", "market_line", "no_vig_over_probability",
    "market_overround", "over_odds_decimal", "under_odds_decimal",
    "actual_total",
)
FEATURE_COLUMNS = (
    "market_line", "no_vig_over_probability", "market_overround",
)

TEAM_ALIASES = {
    "ANA": "LAA", "CHA": "CWS", "CHN": "CHC", "KCA": "KC",
    "LAN": "LAD", "NYA": "NYY", "NYN": "NYM", "SDN": "SD",
    "SFN": "SF", "SLN": "STL", "TBA": "TB", "WAS": "WSH",
}


class DatasetBuildError(ValueError):
    """Raised for malformed source contracts or unsafe build settings."""


@dataclass(frozen=True)
class OddsTeamRow:
    game_date: str
    side: str
    team: str
    game_number: int
    moneyline_american: float
    total_line: float
    over_odds_american: float
    under_odds_american: float
    source_row_number: int


@dataclass(frozen=True)
class ResultGame:
    source_game_id: str
    game_date: str
    game_number: int
    away_team: str
    home_team: str
    away_runs: int
    home_runs: int
    event_start_at: str
    status: str


@dataclass(frozen=True)
class Rejection:
    source_game_id: str
    game_date: str
    away_team: str
    home_team: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class BuildReport:
    schema_version: str
    source_odds_rows: int
    source_result_games: int
    accepted_games: int
    rejected_games: int
    unmatched_result_games: int
    unused_odds_rows: int
    first_feature_cutoff_at: str | None
    last_feature_cutoff_at: str | None
    timestamp_method: str
    research_only: bool
    production_eligible: bool
    reason_codes: tuple[str, ...]


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip().replace("−", "-").replace("–", "-")


def _team(value: Any) -> str:
    team = _clean(value).upper()
    return TEAM_ALIASES.get(team, team)


def _integer(value: Any, name: str) -> int:
    text = _clean(value)
    try:
        number = int(float(text))
    except ValueError as exc:
        raise DatasetBuildError(f"{name} must be an integer: {value!r}") from exc
    return number


def _number(value: Any, name: str) -> float:
    text = _clean(value)
    if text.upper() in {"", "NA", "N/A", "NULL", "NONE"}:
        raise DatasetBuildError(f"{name} is missing")
    try:
        number = float(text)
    except ValueError as exc:
        raise DatasetBuildError(f"{name} must be numeric: {value!r}") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise DatasetBuildError(f"{name} must be finite")
    return number


def _iso_timestamp(value: Any, name: str) -> datetime:
    text = _clean(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DatasetBuildError(f"{name} must be ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise DatasetBuildError(f"{name} must include timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: Any, name: str) -> str:
    text = _clean(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise DatasetBuildError(f"{name} must be YYYY-MM-DD: {value!r}") from exc


def american_to_decimal(value: float) -> float:
    """Convert non-zero American odds to decimal odds."""
    odds = float(value)
    if odds == 0:
        raise DatasetBuildError("American odds cannot be zero")
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def binary_no_vig(over_decimal: float, under_decimal: float) -> tuple[float, float]:
    if over_decimal <= 1.0 or under_decimal <= 1.0:
        raise DatasetBuildError("decimal odds must be greater than 1")
    over_raw = 1.0 / over_decimal
    under_raw = 1.0 / under_decimal
    market_sum = over_raw + under_raw
    return over_raw / market_sum, market_sum - 1.0


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_csv_records(path: str | Path) -> Iterable[tuple[int, Mapping[str, str]]]:
    """Read ordinary CSV or a Google-Sheets export containing CSV lines in col A."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows:
        raise DatasetBuildError(f"source is empty: {path}")

    if len(raw_rows[0]) == 1 and "," in raw_rows[0][0]:
        expanded = [next(csv.reader([row[0]])) if row else [] for row in raw_rows]
    else:
        expanded = raw_rows
    header = tuple(_clean(v) for v in expanded[0])
    for row_number, row in enumerate(expanded[1:], start=2):
        if not any(_clean(v) for v in row):
            continue
        padded = list(row) + [""] * max(0, len(header) - len(row))
        yield row_number, dict(zip(header, padded[: len(header)]))


def read_legacy_odds(path: str | Path) -> list[OddsTeamRow]:
    rows: list[OddsTeamRow] = []
    for row_number, row in _iter_csv_records(path):
        missing = set(ODDS_COLUMNS) - set(row)
        if missing:
            raise DatasetBuildError(f"odds source missing columns: {sorted(missing)}")
        side = _clean(row["at"]).upper()
        if side not in {"V", "H"}:
            raise DatasetBuildError(f"odds row {row_number}: at must be V or H")
        rows.append(
            OddsTeamRow(
                game_date=_date(row["date"], "odds.date"),
                side=side,
                team=_team(row["team"]),
                game_number=_integer(row["gameNumber"], "odds.gameNumber"),
                moneyline_american=_number(row["line"], "odds.line"),
                total_line=_number(row["total"], "odds.total"),
                over_odds_american=_number(row["overOdds"], "odds.overOdds"),
                under_odds_american=_number(row["underOdds"], "odds.underOdds"),
                source_row_number=row_number,
            )
        )
    return rows


def read_results(path: str | Path) -> list[ResultGame]:
    games: list[ResultGame] = []
    seen: set[str] = set()
    for _, row in _iter_csv_records(path):
        missing = set(RESULT_COLUMNS) - set(row)
        if missing:
            raise DatasetBuildError(f"results source missing columns: {sorted(missing)}")
        source_game_id = _clean(row["source_game_id"])
        if not source_game_id or source_game_id in seen:
            raise DatasetBuildError(f"duplicate or empty source_game_id: {source_game_id!r}")
        seen.add(source_game_id)
        status = _clean(row["status"]).lower()
        if status not in {"final", "completed", "game over"}:
            continue
        games.append(
            ResultGame(
                source_game_id=source_game_id,
                game_date=_date(row["game_date"], "results.game_date"),
                game_number=_integer(row["game_number"], "results.game_number"),
                away_team=_team(row["away_team"]),
                home_team=_team(row["home_team"]),
                away_runs=_integer(row["away_runs"], "results.away_runs"),
                home_runs=_integer(row["home_runs"], "results.home_runs"),
                event_start_at=_iso_timestamp(row["event_start_at"], "results.event_start_at").isoformat(),
                status=status,
            )
        )
    return games


def _event_id(game: ResultGame) -> str:
    payload = "|".join(
        [game.source_game_id, game.game_date, str(game.game_number), game.away_team, game.home_team]
    )
    return "mlb_" + sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_rows(
    odds_rows: Sequence[OddsTeamRow],
    result_games: Sequence[ResultGame],
    *,
    close_proxy_seconds: int = 60,
) -> tuple[list[dict[str, Any]], list[Rejection], BuildReport]:
    if close_proxy_seconds < 1:
        raise DatasetBuildError("close_proxy_seconds must be positive")

    odds_index: dict[tuple[str, str, int, str], OddsTeamRow] = {}
    duplicate_keys: set[tuple[str, str, int, str]] = set()
    for row in odds_rows:
        key = (row.game_date, row.team, row.game_number, row.side)
        if key in odds_index:
            duplicate_keys.add(key)
        odds_index[key] = row
    if duplicate_keys:
        raise DatasetBuildError(f"duplicate odds identity keys: {sorted(duplicate_keys)[:5]}")

    used_odds: set[tuple[str, str, int, str]] = set()
    accepted: list[dict[str, Any]] = []
    rejected: list[Rejection] = []
    unmatched = 0

    for game in result_games:
        away_key = (game.game_date, game.away_team, game.game_number, "V")
        home_key = (game.game_date, game.home_team, game.game_number, "H")
        away = odds_index.get(away_key)
        home = odds_index.get(home_key)
        if away is None or home is None:
            unmatched += 1
            rejected.append(Rejection(
                game.source_game_id, game.game_date, game.away_team, game.home_team,
                "ODDS_EVENT_IDENTITY_NOT_FOUND",
                f"missing away={away is None}, home={home is None}; keys={away_key!r}/{home_key!r}",
            ))
            continue
        used_odds.update((away_key, home_key))

        if abs(away.total_line - home.total_line) > 1e-9:
            rejected.append(Rejection(
                game.source_game_id, game.game_date, game.away_team, game.home_team,
                "TOTAL_LINE_CONTRADICTION",
                f"away row={away.total_line}, home row={home.total_line}",
            ))
            continue
        if (
            abs(away.over_odds_american - home.over_odds_american) > 1e-9
            or abs(away.under_odds_american - home.under_odds_american) > 1e-9
        ):
            rejected.append(Rejection(
                game.source_game_id, game.game_date, game.away_team, game.home_team,
                "TOTAL_PRICE_CONTRADICTION",
                "away/home team rows disagree on total prices",
            ))
            continue

        over_decimal = american_to_decimal(away.over_odds_american)
        under_decimal = american_to_decimal(away.under_odds_american)
        no_vig_over, overround = binary_no_vig(over_decimal, under_decimal)
        start = _iso_timestamp(game.event_start_at, "event_start_at")
        cutoff = start - timedelta(seconds=close_proxy_seconds)
        event_id = _event_id(game)
        accepted.append({
            "event_id": event_id,
            "source_game_id": game.source_game_id,
            "game_date": game.game_date,
            "game_number": game.game_number,
            "away_team": game.away_team,
            "home_team": game.home_team,
            "event_start_at": start.isoformat(),
            "feature_cutoff_at": cutoff.isoformat(),
            "slate_id": cutoff.isoformat(),
            "market_timestamp_method": f"derived_closing_proxy_t_minus_{close_proxy_seconds}s",
            "market_line": round(away.total_line, 6),
            "no_vig_over_probability": round(no_vig_over, 12),
            "market_overround": round(overround, 12),
            "over_odds_decimal": round(over_decimal, 12),
            "under_odds_decimal": round(under_decimal, 12),
            "actual_total": game.away_runs + game.home_runs,
        })

    accepted.sort(key=lambda item: (item["feature_cutoff_at"], item["event_id"]))
    first = accepted[0]["feature_cutoff_at"] if accepted else None
    last = accepted[-1]["feature_cutoff_at"] if accepted else None
    reasons = ["MARKET_CAPTURE_TIMESTAMP_DERIVED_NOT_OBSERVED"]
    if not accepted:
        reasons.append("NO_JOINED_CANONICAL_ROWS")
    report = BuildReport(
        schema_version="doctore.mlb-dataset-build-report.v1",
        source_odds_rows=len(odds_rows),
        source_result_games=len(result_games),
        accepted_games=len(accepted),
        rejected_games=len(rejected),
        unmatched_result_games=unmatched,
        unused_odds_rows=len(odds_rows) - len(used_odds),
        first_feature_cutoff_at=first,
        last_feature_cutoff_at=last,
        timestamp_method=f"derived_closing_proxy_t_minus_{close_proxy_seconds}s",
        research_only=True,
        production_eligible=False,
        reason_codes=tuple(reasons),
    )
    return accepted, rejected, report


def write_csv(path: str | Path, columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def build_dataset_files(
    *,
    odds_path: str | Path,
    results_path: str | Path,
    output_dir: str | Path,
    dataset_version: str,
    close_proxy_seconds: int = 60,
    created_at: str | None = None,
) -> dict[str, Any]:
    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError(f"create-only output directory already exists: {destination}")
    destination.mkdir(parents=True)

    odds = read_legacy_odds(odds_path)
    results = read_results(results_path)
    rows, rejections, report = build_rows(
        odds, results, close_proxy_seconds=close_proxy_seconds
    )
    dataset_path = destination / "mlb_full_game_totals_v1.csv"
    rejected_path = destination / "rejected_rows.csv"
    report_path = destination / "build-report.json"
    sources_path = destination / "source-manifest.json"

    write_csv(dataset_path, DATASET_COLUMNS, rows)
    write_csv(rejected_path, tuple(Rejection.__dataclass_fields__), (asdict(v) for v in rejections))
    write_json(report_path, asdict(report))
    source_manifest = {
        "schema_version": "doctore.dataset-sources.v1",
        "odds": {"path": str(odds_path), "sha256": sha256_file(odds_path), "rows": len(odds)},
        "results": {"path": str(results_path), "sha256": sha256_file(results_path), "games": len(results)},
    }
    write_json(sources_path, source_manifest)

    manifest_path: Path | None = None
    if rows:
        now = created_at or datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": "doctore.training-dataset.v1",
            "dataset_id": "mlb_full_game_totals_market_baseline_v1",
            "dataset_version": dataset_version,
            "sport": "MLB",
            "competition": "MLB",
            "market_type": "total",
            "target_market": "full_game_total",
            "period": "full_game",
            "settlement_rules": "full_game_including_extra_innings",
            "target_definition": "away_runs + home_runs after official final settlement",
            "feature_schema_version": "mlb-full-game-total-market-baseline-v1",
            "created_at": now,
            "locked_at": now,
            "locked": True,
            "dataset_sha256": sha256_file(dataset_path),
            "row_count": len(rows),
            "columns": list(DATASET_COLUMNS),
            "feature_columns": list(FEATURE_COLUMNS),
            "target_column": "actual_total",
            "line_column": "market_line",
            "over_odds_column": "over_odds_decimal",
            "under_odds_column": "under_odds_decimal",
            "timestamp_column": "feature_cutoff_at",
            "sort_order": "timestamp_non_decreasing_grouped",
            "slate_column": "slate_id",
            "timestamp_semantics": report.timestamp_method,
            "research_only": True,
            "production_eligible": False,
            "source_manifest": sources_path.name,
            "notes": (
                "Content-locked research baseline. Closing odds are pre-game but their exact "
                "capture timestamps are unavailable; feature_cutoff_at is a deterministic proxy. "
                "Do not use for live bankroll decisions."
            ),
        }
        manifest_path = destination / "training-dataset-manifest.json"
        write_json(manifest_path, manifest)

    return {
        "dataset": str(dataset_path),
        "manifest": str(manifest_path) if manifest_path else None,
        "report": str(report_path),
        "rejections": str(rejected_path),
        "sources": str(sources_path),
        "accepted_games": len(rows),
        "production_eligible": False,
    }
