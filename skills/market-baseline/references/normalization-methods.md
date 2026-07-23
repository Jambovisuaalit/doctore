# Normalization methods

## Proportional method

For decimal odds `d_i`:

```text
q_i = 1 / d_i
market_sum = Σq_i
overround = market_sum - 1
no_vig_i = q_i / market_sum
```

Use this transparent method by default.

## Alternative methods

Shin, power, or other normalization is permitted only when the method, parameters, validation history, and consistent use are documented. Do not switch methods candidate by candidate to create a larger apparent edge.

## Price thresholds

For model probability `p` and minimum EV `m`:

```text
break_even_odds = 1 / p
minimum_qualifying_odds = (1 + m) / p
```
