"""MLB full-game totals feature schema v2.

This module defines feature groups only. It does not acquire data and it does
not permit a feature group to enter model validation merely because columns
exist. Every non-baseline group requires row-level point-in-time provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

FEATURE_SCHEMA_VERSION = "mlb.full-game-total.point-in-time.v2"

BASELINE_V1_COLUMNS: tuple[str, ...] = (
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

STARTER_COLUMNS: tuple[str, ...] = (
    "away_starter_prior30_ip",
    "home_starter_prior30_ip",
    "away_starter_prior30_ra9",
    "home_starter_prior30_ra9",
    "away_starter_days_rest",
    "home_starter_days_rest",
    "away_starter_season_pitch_count",
    "home_starter_season_pitch_count",
)

BULLPEN_COLUMNS: tuple[str, ...] = (
    "away_bullpen_pitches_1d",
    "home_bullpen_pitches_1d",
    "away_bullpen_pitches_3d",
    "home_bullpen_pitches_3d",
    "away_bullpen_appearances_1d",
    "home_bullpen_appearances_1d",
    "away_bullpen_appearances_3d",
    "home_bullpen_appearances_3d",
    "away_bullpen_back_to_back_count",
    "home_bullpen_back_to_back_count",
)

PARK_COLUMNS: tuple[str, ...] = (
    "park_games_prior",
    "park_total_runs_mean_prior",
    "park_run_factor_prior",
)

WEATHER_COLUMNS: tuple[str, ...] = (
    "forecast_temp_f",
    "forecast_wind_speed_mph",
    "forecast_wind_out_component_mph",
    "forecast_relative_humidity_pct",
)


@dataclass(frozen=True)
class FeatureGroupSpec:
    name: str
    columns: tuple[str, ...]
    allowed_availability_modes: tuple[str, ...]
    historical_2012_2021_status: str
    source_policy: str


FEATURE_GROUPS: Mapping[str, FeatureGroupSpec] = {
    "baseline": FeatureGroupSpec(
        name="baseline",
        columns=BASELINE_V1_COLUMNS,
        allowed_availability_modes=("PRIOR_EVENT_FINAL",),
        historical_2012_2021_status="VERIFIED_BASELINE",
        source_policy=(
            "Only prior completed authoritative game results; same-slate outcomes "
            "must be withheld until the full slate is complete."
        ),
    ),
    "starter": FeatureGroupSpec(
        name="starter",
        columns=STARTER_COLUMNS,
        allowed_availability_modes=("PREGAME_SNAPSHOT",),
        historical_2012_2021_status="BLOCKED_PROVENANCE",
        source_policy=(
            "Starter identity must come from an archived pregame snapshot captured "
            "no later than the feature cutoff. Postgame boxscore starter identity "
            "is not accepted as pregame provenance."
        ),
    ),
    "bullpen": FeatureGroupSpec(
        name="bullpen",
        columns=BULLPEN_COLUMNS,
        allowed_availability_modes=("PRIOR_EVENT_FINAL",),
        historical_2012_2021_status="READY_TO_ACQUIRE",
        source_policy=(
            "Usage may be derived only from completed prior games whose final state "
            "was available before the feature cutoff; current/same-slate games are excluded."
        ),
    ),
    "park": FeatureGroupSpec(
        name="park",
        columns=PARK_COLUMNS,
        allowed_availability_modes=("PRIOR_EVENT_FINAL", "STATIC_KNOWN_BEFORE_CUTOFF"),
        historical_2012_2021_status="READY_TO_ACQUIRE",
        source_policy=(
            "Park effect must be derived prior-only from venue history or from a "
            "versioned value known before cutoff. Full-season hindsight park factors "
            "must never be joined to earlier rows."
        ),
    ),
    "weather": FeatureGroupSpec(
        name="weather",
        columns=WEATHER_COLUMNS,
        allowed_availability_modes=("FORECAST_RUN",),
        historical_2012_2021_status="BLOCKED_PERIOD",
        source_policy=(
            "Weather must be an archived forecast run issued before feature cutoff. "
            "Reanalysis/observed-at-game-time data cannot substitute for a pregame forecast."
        ),
    ),
}

ABlation_ORDER: tuple[str, ...] = ("baseline", "starter", "bullpen", "park", "weather")


def group_columns(group_name: str) -> tuple[str, ...]:
    try:
        return FEATURE_GROUPS[group_name].columns
    except KeyError as exc:
        raise ValueError(f"unknown feature group: {group_name}") from exc


def validate_feature_group_partition() -> None:
    seen: set[str] = set()
    for spec in FEATURE_GROUPS.values():
        if not spec.columns:
            raise ValueError(f"feature group {spec.name} has no columns")
        overlap = seen.intersection(spec.columns)
        if overlap:
            raise ValueError(f"feature columns overlap across groups: {sorted(overlap)}")
        seen.update(spec.columns)


validate_feature_group_partition()
