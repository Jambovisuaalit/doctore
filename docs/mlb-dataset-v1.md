# Canonical MLB dataset v1

## Domain

```text
sport: MLB
competition: MLB
market_type: total
target_market: full_game_total
period: full_game
settlement: full game including extra innings
```

The first dataset is deliberately a **market-baseline research dataset**, not a
production feature set. Its model features are limited to:

- full-game total line;
- two-sided no-vig Over probability;
- market overround.

The final total is the target only. Current-game runs, hits, RBI, pitcher lines
or other settled box-score fields are forbidden as features.

## Source contracts

### Legacy team-level odds

```csv
date,at,team,gameNumber,line,runLine,runLineOdds,total,overOdds,underOdds
```

`at` must be `V` or `H`. Odds are joined only after a result game establishes the
full event identity. A date-and-team-only join is forbidden.

### One-row-per-game results

```csv
source_game_id,game_date,game_number,away_team,home_team,away_runs,home_runs,event_start_at,status
```

Accepted results are official final/completed games. `source_game_id` must be
stable and unique. Doubleheaders are separated by `game_number`.

## Join identity

```text
(game_date, game_number, away_team, home_team)
```

The builder performs two exact lookups:

```text
(game_date, away_team, game_number, V)
(game_date, home_team, game_number, H)
```

Missing sides, contradictory totals or contradictory total prices are rejected.
There is no fuzzy correction.

## Timestamp policy

The historical source contains closing prices but not the exact capture time.
The builder therefore emits a deterministic pre-start proxy and records it as:

```text
market_timestamp_method = derived_closing_proxy_t_minus_<seconds>s
research_only = true
production_eligible = false
```

This proxy is suitable for content-addressed research reconstruction, not for
claiming exact executable timing or live bankroll readiness.

Games sharing the same cutoff retain the same timestamp and `slate_id`. They
must be evaluated by a timestamp-grouped walk-forward splitter. Fabricating
microsecond ordering is forbidden because it can leak one same-slate outcome
into another game's training history.

## Build

```bash
python scripts/build_mlb_dataset_v1.py \
  --odds data/raw/oddsDataMLB.csv \
  --results data/raw/mlb-results.csv \
  --output-dir artifacts/datasets/mlb-full-game-totals-v1.0.0 \
  --dataset-version 1.0.0 \
  --close-proxy-seconds 60
```

The output directory is create-only:

```text
mlb_full_game_totals_v1.csv
training-dataset-manifest.json
source-manifest.json
build-report.json
rejected_rows.csv
```

## Lock gates

A manifest is written only when at least one row passes. The manifest locks:

- exact CSV SHA-256;
- exact header order;
- row count;
- feature schema;
- target and market columns;
- timestamp grouping semantics;
- source-manifest filename.

A locked dataset is not automatically validated. This v1 baseline remains
research-only until exact market capture timestamps and timestamp-grouped OOS
model validation are demonstrated.

## Attribution

When Retrosheet game logs are used, preserve the Retrosheet attribution and
usage notice in the source manifest and any published artifact derived from the
data.
