# Doctore Data Quality Gate

Every candidate must pass this gate before edge calculation. The gate prevents unsupported probabilities, stale prices, mismatched events, and incomplete markets from reaching the execution layer.

## Statuses

| Status | Meaning | Action |
|---|---|---|
| `VALID` | Required fields are present, current, and internally consistent. | Continue. |
| `DEGRADED` | Non-critical context is missing, but core EV calculation remains valid. | Continue with reduced confidence and stricter sizing. |
| `BLOCKED` | A critical field is missing, stale, contradictory, or unverified. | Do not recommend a bet. |

## Critical fields

```yaml
event_id: required
sport: required
competition: required
event_start_at: required ISO-8601
market_id: required
market_type: required
selection: required
book: required
odds_decimal: required and > 1.0
market_snapshot_at: required ISO-8601
opposing_outcomes: complete outcome set required
model_probability: required, 0 < p < 1
model_version: required
model_generated_at: required ISO-8601
calibration_status: required
```

## Freshness rules

Default pregame limits:

| Data | Maximum age | Failure state |
|---|---:|---|
| Executable price | 5 minutes | `BLOCKED` |
| Model probability | Defined by model contract; default 30 minutes | `BLOCKED` |
| Confirmed lineup or starter | Sport-specific | `BLOCKED` when required |
| Injury status | 3 hours; shorter near start | `DEGRADED` or `BLOCKED` |
| Weather | 3 hours; refresh within 60 minutes outdoors | `DEGRADED` or `BLOCKED` |
| Portfolio exposure | Real-time | `BLOCKED` |

If a source supplies its own timestamp, use the source timestamp rather than retrieval time.

## Identity checks

Confirm that all records refer to the same:

- event and scheduled start;
- competition and season;
- home/away or player orientation;
- market type and period;
- handicap or total line;
- settlement rules;
- sportsbook and currency.

A full-game market must not be compared with a first-half, first-five-innings, set, map, or regulation-only model output.

## Market completeness

No-vig calculation requires the complete mutually exclusive outcome set.

Examples:

- Two-way moneyline: both sides.
- Soccer 1X2: home, draw, away.
- Total: over and under at the same line.
- Spread: both sides at complementary handicaps.

If one outcome is missing or comes from a materially different timestamp, mark `BLOCKED` unless a documented reference-market method is used.

## Model provenance checks

The probability is valid only when all are present:

- model name and version;
- prediction generation timestamp;
- target definition matching the market;
- calibration method or explicit uncalibrated status;
- feature cutoff timestamp;
- no known leakage from data unavailable at decision time.

A probability typed manually without provenance is `BLOCKED`.

## Contradiction checks

Return `BLOCKED` when:

- event start times differ materially across sources;
- the named starter, goalie, lineup, or player status conflicts across authoritative sources;
- model target does not match sportsbook settlement rules;
- model probability and selected side are reversed;
- odds are malformed or imply an impossible market;
- the event has already started for a pregame recommendation;
- current open exposure cannot be determined.

## Degraded context

The following may produce `DEGRADED` rather than `BLOCKED` when they are not model-critical:

- public betting percentages unavailable;
- opening line unavailable;
- minor player status not represented in the model;
- secondary weather details unavailable for an indoor event;
- one non-primary contextual source unavailable.

`DEGRADED` candidates must use the lower allowed Kelly fraction and must state what is missing.

## Required gate output

```text
DATA QUALITY: VALID | DEGRADED | BLOCKED
Decision timestamp: [ISO-8601]
Market age: [seconds]
Model age: [seconds]
Identity match: YES | NO
Complete outcome set: YES | NO
Critical confirmations: [list]
Conflicts: [none or list]
Missing context: [none or list]
Next action: CONTINUE | REFRESH | RESOLVE | PASS
```