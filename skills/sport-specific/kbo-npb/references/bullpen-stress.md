# KBO bullpen-stress policy v1

## Status

`doctore.kbo-bullpen-stress.v1` is a transparent research prior. The KBO
composite `doctore.kbo-stress-index.v2` combines this component with team travel
stress. Neither index may directly negotiate or overwrite model probability,
EV, edge, or Kelly.

The workload coefficients are not validated KBO performance effects. The raw
inputs are available from official KBO box scores, which publish pitcher-level
batters faced and pitch counts. The dose-response thresholds and recovery decay
are adapted from published reliever-fatigue research and must be validated on
KBO data before production use.

Sources:

- Official KBO box score with pitcher pitch counts:
  https://www.koreabaseball.com/Futures/Schedule/BoxScore.aspx
- Greenhouse, Z. et al., *Out of gas: quantifying fatigue in MLB relievers*:
  https://doi.org/10.1515/jqas-2018-0007

## Required reliever inputs

For every projected bullpen arm:

```text
pitcher_id
role: closer | setup | middle | long | unknown
pitches_last_24h
pitches_24_to_48h
pitches_48_to_72h
consecutive_days_used
availability: available | limited | unavailable | unknown
availability_confirmed
```

Do not replace pitcher-level records with one raw bullpen pitch total. Thirty
pitches from a closer or primary setup arm are not equivalent to thirty pitches
from a low-leverage long reliever.

## Per-reliever calculation

Recent workload uses a 24-hour half-life:

```text
decayed_pitches =
    pitches_last_24h
    + 0.50 × pitches_24_to_48h
    + 0.25 × pitches_48_to_72h
```

Pitch pressure is piecewise:

| Decayed pitches | Pressure |
|---:|---:|
| `0–10` | `0.00` |
| `10–15` | linearly `0.00 → 0.15` |
| `15–20` | linearly `0.15 → 0.45` |
| `20–35` | linearly `0.45 → 1.00` |
| `>=35` | `1.00` |

The 15- and 20-pitch inflection points reflect the published reliever-fatigue
finding. The saturation point at 35 decayed pitches is a Doctore research prior,
not a published KBO threshold.

Consecutive-day pressure:

| Consecutive days used | Pressure |
|---:|---:|
| `0` | `0.00` |
| `1` | `0.15` |
| `2` | `0.70` |
| `>=3` | `1.00` |

```text
individual_pressure =
    0.80 × pitch_pressure
    + 0.20 × streak_pressure
```

## Role and availability weights

| Role | Weight |
|---|---:|
| closer | `1.35` |
| setup | `1.20` |
| middle | `1.00` |
| long | `0.80` |
| unknown | `1.00` |

| Availability | Pressure |
|---|---:|
| available | `0.00` |
| limited | `0.50` |
| unavailable | `1.00` |
| unknown | `0.25` |

Unknown or unconfirmed availability must emit a warning. It must not be silently
converted into confirmed availability during historical backfill.

## Bullpen aggregation

```text
bullpen_pressure =
    0.30 × role_weighted_mean_pressure
    + 0.45 × key_arm_pressure
    + 0.15 × depth_pressure
    + 0.10 × availability_pressure

bullpen_stress_index = 100 × clip(bullpen_pressure, 0, 1)
```

Definitions:

- `role_weighted_mean_pressure`: workload across the projected bullpen;
- `key_arm_pressure`: closer and setup workload, or a warned fallback when roles
  are unavailable;
- `depth_pressure`: share of relievers with `individual_pressure >= 0.55`;
- `availability_pressure`: role-weighted limited/unavailable burden.

## Combined KBO Stress Index v2

The previous travel index remains available unchanged. The team-level composite
uses:

```text
dominant = max(team_travel_stress, bullpen_stress)
secondary = min(team_travel_stress, bullpen_stress)

stress_index = clip(
    dominant + 0.25 × secondary,
    0,
    100
)
```

This design does not dilute the dominant signal. The secondary component adds a
limited interaction for the case where a fatigued bullpen also arrives under
material travel stress.

Starting-pitcher travel is not eligible for this composite:

```text
team_travel_stress + bullpen_stress → team operational stress
starting_pitcher_travel_stress      → separate feature
```

A starter who travelled early by KTX cannot reduce the bullpen or lineup travel
burden.

## Market boundary

Bullpen stress is primarily applicable to:

- full-game totals;
- full-game moneyline;
- full-game run line.

It must not be applied unchanged to first-five markets. A first-five model may
retain starter travel and starter context, but bullpen stress should be excluded
unless the target explicitly includes relief innings.

## Point-in-time and leakage rules

- Include only appearances with `game_end_at < feature_cutoff_at`.
- Exclude the current event ID.
- A doubleheader Game 1 workload may enter Game 2 only if Game 1 finished before
  the Game 2 feature cutoff.
- Use the roster, role and availability state known at the cutoff.
- Never use final postgame availability or retrospective role labels.
- Preserve every source timestamp and raw pitcher-game record.

## Required ablation

```text
M0: current KBO model
M1: M0 + transparent travel primitives
M2: M1 + transparent bullpen primitives
M3: M0 + travel_stress_index
M4: M0 + bullpen_stress_index
M5: M0 + combined stress_index v2
R1–R20: matching synthetic random controls
```

Retain the combined index only when it improves unchanged chronological OOS
Brier or log loss by at least 1% relative, remains non-inferior in three
consecutive windows, beats random-feature controls and does not degrade
calibration. Full-game totals, moneyline and run line must be evaluated as
separate validation domains.
