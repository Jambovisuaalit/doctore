# KBO travel-stress policy v1

## Status

`doctore.kbo-travel-stress.v1` is a transparent research prior. It is not a
causal estimate and must not directly negotiate or overwrite model probability,
EV, edge, or Kelly. Retain it as a model feature only after locked chronological
ablation testing.

## KBO-specific assumptions

- All domestic KBO venues use `Asia/Seoul`; timezone and east/west circadian
  terms are fixed at zero.
- KBO scheduling is concentrated into short domestic routes and normally uses
  three-game series. KBO also states that travel distance is considered in
  schedule construction.
- The default team transport prior is a club bus, not KTX.
- KTX relief is applied only when the actual transport and traveler scope are
  confirmed. A starting pitcher traveling early by KTX does not change the
  team-level travel feature.
- Door-to-door travel time is the primary primitive. Kilometres are retained
  for audit and route estimation, but are not scored directly.

Sources:

- KBO 2026 schedule release: https://www.koreabaseball.com/MediaNews/Notice/View.aspx?bdSe=11794
- KBO team movement description: https://www.knnews.co.kr/news/articleView.php?idxno=1153518
- Lotte team bus reporting: https://www.kookje.co.kr/news2011/asp/newsbody.asp?code=0600&key=20240423.99099006685
- KORAIL timetables: https://www.korail.go.kr/ticket/reserve/train-timeTable

## Mode multipliers

| Mode | Multiplier | Rule |
|---|---:|---|
| `same_venue` | `0.00` | No travel burden |
| `local_bus` | `0.45` | Same metro / short local transfer |
| `team_bus` | `1.00` | KBO team-level default |
| `ktx` | `0.70` | Confirmed KTX traveler only |
| `mixed_bus_ktx` | `0.80` | Bus transfers plus KTX |
| `domestic_flight` | `0.85` | Includes airport and transfer friction |
| `unknown` | `1.00` | Conservative bus prior plus warning |

The KTX coefficient is intentionally not based only on line-haul speed. It
allows for station transfers, baggage, team logistics and last-mile bus travel.
It is a prior to test, not a measured KBO performance coefficient.

## Formula

```text
effective_travel_hours = door_to_door_hours × mode_multiplier

route_load = clip(
  (effective_travel_hours - 0.75) / 4.25,
  0,
  1
)

residual_route_load = route_load × 2 ^ (-hours_since_arrival / 24)

amplifier =
  0.65
  + 0.20 × recovery_pressure
  + 0.10 × late_arrival_pressure
  + 0.05 × trip_chain_pressure

stress_index = 100 × clip(residual_route_load × amplifier, 0, 1)
```

### Recovery pressure

| Hours since previous game end | Pressure |
|---:|---:|
| `>= 42` | `0.00` |
| `36–42` | `0.10` |
| `30–36` | `0.25` |
| `24–30` | `0.45` |
| `18–24` | `0.70` |
| `< 18` | `1.00` |

Add `0.15`, capped at `1.00`, when the previous game went to extra innings.

### Late-arrival pressure

| Local arrival time | Pressure |
|---|---:|
| `06:00–21:59` | `0.00` |
| `22:00–22:59` | `0.30` |
| `23:00–23:59` | `0.60` |
| `00:00–01:59` | `0.80` |
| `02:00–05:59` | `1.00` |

### Road-trip chain

```text
trip_chain_pressure = clip((consecutive_away_series - 1) / 3, 0, 1)
```

## Interpretation

| Index | Band | Operational meaning |
|---:|---|---|
| `0–9.9` | `NEGLIGIBLE` | No material travel burden |
| `10–24.9` | `LOW` | Track as context only |
| `25–44.9` | `MODERATE` | Material model feature; no automatic gate |
| `45–64.9` | `HIGH` | Context `WATCH` candidate if other fatigue signals agree |
| `65–100` | `SEVERE` | Require source review; never alter probability manually |

Travel stress alone is not a hard blocker. A missing or contradictory itinerary
may be a data-quality blocker when the production model requires this feature.

## Scope separation

Calculate separately when evidence supports it:

```text
team_travel_stress
starting_pitcher_travel_stress
```

Example:

```text
team: Busan → Seoul by club bus
starter: Busan → Seoul earlier by KTX
```

The starter may receive the KTX coefficient. The lineup and bullpen retain the
team-bus coefficient. Do not average these into one undocumented score.

## Point-in-time rules

- Use the latest completed prior game with `completed_at < feature_cutoff_at`.
- Use only itinerary information observed by `feature_cutoff_at`.
- Do not treat a postponed game as completed travel.
- Do not infer KTX from route availability.
- Unknown transport is `unknown`, scored as the bus prior, with a warning.
- Preserve route, mode, confirmation source and timestamps in the feature row.

## Required ablation

```text
M0: current KBO model
M1: M0 + transparent travel primitives
M2: M0 + composite stress_index
R1–R20: M0 + synthetic random control feature
```

Retain the composite only if it improves unchanged chronological OOS Brier or
log loss by at least 1% relative, remains non-inferior in three consecutive
windows, beats random-feature controls and does not degrade calibration.
