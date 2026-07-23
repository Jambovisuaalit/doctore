# SKILL: Edge Detection

> Purpose: Convert a valid market snapshot and calibrated model probability into transparent edge, EV, price threshold, and execution status.

## Required inputs

```yaml
odds_decimal: number
model_probability: number
market_no_vig_probability: number
minimum_ev: number
minimum_edge_pp: number
```

Use the executable price for EV. Use the no-vig market probability only for relative edge reporting.

## Definitions

For decimal odds `d` and model probability `p`:

```text
break_even_probability = 1 / d
edge_vs_break_even_pp = p - break_even_probability
EV = p * d - 1
```

For market no-vig probability `m`:

```text
edge_vs_market_pp = p - m
```

These are different metrics. Do not use them interchangeably.

## EV example

```text
Decimal odds: 2.10
Model probability: 51.0%
Break-even probability: 47.619%
EV = 0.51 * 2.10 - 1
EV = +0.071 = +7.1%
```

If the no-vig market probability is 48.5%:

```text
Edge vs market = 51.0% - 48.5% = +2.5 percentage points
```

## Qualification gate

Default Doctore rule:

```text
BET candidate when:
EV >= minimum_ev
AND edge_vs_market_pp >= minimum_edge_pp
AND full Kelly > 0
AND data quality is VALID or permitted DEGRADED
AND model validation is acceptable
AND risk limits allow the position
```

A candidate failing the EV threshold is `PASS`, even when the model probability is higher than the no-vig market probability.

## Price thresholds

Given model probability `p`:

```text
zero_EV_price = 1 / p
minimum_price_for_target_EV = (1 + minimum_ev) / p
```

Example with `p = 0.51` and minimum EV `0.03`:

```text
Zero-EV price = 1 / 0.51 = 1.9608
Minimum 3% EV price = 1.03 / 0.51 = 2.0196
```

Output the minimum acceptable decimal price rounded conservatively upward to the sportsbook's price precision.

## Probability and price sensitivity

Every candidate should show how fragile the edge is.

At minimum calculate:

- EV at the current price;
- EV after one realistic price step against the bettor;
- EV using the sizing probability after uncertainty shrinkage;
- minimum model probability required at the current price.

```text
minimum_probability_for_target_EV = (1 + minimum_ev) / d
```

## Candidate tiers

Tiers describe evidence quality. They do not define stake independently.

| Tier | Requirements |
|---|---|
| A | Validated model, valid data, EV >= 5%, edge >= 2.5 pp, liquid market, clean context. |
| B | Validated or partially validated model, EV >= 3%, edge >= 1.5 pp, acceptable context. |
| C | Uncalibrated/new model or degraded context; EV clears stricter threshold but sizing is heavily reduced. |
| PASS | Threshold not met or Kelly non-positive. |
| BLOCKED | Critical data, target matching, or model provenance failure. |

Do not promote a candidate because of a compelling narrative.

## Multiple books

For each available executable book:

1. calculate EV at that exact price;
2. retain settlement-rule compatibility;
3. choose the highest valid price;
4. record the reference market separately;
5. do not report a price that cannot actually be taken.

## Mutually exclusive positions

When considering both sides or multiple alternatives in the same market:

- never recommend mutually exclusive positions without an explicit hedge or arbitrage model;
- calculate net portfolio payoff by outcome;
- treat middles and arbitrage as separate strategies;
- block accidental duplicate exposure.

## Correlation

Candidate-level EV is not portfolio EV when positions are correlated. Pass all candidates to risk management with event, team, player, total, and derivative-market relationships.

Examples:

- team moneyline and team -1.5;
- favorite and game under/over;
- player prop and team total;
- multiple bets dependent on the same starting pitcher or injury assumption.

## Required output

```text
EDGE CALCULATION
Selection: [selection]
Executable odds: [decimal]
Model probability: [percentage]
Market no-vig probability: [percentage]
Break-even probability: [percentage]
Edge vs market: [percentage points]
Edge vs break-even: [percentage points]
EV: [percentage]
Zero-EV price: [decimal]
Minimum price at target EV: [decimal]
Minimum model probability at current price: [percentage]
Sensitivity: [summary]
Candidate tier: A | B | C | PASS | BLOCKED
```