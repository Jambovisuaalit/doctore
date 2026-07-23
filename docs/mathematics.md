# Doctore Mathematics Reference

This document is the canonical reference for market probability, edge, expected value, Kelly sizing, price thresholds, and closing line value.

## 1. Decimal odds and break-even probability

For decimal odds `d`:

```text
break_even_probability = 1 / d
```

Example:

```text
d = 2.10
break_even_probability = 1 / 2.10 = 0.476190 = 47.6190%
```

This is the minimum win probability required for zero expected value before considering stake sizing.

## 2. Raw market margin

For a market with outcomes `i = 1...n`:

```text
q_i = 1 / d_i
market_sum = sum(q_i)
market_margin = market_sum - 1
```

Example with two outcomes:

```text
A = 1.80 -> q_A = 55.5556%
B = 2.10 -> q_B = 47.6190%
market_sum = 103.1746%
market_margin = 3.1746%
```

## 3. Proportional no-vig probability

```text
no_vig_probability_i = q_i / market_sum
```

Example:

```text
no_vig_A = 55.5556 / 103.1746 = 53.8462%
no_vig_B = 47.6190 / 103.1746 = 46.1538%
```

The no-vig probability is a market baseline, not the model prediction.

## 4. Edge definitions

Let:

- `p` = calibrated model probability;
- `m` = no-vig market probability;
- `bep` = break-even probability at the executable price.

```text
edge_vs_market_pp = p - m
edge_vs_break_even_pp = p - bep
```

Report these in percentage points, not percent change.

Example:

```text
p = 51.0%
m = 48.5%
bep = 47.619%

edge_vs_market = +2.5 percentage points
edge_vs_break_even = +3.381 percentage points
```

## 5. Expected value

For one unit staked at decimal odds `d`:

```text
EV = p * d - 1
```

Equivalent expanded form:

```text
EV = p * (d - 1) - (1 - p)
```

Example:

```text
p = 0.51
d = 2.10
EV = 0.51 * 2.10 - 1 = 0.071 = +7.1%
```

For a 500 EUR stake:

```text
expected_profit = 500 * 0.071 = 35.50 EUR
```

Expected profit is not the likely result of one bet. It is a long-run expectation under the probability assumption.

## 6. Minimum probability for target EV

For target EV `t`:

```text
minimum_probability = (1 + t) / d
```

Example at decimal odds 2.10 and target EV 3%:

```text
minimum_probability = 1.03 / 2.10 = 49.0476%
```

## 7. Minimum price for target EV

```text
minimum_decimal_odds = (1 + t) / p
```

Example with model probability 51% and target EV 3%:

```text
minimum_decimal_odds = 1.03 / 0.51 = 2.0196
```

The execution rule should therefore require approximately 2.02 or better, subject to sportsbook price increments.

## 8. Correct Kelly criterion

For decimal odds `d` and sizing probability `p_sized`:

```text
full_kelly = (p_sized * d - 1) / (d - 1)
```

Example using the full 51% model probability:

```text
p_sized = 0.51
d = 2.10
full_kelly = (0.51 * 2.10 - 1) / 1.10
full_kelly = 0.064545 = 6.4545% of bankroll
```

At 25% fractional Kelly:

```text
fractional_kelly = 6.4545% * 0.25 = 1.6136% of bankroll
```

With a 50,000 EUR bankroll:

```text
raw_stake = 50,000 * 0.016136 = 806.82 EUR
```

Apply hard caps and round down after calculation.

## 9. Uncertainty shrinkage

Suppose:

```text
model_p = 51.0%
market_no_vig_p = 48.5%
shrinkage_factor = 0.50
```

Then:

```text
sizing_p = 48.5% + 0.50 * (51.0% - 48.5%)
sizing_p = 49.75%
```

At odds 2.10:

```text
full_kelly = (0.4975 * 2.10 - 1) / 1.10
full_kelly = 4.0682%
```

At 25% fractional Kelly:

```text
stake_fraction = 1.0170% of bankroll
stake = 508.52 EUR on a 50,000 EUR bankroll
```

The model EV is still reported from the calibrated model probability. The more conservative sizing probability controls stake.

## 10. Closing line value

### Raw implied-probability CLV

```text
implied_taken = 1 / odds_taken
implied_close = 1 / odds_close
raw_clv_pp = implied_close - implied_taken
```

Example:

```text
odds_taken = 2.30 -> implied_taken = 43.4783%
odds_close = 2.10 -> implied_close = 47.6190%
raw_clv = +4.1407 percentage points
```

The bettor took the better price, so CLV is positive.

### Price-ratio CLV

```text
price_clv = odds_taken / odds_close - 1
```

Example:

```text
2.30 / 2.10 - 1 = +9.5238%
```

### Preferred no-vig CLV

When the complete entry and closing markets are available:

```text
no_vig_clv_pp = closing_no_vig_probability - entry_no_vig_probability
```

This reduces distortion from changing bookmaker margin.

## 11. Brier score

For binary outcomes `y` where win = 1 and loss = 0:

```text
brier = mean((p - y)^2)
```

Lower is better, but comparisons should use the same target domain and base rate.

## 12. Log loss

```text
log_loss = -mean(y * ln(p) + (1-y) * ln(1-p))
```

Log loss penalizes confident wrong predictions heavily. Preserve original probabilities in the audit trail.

## 13. ROI and bankroll return

```text
turnover = sum(stakes)
ROI_or_yield = net_profit / turnover
bankroll_return = net_profit / starting_bankroll
```

These answer different questions. Do not report bankroll return as betting yield.

## 14. Maximum drawdown

For bankroll series `B_t`:

```text
running_peak_t = max(B_0 ... B_t)
drawdown_t = (running_peak_t - B_t) / running_peak_t
maximum_drawdown = max(drawdown_t)
```

## 15. Rounding policy

- Keep full precision internally.
- Display probabilities to 0.1 percentage point unless more precision is required for audit.
- Display EV to 0.1%.
- Round minimum acceptable odds conservatively upward.
- Round stakes down to the permitted increment.
- Never round a marginal negative EV into a positive decision.