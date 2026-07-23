# SKILL: Market Baseline

> Purpose: Convert an executable sportsbook market into a correctly normalized no-vig reference probability without pretending that the market is Doctore's prediction model.

## Required inputs

```yaml
book: string
market_id: string
market_type: string
period: string
line: number | null
snapshot_at: ISO-8601
outcomes:
  - selection: string
    odds_decimal: number
```

The outcome set must be complete, mutually exclusive, and use the same market definition.

## Decimal implied probability

For decimal odds `d`:

```text
raw_implied_probability = 1 / d
```

This includes bookmaker margin and is not a fair probability.

## Proportional no-vig method

For `n` outcomes:

```text
q_i = 1 / d_i
market_sum = sum(q_i)
market_margin = market_sum - 1
no_vig_probability_i = q_i / market_sum
```

### Two-way example

```text
Side A: 1.80 -> 55.5556%
Side B: 2.10 -> 47.6190%
Market sum: 103.1746%
Margin: 3.1746%
No-vig A: 53.8462%
No-vig B: 46.1538%
```

### Three-way example

Apply the same normalization across home, draw, and away. Do not remove the draw or convert the market into a two-way market unless a separate documented model does so.

## Method selection

Use proportional normalization as the default transparent baseline. A different method, such as Shin or power normalization, may be used only when:

- the method is named;
- parameters are reported;
- the same method is used consistently in backtests and live evaluation;
- the reason for using it is documented.

Do not switch methods candidate by candidate to improve apparent edge.

## Reference market rules

Primary baseline:

- use the same executable book as the candidate;
- use all outcomes from one synchronized snapshot;
- report the actual market margin.

Optional consensus baseline:

- may combine multiple sharp or liquid books;
- must use a documented aggregation rule;
- must preserve timestamps and book identities;
- must not substitute for the executable price used in EV calculation.

Pinnacle may be used as the primary reference market when available, but its price is still not automatically the true probability.

## Spread and total handling

For spreads and totals:

- both sides must use the same line;
- complementary handicaps must match exactly;
- over and under must use the same total;
- pushes and settlement rules must match;
- alternative lines are separate markets.

Do not compare `Over 8.0` with `Under 8.5` as a complete two-way market.

## Price threshold calculation

Given model probability `p` and minimum required EV `m`:

```text
minimum_decimal_odds = (1 + m) / p
```

Given model probability `p`, break-even price is:

```text
break_even_decimal_odds = 1 / p
```

The output must show both:

- break-even price at zero EV;
- minimum executable price at the configured EV threshold.

## Line movement

Line movement is contextual information only.

Report:

```text
opening_price -> current_price
opening_no_vig_probability -> current_no_vig_probability
change_in_percentage_points
elapsed_time
source
```

Do not infer professional money, insider information, or causal news without reliable evidence.

## Blocking conditions

Return `BLOCKED` when:

- an outcome is missing;
- prices are stale;
- outcome timestamps differ materially;
- period or settlement rules differ;
- a spread or total line is mismatched;
- odds are less than or equal to 1.0;
- event or selection identity is ambiguous.

## Required output

```text
MARKET BASELINE
Book: [book]
Market: [market and period]
Snapshot: [ISO-8601]
Prices: [complete outcome set]
Raw implied probabilities: [values]
Market margin: [percentage]
No-vig probabilities: [values]
Normalization method: [method]
Executable candidate price: [decimal]
Break-even probability: [percentage]
```