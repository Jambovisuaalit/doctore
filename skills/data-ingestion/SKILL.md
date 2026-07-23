# SKILL: Data Ingestion

> Purpose: Build a timestamped, auditable input package before any probability, EV, or stake decision is made.

## Core principle

Do not analyze a market from prose summaries alone. Convert every source into a structured record with source, retrieval time, source timestamp, and confidence.

## Required ingestion sequence

### 1. Event slate

Collect:

```yaml
event_id: stable internal identifier
sport: string
competition: string
season: string
event_start_at: ISO-8601
home_or_player_a: string
away_or_player_b: string
venue: string | null
status: scheduled | delayed | postponed | started | finished
source: string
retrieved_at: ISO-8601
```

Block pregame analysis when event status is not `scheduled`.

### 2. Market snapshot

For every candidate market collect the complete outcome set from the same book and as close to the same timestamp as possible.

```yaml
market_id: string
book: string
market_type: moneyline | spread | total | prop | 1x2 | asian_handicap
period: full_game | first_half | first_5 | set | other
line: number | null
settlement_rule: string
snapshot_at: ISO-8601
outcomes:
  - selection: string
    odds_decimal: number
    max_stake: number | null
source: string
retrieved_at: ISO-8601
```

Never merge one side from one book with the opposing side from another book for the primary no-vig calculation unless the method is explicitly labeled as a synthetic reference market.

### 3. Model output

Collect the model result as a separate object.

```yaml
model_name: string
model_version: string
target_market: string
selection: string
probability_raw: number
probability_calibrated: number | null
calibration_method: string | null
prediction_generated_at: ISO-8601
feature_cutoff_at: ISO-8601
feature_schema_version: string
training_cutoff_at: ISO-8601
validation_sample_size: integer | null
brier_score: number | null
log_loss: number | null
```

The explanation agent may not derive this object from market prices or narrative factors.

### 4. Sport-specific confirmations

Load the relevant sport skill and collect only fields that can change the validity of the model or market.

Examples:

- MLB: confirmed starters, lineup, bullpen availability, park, roof, weather.
- Tennis: surface, tournament, best-of format, retirement rules, recent workload, injury status.
- Soccer: projected and confirmed lineups, competition motivation, rest, travel, weather.
- NBA: active roster, probable starters, minutes restrictions, rest, back-to-back status.
- NFL: quarterback status, offensive line, weather, travel, rest, market settlement.

### 5. Portfolio state

Collect current risk before sizing:

```yaml
bankroll: number
open_exposure: number
daily_turnover: number
league_exposure: number
rolling_3d_turnover: number
correlated_positions:
  - position_id: string
    relationship: string
    stake: number
as_of: ISO-8601
```

## Source hierarchy

Use primary sources for facts that affect eligibility:

1. Official league, tournament, team, sportsbook, weather, or data-provider feed.
2. Established specialist data source with explicit timestamp.
3. Reputable news or beat source.
4. Aggregator only as a secondary confirmation.
5. Social media only when the identity and timestamp are verifiable.

Do not treat search snippets as final evidence when the underlying page or feed can be read.

## Data normalization

Normalize:

- all odds to decimal;
- all timestamps to ISO-8601 with timezone;
- team and player names to stable IDs;
- markets to controlled vocabulary;
- handicaps from the selected participant's perspective;
- currencies to the bankroll currency;
- statuses to controlled enums.

## Duplicate and conflict handling

When two records describe the same field:

- prefer the more authoritative source;
- prefer the newer source when authority is equal;
- retain both values in the audit record;
- do not silently overwrite a critical conflict;
- return `BLOCKED` when the conflict changes eligibility or probability validity.

## Freshness and refresh triggers

Refresh immediately when:

- price age exceeds the configured threshold;
- a starting player changes;
- lineup status changes;
- weather crosses a sport-specific threshold;
- a market line changes;
- event start time changes;
- model inputs have changed since prediction generation;
- portfolio exposure has changed.

## Output package

```text
INGESTION STATUS: COMPLETE | DEGRADED | BLOCKED
Event record: [structured summary]
Market record: [structured summary]
Model record: [structured summary]
Sport confirmations: [structured summary]
Portfolio state: [structured summary]
Sources and timestamps: [list]
Conflicts: [none or list]
Refresh required: YES | NO
```

Only `COMPLETE` and permitted `DEGRADED` packages may proceed to the data quality gate.