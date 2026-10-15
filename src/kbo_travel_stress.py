"""Deterministic KBO travel-stress feature engineering.

The index is a transparent research prior, not a causal estimate and not a
permission to alter a supplied model probability. Retain only after locked
chronological ablation testing against the no-vig market baseline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, log
from typing import Literal

TravelMode = Literal[
    "same_venue",
    "local_bus",
    "team_bus",
    "ktx",
    "mixed_bus_ktx",
    "domestic_flight",
    "unknown",
]
TravelScope = Literal["team", "starting_pitcher"]
StressBand = Literal["NEGLIGIBLE", "LOW", "MODERATE", "HIGH", "SEVERE"]

MODE_MULTIPLIERS: dict[TravelMode, float] = {
    "same_venue": 0.00,
    "local_bus": 0.45,
    "team_bus": 1.00,
    "ktx": 0.70,
    "mixed_bus_ktx": 0.80,
    "domestic_flight": 0.85,
    "unknown": 1.00,
}


@dataclass(frozen=True)
class KBOTravelStressInput:
    door_to_door_hours: float
    hours_since_previous_game_end: float
    hours_since_arrival: float
    arrival_local_hour: float
    consecutive_away_series: int = 1
    previous_game_extra_innings: bool = False
    travel_mode: TravelMode = "unknown"
    transport_confirmed: bool = False
    scope: TravelScope = "team"


@dataclass(frozen=True)
class KBOTravelStressResult:
    schema_version: str
    stress_index: float
    stress_band: StressBand
    scope: TravelScope
    travel_mode: TravelMode
    mode_multiplier: float
    effective_travel_hours: float
    route_load: float
    residual_route_load: float
    recovery_pressure: float
    late_arrival_pressure: float
    trip_chain_pressure: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _validate(data: KBOTravelStressInput) -> None:
    for name in (
        "door_to_door_hours",
        "hours_since_previous_game_end",
        "hours_since_arrival",
    ):
        value = getattr(data, name)
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    if not 0 <= data.arrival_local_hour < 24:
        raise ValueError("arrival_local_hour must be in [0, 24)")
    if data.consecutive_away_series < 0:
        raise ValueError("consecutive_away_series must be non-negative")
    if data.travel_mode not in MODE_MULTIPLIERS:
        raise ValueError(f"unsupported travel_mode: {data.travel_mode}")
    if data.scope not in ("team", "starting_pitcher"):
        raise ValueError(f"unsupported scope: {data.scope}")


def _recovery_pressure(hours_since_previous_game_end: float, extra_innings: bool) -> float:
    hours = hours_since_previous_game_end
    if hours >= 42:
        pressure = 0.00
    elif hours >= 36:
        pressure = 0.10
    elif hours >= 30:
        pressure = 0.25
    elif hours >= 24:
        pressure = 0.45
    elif hours >= 18:
        pressure = 0.70
    else:
        pressure = 1.00
    if extra_innings:
        pressure = _clip(pressure + 0.15)
    return pressure


def _late_arrival_pressure(arrival_local_hour: float) -> float:
    hour = arrival_local_hour
    if 6 <= hour < 22:
        return 0.00
    if 22 <= hour < 23:
        return 0.30
    if 23 <= hour < 24:
        return 0.60
    if 0 <= hour < 2:
        return 0.80
    return 1.00


def _stress_band(index: float) -> StressBand:
    if index < 10:
        return "NEGLIGIBLE"
    if index < 25:
        return "LOW"
    if index < 45:
        return "MODERATE"
    if index < 65:
        return "HIGH"
    return "SEVERE"


def calculate_kbo_travel_stress(data: KBOTravelStressInput) -> KBOTravelStressResult:
    """Calculate a 0-100 KBO travel-stress index.

    Design choices:
    - no timezone term: all KBO venues use Asia/Seoul;
    - door-to-door time is primary; distance is only a fallback input upstream;
    - KTX relief is applied only when transport is confirmed;
    - unknown transport is conservatively treated as team bus;
    - route burden decays with a 24-hour half-life after arrival;
    - short recovery, late arrival and an extended road trip amplify route burden,
      but cannot create travel stress when no travel occurred.
    """

    _validate(data)
    warnings: list[str] = []

    mode: TravelMode = data.travel_mode
    if not data.transport_confirmed and mode not in ("same_venue", "unknown"):
        warnings.append("UNCONFIRMED_TRANSPORT_MODE_TREATED_AS_TEAM_BUS")
        mode = "unknown"
    if mode == "unknown":
        warnings.append("TRANSPORT_MODE_UNKNOWN_CONSERVATIVE_BUS_PRIOR")

    mode_multiplier = MODE_MULTIPLIERS[mode]
    effective_hours = data.door_to_door_hours * mode_multiplier

    # KBO-specific route scale: burden begins above 45 minutes and saturates
    # around five effective travel hours. This intentionally excludes the
    # timezone-displacement term used in larger cross-zone leagues.
    route_load = _clip((effective_hours - 0.75) / 4.25)

    half_life_hours = 24.0
    decay = exp(-log(2.0) * data.hours_since_arrival / half_life_hours)
    residual_route_load = route_load * decay

    recovery = _recovery_pressure(
        data.hours_since_previous_game_end,
        data.previous_game_extra_innings,
    )
    late_arrival = _late_arrival_pressure(data.arrival_local_hour)
    trip_chain = _clip((data.consecutive_away_series - 1) / 3.0)

    amplifier = 0.65 + 0.20 * recovery + 0.10 * late_arrival + 0.05 * trip_chain
    stress_index = round(_clip(residual_route_load * amplifier) * 100.0, 1)

    return KBOTravelStressResult(
        schema_version="doctore.kbo-travel-stress.v1",
        stress_index=stress_index,
        stress_band=_stress_band(stress_index),
        scope=data.scope,
        travel_mode=mode,
        mode_multiplier=mode_multiplier,
        effective_travel_hours=round(effective_hours, 3),
        route_load=round(route_load, 4),
        residual_route_load=round(residual_route_load, 4),
        recovery_pressure=round(recovery, 4),
        late_arrival_pressure=round(late_arrival, 4),
        trip_chain_pressure=round(trip_chain, 4),
        warnings=tuple(warnings),
    )
