"""KBO team operational stress: travel plus bullpen workload.

The composite is a transparent research prior. It must not directly alter a
supplied model probability, EV, edge, or Kelly. Retain only after locked
chronological out-of-sample ablation testing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from kbo_travel_stress import (
    KBOTravelStressInput,
    KBOTravelStressResult,
    StressBand,
    calculate_kbo_travel_stress,
)

RelieverRole = Literal["closer", "setup", "middle", "long", "unknown"]
ReliefAvailability = Literal["available", "limited", "unavailable", "unknown"]

ROLE_WEIGHTS: dict[RelieverRole, float] = {
    "closer": 1.35,
    "setup": 1.20,
    "middle": 1.00,
    "long": 0.80,
    "unknown": 1.00,
}

AVAILABILITY_PRESSURE: dict[ReliefAvailability, float] = {
    "available": 0.00,
    "limited": 0.50,
    "unavailable": 1.00,
    "unknown": 0.25,
}


@dataclass(frozen=True)
class KBORelieverWorkload:
    pitcher_id: str
    pitches_last_24h: int = 0
    pitches_24_to_48h: int = 0
    pitches_48_to_72h: int = 0
    consecutive_days_used: int = 0
    role: RelieverRole = "unknown"
    availability: ReliefAvailability = "unknown"
    availability_confirmed: bool = False


@dataclass(frozen=True)
class KBOBullpenStressInput:
    relievers: tuple[KBORelieverWorkload, ...]
    minimum_expected_relievers: int = 5


@dataclass(frozen=True)
class KBORelieverStress:
    pitcher_id: str
    role: RelieverRole
    role_weight: float
    decayed_pitches: float
    pitch_pressure: float
    streak_pressure: float
    individual_pressure: float
    availability: ReliefAvailability
    availability_pressure: float


@dataclass(frozen=True)
class KBOBullpenStressResult:
    schema_version: str
    stress_index: float
    stress_band: StressBand
    role_weighted_mean_pressure: float
    key_arm_pressure: float
    depth_pressure: float
    availability_pressure: float
    relievers: tuple[KBORelieverStress, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class KBOStressInput:
    travel: KBOTravelStressInput
    bullpen: KBOBullpenStressInput


@dataclass(frozen=True)
class KBOStressResult:
    schema_version: str
    stress_index: float
    stress_band: StressBand
    dominant_component: Literal["travel", "bullpen", "equal"]
    interaction_component: float
    travel_stress_index: float
    bullpen_stress_index: float
    travel: KBOTravelStressResult
    bullpen: KBOBullpenStressResult
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


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


def _validate_reliever(reliever: KBORelieverWorkload) -> None:
    if not reliever.pitcher_id.strip():
        raise ValueError("pitcher_id must be non-empty")
    for name in (
        "pitches_last_24h",
        "pitches_24_to_48h",
        "pitches_48_to_72h",
        "consecutive_days_used",
    ):
        value = getattr(reliever, name)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if reliever.role not in ROLE_WEIGHTS:
        raise ValueError(f"unsupported role: {reliever.role}")
    if reliever.availability not in AVAILABILITY_PRESSURE:
        raise ValueError(f"unsupported availability: {reliever.availability}")


def _pitch_pressure(decayed_pitches: float) -> float:
    """Piecewise dose response around the published 15/20-pitch thresholds."""

    if decayed_pitches <= 10:
        return 0.00
    if decayed_pitches <= 15:
        return 0.15 * (decayed_pitches - 10) / 5
    if decayed_pitches <= 20:
        return 0.15 + 0.30 * (decayed_pitches - 15) / 5
    return _clip(0.45 + 0.55 * (decayed_pitches - 20) / 15)


def _streak_pressure(consecutive_days_used: int) -> float:
    if consecutive_days_used <= 0:
        return 0.00
    if consecutive_days_used == 1:
        return 0.15
    if consecutive_days_used == 2:
        return 0.70
    return 1.00


def _weighted_mean(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def calculate_kbo_bullpen_stress(
    data: KBOBullpenStressInput,
) -> KBOBullpenStressResult:
    """Calculate a 0-100 bullpen workload stress index.

    Recent pitches decay by 50% per 24-hour bucket. Aggregation emphasizes
    leverage arms rather than treating every reliever or pitch as equivalent.
    """

    if data.minimum_expected_relievers < 1:
        raise ValueError("minimum_expected_relievers must be positive")
    if not data.relievers:
        raise ValueError("at least one reliever is required")

    warnings: list[str] = []
    seen: set[str] = set()
    details: list[KBORelieverStress] = []

    for reliever in data.relievers:
        _validate_reliever(reliever)
        if reliever.pitcher_id in seen:
            raise ValueError(f"duplicate pitcher_id: {reliever.pitcher_id}")
        seen.add(reliever.pitcher_id)

        if not reliever.availability_confirmed:
            warnings.append(
                f"RELIEVER_AVAILABILITY_UNCONFIRMED:{reliever.pitcher_id}"
            )

        decayed_pitches = (
            reliever.pitches_last_24h
            + 0.50 * reliever.pitches_24_to_48h
            + 0.25 * reliever.pitches_48_to_72h
        )
        pitch_pressure = _pitch_pressure(decayed_pitches)
        streak_pressure = _streak_pressure(reliever.consecutive_days_used)
        individual_pressure = _clip(
            0.80 * pitch_pressure + 0.20 * streak_pressure
        )
        role_weight = ROLE_WEIGHTS[reliever.role]
        availability_pressure = AVAILABILITY_PRESSURE[reliever.availability]

        details.append(
            KBORelieverStress(
                pitcher_id=reliever.pitcher_id,
                role=reliever.role,
                role_weight=role_weight,
                decayed_pitches=round(decayed_pitches, 2),
                pitch_pressure=round(pitch_pressure, 4),
                streak_pressure=round(streak_pressure, 4),
                individual_pressure=round(individual_pressure, 4),
                availability=reliever.availability,
                availability_pressure=round(availability_pressure, 4),
            )
        )

    if len(details) < data.minimum_expected_relievers:
        warnings.append("LOW_RELIEVER_COVERAGE")

    role_weighted_mean = _weighted_mean(
        [(reliever.individual_pressure, reliever.role_weight) for reliever in details]
    )

    leverage_arms = [
        reliever for reliever in details if reliever.role in ("closer", "setup")
    ]
    if not leverage_arms:
        leverage_arms = sorted(
            details,
            key=lambda item: (item.role_weight, item.pitcher_id),
            reverse=True,
        )[: min(3, len(details))]
        warnings.append("LEVERAGE_ROLES_NOT_IDENTIFIED_USING_TOP_ROLE_WEIGHTS")

    key_arm_pressure = _weighted_mean(
        [(reliever.individual_pressure, reliever.role_weight) for reliever in leverage_arms]
    )
    depth_pressure = sum(
        reliever.individual_pressure >= 0.55 for reliever in details
    ) / len(details)
    availability_pressure = _weighted_mean(
        [(reliever.availability_pressure, reliever.role_weight) for reliever in details]
    )

    # Key arms receive the largest weight. This avoids a raw team pitch total
    # diluting closer/setup workload with low-leverage innings.
    combined_pressure = _clip(
        0.30 * role_weighted_mean
        + 0.45 * key_arm_pressure
        + 0.15 * depth_pressure
        + 0.10 * availability_pressure
    )
    stress_index = round(100.0 * combined_pressure, 1)

    return KBOBullpenStressResult(
        schema_version="doctore.kbo-bullpen-stress.v1",
        stress_index=stress_index,
        stress_band=_stress_band(stress_index),
        role_weighted_mean_pressure=round(role_weighted_mean, 4),
        key_arm_pressure=round(key_arm_pressure, 4),
        depth_pressure=round(depth_pressure, 4),
        availability_pressure=round(availability_pressure, 4),
        relievers=tuple(details),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def calculate_kbo_stress(data: KBOStressInput) -> KBOStressResult:
    """Combine team travel and bullpen burden without diluting either signal.

    The dominant channel is retained in full. Twenty-five percent of the
    secondary channel is added as a compounding interaction and the result is
    capped at 100. Starting-pitcher travel remains a separate feature and may
    not be combined with team bullpen workload.
    """

    if data.travel.scope != "team":
        raise ValueError(
            "composite KBO stress requires team travel scope; "
            "starting-pitcher travel must remain separate"
        )

    travel = calculate_kbo_travel_stress(data.travel)
    bullpen = calculate_kbo_bullpen_stress(data.bullpen)

    dominant = max(travel.stress_index, bullpen.stress_index)
    secondary = min(travel.stress_index, bullpen.stress_index)
    interaction = 0.25 * secondary
    stress_index = round(min(100.0, dominant + interaction), 1)

    if travel.stress_index > bullpen.stress_index:
        dominant_component: Literal["travel", "bullpen", "equal"] = "travel"
    elif bullpen.stress_index > travel.stress_index:
        dominant_component = "bullpen"
    else:
        dominant_component = "equal"

    warnings = tuple(dict.fromkeys((*travel.warnings, *bullpen.warnings)))

    return KBOStressResult(
        schema_version="doctore.kbo-stress-index.v2",
        stress_index=stress_index,
        stress_band=_stress_band(stress_index),
        dominant_component=dominant_component,
        interaction_component=round(interaction, 1),
        travel_stress_index=travel.stress_index,
        bullpen_stress_index=bullpen.stress_index,
        travel=travel,
        bullpen=bullpen,
        warnings=warnings,
    )
