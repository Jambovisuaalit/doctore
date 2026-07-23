# SKILL: NBA and WNBA

> Purpose: Validate roster status, minutes assumptions, schedule, market definition, and model freshness before approving basketball moneyline, spread, total, team-total, or player-prop candidates.

## Supported domains

- NBA regular season and playoffs when covered by the model.
- WNBA regular season and playoffs when covered by the model.
- Preseason only with a separately validated preseason model.
- Player props only with a dedicated minutes and usage model.

Do not apply NBA calibration to WNBA, preseason, Summer League, G League, or international basketball without explicit validation.

## Critical confirmations

```yaml
league: NBA | WNBA
season_phase: preseason | regular | playoffs
home_team: stable ID
away_team: stable ID
event_start_at: ISO-8601
active_roster_snapshot_at: ISO-8601
projected_starters_at: ISO-8601
injury_report_at: ISO-8601
rest_days_home: integer
rest_days_away: integer
back_to_back_home: boolean
back_to_back_away: boolean
market_includes_overtime: boolean
```

## Model input audit

Preferred team-market features include:

- possession-adjusted offensive and defensive strength;
- expected active roster and starters;
- projected minutes and rotation depth;
- on/off or lineup effects with shrinkage;
- pace and shot-profile interactions;
- rest, travel, altitude, and back-to-back effects;
- garbage-time handling;
- season phase and playoff rotation changes;
- market data only when declared in the model contract.

For player props, require:

- projected minutes;
- starting/bench role;
- usage and opportunity distribution;
- teammate availability;
- opponent matchup variables validated for the prop;
- overtime treatment;
- sportsbook stat and void rules.

The explanation layer must not convert an injury report directly into an arbitrary spread adjustment.

## Injury and minutes validation

Player labels such as questionable, probable, or available are insufficient alone. Verify:

- expected active status;
- likely starting role;
- minutes restriction;
- return from injury;
- rotation change caused by another absence;
- late rest or load-management risk.

If a model-critical player's status changes after prediction generation, refresh or block the candidate.

## Schedule validation

Check:

- back-to-back and three-in-four status;
- travel and time-zone changes;
- altitude where modeled;
- previous game overtime;
- playoff series state;
- preseason rotation uncertainty.

Schedule context can make an existing model output stale. It does not independently create probability.

## Market-specific checks

### Moneyline

- Confirm overtime inclusion.
- Confirm roster state.
- Aggregate correlation with spread and team-total positions.

### Spread

- Match exact line and participant orientation.
- Confirm push treatment on integer lines.
- Require a margin-distribution or direct spread model.

### Total

- Match exact total.
- Confirm pace, roster, and overtime assumptions.
- Require a total or score-distribution model.

### Player props

- Require current minutes and role projections.
- Match exact stat definition and line.
- Block when the player is not confirmed active near event start.
- Aggregate correlation with team and game markets.

## Red flags

Return `BLOCKED` or `WATCH` when:

- a star or high-minute player changes status after prediction generation;
- minutes restrictions are unknown;
- projected starters differ materially;
- the market is preseason but the model is regular-season only;
- a prop model lacks current teammate availability;
- event start or overtime rules are mismatched;
- the displayed price is stale during rapid injury repricing;
- WNBA predictions use NBA calibration or vice versa.

## Required basketball validation output

```text
BASKETBALL VALIDATION
League/domain match: YES | NO
Season phase match: YES | NO
Active roster current: YES | NO
Projected starters current: YES | NO
Minutes restrictions resolved: YES | NO | NOT APPLICABLE
Rest/travel state current: YES | NO
Overtime settlement match: YES | NO
Material changes since prediction: [none or list]
Correlation flags: [none or list]
Decision: VALID | DEGRADED | BLOCKED
```