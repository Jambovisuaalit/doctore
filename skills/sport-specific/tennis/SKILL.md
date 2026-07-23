# SKILL: Tennis

> Purpose: Validate tennis-specific model assumptions, player identity, surface, format, availability, and settlement rules before approving match, set, game, total, handicap, or prop candidates.

## Supported market families

- Match winner.
- Set handicap and game handicap.
- Match totals and set totals.
- Correct score only with a dedicated distribution model.
- Player props only with a dedicated prop probability.

Do not infer handicap, total, or correct-score probabilities from match-winner probability alone.

## Critical confirmations

```yaml
player_a: stable player ID
player_b: stable player ID
tournament: string
round: string
surface: hard | clay | grass | indoor_hard | other
format: best_of_3 | best_of_5
venue: string
scheduled_start_at: ISO-8601
retirement_rule: book-specific settlement
walkover_rule: book-specific settlement
player_status_a: active and verified
player_status_b: active and verified
prediction_generated_at: ISO-8601
```

Block when player identity, opponent, surface, format, or settlement rule does not match the model target.

## Model input audit

Preferred features include:

- surface-adjusted serve and return performance;
- opponent-adjusted hold and break rates;
- point-level or game-level strength estimates;
- recent workload and match duration;
- travel and time-zone effects where validated;
- injury and retirement history with appropriate shrinkage;
- handedness and matchup interaction where validated;
- indoor/outdoor conditions;
- tournament level and ball/altitude effects when modeled.

Do not use head-to-head record as a primary feature without controlling for age, surface, era, and sample size.

## Availability and injury validation

Tennis injury information is often incomplete. Distinguish:

- officially withdrawn or walkover;
- verified medical timeout or retirement in a recent match;
- credible current report;
- speculative social-media claim;
- no evidence.

A credible injury change after model generation can make the prediction stale. Do not manually subtract probability without a validated injury model.

## Workload checks

Verify when relevant:

- previous match end time;
- match duration and sets played;
- consecutive-day matches;
- doubles participation;
- travel between tournaments;
- qualifying rounds before the main draw.

Workload may invalidate a model that used an earlier schedule snapshot.

## Market-specific checks

### Match winner

- Confirm retirement settlement rules.
- Confirm best-of format.
- Confirm surface and venue.
- Check whether either player has withdrawn or changed status.

### Game or set handicap

- Match exact line and sign.
- Confirm push rules.
- Require a score or game distribution model.
- Do not convert match-winner edge directly into handicap edge.

### Totals

- Match exact total and format.
- Require a set/game distribution model.
- Account for retirement settlement rules.

### Live or in-play

Pregame probabilities are not valid after the match begins. Live markets require a live state model with current score, server, point state, and timestamp.

## Red flags

Return `BLOCKED` or `WATCH` when:

- the match has started for a pregame analysis;
- opponent or draw position changed;
- surface or venue classification is wrong;
- player status is uncertain after credible injury news;
- model prediction predates a long or late previous match;
- the sportsbook retirement rule differs from the model/backtest assumption;
- market liquidity is too low for the displayed price to be executable;
- the model is outside its ATP, WTA, Challenger, ITF, junior, or exhibition domain.

## Required tennis validation output

```text
TENNIS VALIDATION
Players and event match: YES | NO
Surface: [surface] — match: YES | NO
Format: [format] — match: YES | NO
Match started: YES | NO
Player availability: VERIFIED | UNCERTAIN | BLOCKED
Recent workload current: YES | NO | NOT MODELED
Retirement rule match: YES | NO
Market target match: YES | NO
Material changes since prediction: [none or list]
Decision: VALID | DEGRADED | BLOCKED
```