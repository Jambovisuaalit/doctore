# SKILL: MLB

> Purpose: Validate MLB model inputs, market matching, and event-specific assumptions before approving moneyline, run line, total, first-five, or prop candidates.

## Supported market families

- Full-game moneyline.
- Run line and alternative run lines.
- Full-game totals.
- First five innings moneyline, spread, and total.
- Team totals.
- Player props only when a dedicated prop model supplies probability.

Each market requires its own target definition. Do not transfer a full-game probability to a first-five market.

## Critical pregame confirmations

Block the candidate when a model-critical field is missing or changed:

```yaml
starting_pitcher_away: confirmed identity
starting_pitcher_home: confirmed identity
lineup_away: confirmed or model-compatible projected lineup
lineup_home: confirmed or model-compatible projected lineup
park: confirmed
roof_status: confirmed when relevant
weather_snapshot_at: ISO-8601 for outdoor games
bullpen_state_cutoff_at: ISO-8601
market_period: full_game | first_5 | other
listed_pitcher_rule: action | listed | book-specific
```

## Model input audit

Preferred pitcher features include:

- projected innings or batters faced;
- handedness;
- strikeout and walk skill;
- contact quality;
- pitch mix and velocity trend;
- platoon performance with shrinkage;
- park and opponent adjustment;
- rest and recent workload;
- injury or pitch-count limitation.

Preferred offense features include:

- projected lineup rather than season team average alone;
- handedness-specific quality;
- strikeout, walk, power, and batted-ball profile;
- park and weather interaction;
- catcher and defensive effects only when validated.

Preferred bullpen features include:

- projected reliever availability;
- recent pitch counts and consecutive-day usage;
- quality by leverage role;
- roster transactions;
- extra-inning or doubleheader context.

Do not manually add fixed run adjustments unless they are part of a validated model or a documented scenario model.

## Weather and park validation

For outdoor games verify:

- temperature;
- wind speed and direction relative to stadium orientation;
- precipitation and delay risk;
- humidity or air density when used by the model;
- roof status;
- measurement timestamp.

Weather context can invalidate a stale model prediction. It must not be converted into an improvised probability by the explanation layer.

## Market-specific checks

### Moneyline

- Confirm extra innings are included.
- Confirm listed-pitcher rules.
- Confirm both starter and bullpen assumptions.
- Evaluate correlation with run line and team totals.

### Run line

- Match the exact handicap and participant orientation.
- Confirm push rules for integer alternatives.
- Do not derive run-line probability from moneyline without a run-distribution model.

### Total

- Match the exact total line.
- Confirm weather, park, umpire usage if modeled, lineups, starters, and bullpens.
- Do not compare model probability for 8.0 with market 8.5.

### First five innings

- Confirm settlement period and tie/push treatment.
- Remove bullpen assumptions unless the model explicitly includes opener/bulk usage.
- Block opener or uncertain pitching plans unless modeled.

## Red flags

Return `BLOCKED` or `WATCH` when:

- a starter changes after prediction generation;
- confirmed lineup materially differs from model lineup;
- weather or roof state changes beyond model tolerance;
- bullpen availability is stale for a full-game market;
- the event is a doubleheader and game identity is ambiguous;
- the sportsbook market uses different listed-pitcher rules;
- the model is outside the league, season phase, or park domain it was validated on.

## Required MLB validation output

```text
MLB VALIDATION
Starters confirmed: YES | NO
Lineups compatible: YES | NO | PROJECTED
Pitch-count restrictions: [none or list]
Bullpen state current: YES | NO | NOT REQUIRED
Weather/roof current: YES | NO | INDOOR
Market-period match: YES | NO
Listed-pitcher rule match: YES | NO
Material model-input changes: [none or list]
Correlation flags: [none or list]
Decision: VALID | DEGRADED | BLOCKED
```