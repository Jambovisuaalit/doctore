# SKILL: KBO and NPB

> Purpose: Validate KBO and NPB-specific data coverage, starting pitchers, lineups, bullpen state, venue conditions, league rules, and market mapping before approving baseball candidates.

## Domain separation

Treat KBO and NPB as separate model domains.

Do not reuse MLB calibration, park effects, run environment, bullpen assumptions, roster rules, or market priors without explicit validation. Do not pool KBO and NPB performance under a generic baseball result when evaluating model quality.

## Supported market families

- Full-game moneyline.
- Run line and Asian run handicap.
- Full-game totals.
- First-five or first-half markets when explicitly modeled.
- Team totals.

## Critical confirmations

```yaml
league: KBO | NPB
season: string
home_team: stable ID
away_team: stable ID
event_start_at: ISO-8601
starting_pitcher_home: confirmed identity
starting_pitcher_away: confirmed identity
lineup_home_at: ISO-8601 | null
lineup_away_at: ISO-8601 | null
venue: string
roof_status: string | null
weather_snapshot_at: ISO-8601 | null
bullpen_state_cutoff_at: ISO-8601
foreign_player_status: current
market_period: full_game | first_5 | other
settlement_rule: book-specific
```

## Model input audit

Preferred features include:

- league-specific run environment;
- pitcher quality using league-appropriate metrics and translations;
- handedness and lineup composition;
- foreign-player roster and availability;
- bullpen quality and recent workload;
- park and roof effects;
- travel, rest, doubleheaders, and makeup games;
- tie rules and extra-inning limits;
- league-specific ball, schedule, and roster changes;
- data-source completeness by season.

Historical stats from translated or unofficial sources must preserve player identity and season context.

## League-rule validation

Verify the current competition and sportsbook settlement rules for:

- ties;
- extra-inning limits;
- suspended games;
- shortened games;
- listed pitchers;
- doubleheaders;
- playoff rules.

A model trained under one ruleset may be stale after a league rule change.

## Starting pitcher and lineup validation

Block when:

- announced starter differs from model input;
- transliterated player identity is ambiguous;
- a foreign starter or hitter changes status;
- lineup data is missing when the model is lineup-dependent;
- opener or bullpen-game usage is not represented.

Do not manually translate an MLB performance line into KBO or NPB probability without a validated league-translation model.

## Data-source quality

Record:

- original source language;
- translation or transliteration layer;
- stable player and team IDs;
- source timestamp;
- whether the source is official, specialist, or aggregator;
- missing-stat and delayed-update behavior.

Conflicting translated names are an identity risk and may require `BLOCKED` status.

## Market-specific checks

### Moneyline

- Confirm tie and extra-inning treatment.
- Confirm starters and bullpen assumptions.

### Run handicap

- Match exact Asian or standard line.
- Confirm settlement for ties and pushes.
- Require a run-distribution or direct handicap model.

### Total

- Match exact line and game period.
- Confirm run environment, starters, lineups, park, roof, weather, and bullpen freshness.

### First segment

- Match first-five or local-book period definition exactly.
- Remove bullpen assumptions only when the target truly excludes them.

## Red flags

Return `BLOCKED` or `WATCH` when:

- league/domain mapping is wrong;
- starter identity is uncertain;
- local-language sources conflict materially;
- current tie or extra-inning rules are not represented;
- foreign-player availability changed;
- weather or roof state changed beyond tolerance;
- market period differs from model target;
- the model was calibrated on MLB or the other Asian league without validation.

## Required KBO/NPB validation output

```text
KBO/NPB VALIDATION
League/domain match: YES | NO
Event and team identities: YES | NO
Starting pitchers confirmed: YES | NO
Lineups compatible: YES | NO | PROJECTED
Foreign-player status current: YES | NO | NOT MATERIAL
Bullpen state current: YES | NO | NOT REQUIRED
Weather/roof current: YES | NO | INDOOR
League and settlement rules match: YES | NO
Translation/identity conflicts: [none or list]
Material changes since prediction: [none or list]
Decision: VALID | DEGRADED | BLOCKED
```