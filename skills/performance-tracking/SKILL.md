# SKILL: Performance Tracking

> Purpose: Determine whether Doctore is producing real, repeatable edge after accounting for price, calibration, model version, execution, and variance.

## Core principle

Win rate and profit alone are insufficient. Track every decision from prediction through closing price and settlement.

## Required bet record

```yaml
bet_id: string
event_id: string
decision_at: ISO-8601
event_start_at: ISO-8601
sport: string
competition: string
market_id: string
market_type: string
period: string
selection: string
line: number | null
book: string
odds_taken_decimal: number
stake: number
units: number
bankroll_before: number
model_name: string
model_version: string
model_probability: number
sizing_probability: number
market_no_vig_probability: number
break_even_probability: number
expected_ev: number
edge_vs_market_pp: number
data_quality_status: VALID | DEGRADED
candidate_tier: A | B | C
kelly_full: number
kelly_fraction_used: number
price_threshold: number
correlation_group: string | null
closing_odds_decimal: number | null
closing_market_no_vig_probability: number | null
result: WIN | LOSS | PUSH | VOID | OPEN
profit_loss: number | null
notes: string | null
```

Also log `PASS`, `WATCH`, and `BLOCKED` decisions in a separate decision table. This is required to detect selection bias and measure missed or prevented exposure.

## Closing line value

Do not subtract American odds or decimal odds directly as the primary CLV measure.

### Implied-probability CLV

```text
implied_taken = 1 / odds_taken
implied_close = 1 / closing_odds
raw_clv_pp = implied_close - implied_taken
```

Positive value means the taken price had a lower break-even probability than the closing price.

### No-vig CLV

Preferred when the complete closing market is available:

```text
no_vig_clv_pp = closing_no_vig_probability - taken_no_vig_probability
```

For a backed selection, a higher closing no-vig probability than at entry generally indicates positive CLV.

### Price ratio

Optional multiplicative metric:

```text
price_clv = odds_taken / closing_odds - 1
```

Positive means the bettor took the higher decimal price.

## Core performance metrics

```text
Turnover = sum(stakes)
Net P&L = sum(profit_loss)
ROI or yield = Net P&L / Turnover
Bankroll return = Net P&L / Starting bankroll
Hit rate = wins / (wins + losses)
Average expected EV = stake-weighted mean(expected_ev)
Positive CLV rate = bets with positive CLV / bets with closing data
Maximum drawdown = maximum peak-to-trough bankroll decline
```

## Probability scoring

For binary outcomes:

```text
Brier = mean((predicted_probability - outcome)^2)
Log loss = -mean(y*ln(p) + (1-y)*ln(1-p))
```

Clip probabilities only according to a documented numerical policy. Do not hide extreme prediction failures.

## Calibration analysis

Group predictions into probability buckets and compare:

- average predicted probability;
- realized frequency;
- number of observations;
- average odds;
- average CLV;
- ROI.

Use reliability diagrams and expected calibration error. Avoid conclusions from small buckets.

## Required segmentation

Report at minimum by:

- sport and competition;
- market type and period;
- model name and version;
- candidate tier;
- odds band;
- predicted probability band;
- expected EV band;
- time from decision to event start;
- data quality status;
- book;
- home/favorite/underdog orientation where relevant.

Do not pool materially different model versions into one headline result without separate rows.

## Sample-size rules

Use staged conclusions:

| Comparable settled bets | Interpretation |
|---:|---|
| <100 | Insufficient for strong conclusions. Focus on data integrity and CLV. |
| 100–499 | Early signal. Maintain conservative sizing. |
| 500–1,999 | Evaluate calibration and edge by segment. |
| >=2,000 | Stronger evidence, still subject to market and model drift. |

The sample must be comparable. Five hundred bets across unrelated sports, markets, and model versions do not automatically validate each segment.

## Drift and failure triggers

Trigger review when any occurs:

- rolling average CLV turns materially negative;
- calibration error rises beyond the model's control limit;
- actual data distributions depart from training distributions;
- rejected or stale-data rates spike;
- expected EV rises while CLV and results deteriorate;
- one source or book causes abnormal discrepancies;
- execution price is consistently worse than recorded decision price;
- model version changes without a clean performance boundary.

## Model promotion criteria

A model may move to a higher Kelly tier only when all configured requirements are met. Recommended minimum:

- at least 500 comparable settled bets;
- positive stake-weighted no-vig CLV;
- acceptable calibration and log loss;
- no unresolved leakage or target-mapping issue;
- controlled maximum drawdown;
- stable performance across more than one time window;
- documented approval of the model version.

## Monthly report

```text
DOCTORE PERFORMANCE REPORT
Period: [start to end]
Settled bets: [N]
Turnover: [amount]
Net P&L: [amount]
ROI/yield: [percentage]
Bankroll return: [percentage]
Expected stake-weighted EV: [percentage]
Average no-vig CLV: [percentage points]
Positive CLV rate: [percentage]
Brier score: [value]
Log loss: [value]
Maximum drawdown: [percentage]
Best validated segment: [segment]
Worst segment: [segment]
Data-quality rejection rate: [percentage]
Model versions active: [list]
Risk-tier recommendation: [maintain, reduce, increase, pause]
Required actions: [list]
```

## Post-settlement rule

Do not rewrite the original probability, EV, or rationale after seeing the result. Add post-settlement notes as a separate field. Preserve the decision-time audit trail.