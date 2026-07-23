---
name: market-baseline
description: Calculate sportsbook implied probabilities, overround, no-vig fair probabilities, break-even prices, and minimum qualifying odds. Use when the user asks for no-vig, fair price, markkinatodennäköisyys, bookmaker margin, line comparison, or a price threshold for moneyline, spread, total, prop, 1X2, or Asian handicap markets.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for deterministic no-vig calculations.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: mathematics
allowed-tools: Read Grep Glob Bash(python:*)
---

# Market baseline

Normalize a complete executable market. Do not label the result as Doctore's model probability.

## Workflow

1. Confirm all outcomes belong to the same book, snapshot, market, line, period, and settlement rule.
2. Run `scripts/calculate_no_vig.py --odds ODDS...`.
3. Report raw implied probabilities, market sum, overround, and normalized probabilities.
4. Use the executable price, not the no-vig price, for EV calculations.
5. Send the selected no-vig probability to `edge-detection` as a comparison baseline.

## Conditional references

- Read `references/normalization-methods.md` when proportional normalization may be insufficient.
- Read `references/market-matching.md` for spread, total, 1X2, push, or settlement-rule matching.

## Hard rules

- Never normalize an incomplete outcome set.
- Never pair different spread or total lines.
- Never mix books or materially different timestamps.
- Never infer true probability solely from no-vig prices.
