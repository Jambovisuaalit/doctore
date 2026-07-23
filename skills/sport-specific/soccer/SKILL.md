# SKILL: Soccer

> Purpose: Validate soccer event identity, lineups, competition context, market definition, and model freshness before approving 1X2, Asian handicap, totals, BTTS, team totals, or prop candidates.

## Supported market families

- 1X2.
- Draw-no-bet and double chance with dedicated probability mapping.
- Asian handicap.
- Match totals.
- Both teams to score.
- Team totals.
- Player props only with a dedicated player model.

Do not derive Asian handicap, totals, or BTTS probabilities from a 1X2 probability without a score-distribution model.

## Critical confirmations

```yaml
competition: string
season: string
home_team: stable team ID
away_team: stable team ID
venue: string
event_start_at: ISO-8601
competition_format: league | cup | two_leg | playoff | friendly
leg_state: first_leg | second_leg | not_applicable
extra_time_in_market: boolean
penalties_in_market: boolean
projected_lineups_at: ISO-8601 | null
confirmed_lineups_at: ISO-8601 | null
```

Block when the market's regulation, extra-time, or qualification settlement differs from the model target.

## Model input audit

Preferred team-strength inputs include:

- non-penalty expected goals for and against;
- shot and chance quality;
- opponent and league adjustment;
- home advantage estimated by competition and era;
- expected lineup quality;
- goalkeeper impact where validated;
- rest, travel, congestion, and rotation;
- score-state and red-card treatment in historical features;
- promoted/relegated team priors;
- market information only when explicitly part of the model contract.

Avoid overweighting raw recent results, possession, or head-to-head records without context.

## Lineup validation

Before confirmed lineups:

- compare the model's expected lineup with current availability;
- identify players whose absence materially changes model inputs;
- use `WATCH` when the edge depends on uncertain starters.

After confirmed lineups:

- verify formation and key roles where modeled;
- refresh or block the prediction when material differences exceed model tolerance;
- do not manually add or subtract arbitrary probability points.

## Competition context

Verify:

- league versus cup incentives;
- first-leg versus second-leg state;
- aggregate score;
- qualification and relegation context if modeled;
- rotation likelihood;
- neutral venue;
- schedule congestion;
- travel and weather;
- friendly or exhibition status.

Narrative motivation must not create a bet unless represented in a validated model or used only as a reason to block stale assumptions.

## Market-specific checks

### 1X2

- Require all three outcome prices for no-vig calculation.
- Match regulation-time settlement.
- Report draw probability separately.

### Asian handicap

- Match exact quarter-, half-, or whole-goal line.
- Use correct split-stake settlement for quarter lines.
- Require a goal-distribution model or direct market model.

### Totals

- Match exact line and regulation period.
- Require a score-distribution or direct total model.
- Account for weather and lineups if model-critical.

### BTTS

- Require a joint scoring model.
- Do not approximate from separate team win probabilities.

## Red flags

Return `BLOCKED` or `WATCH` when:

- lineups materially changed after prediction generation;
- competition or leg state is wrong;
- neutral venue is not represented;
- regulation and qualification markets are confused;
- major goalkeeper or striker uncertainty is model-critical;
- promoted team or early-season domain is outside validation;
- the event is a friendly or youth match outside the trained domain;
- market liquidity or limits make the displayed price non-executable.

## Required soccer validation output

```text
SOCCER VALIDATION
Competition and event match: YES | NO
Market settlement match: YES | NO
Venue state: HOME | NEUTRAL | UNKNOWN
Lineup state: PROJECTED | CONFIRMED | MATERIAL CHANGE
Key availability current: YES | NO
Rest/travel context current: YES | NO | NOT MODELED
Cup/leg state represented: YES | NO | NOT APPLICABLE
Model domain match: YES | NO
Material changes since prediction: [none or list]
Decision: VALID | DEGRADED | BLOCKED
```