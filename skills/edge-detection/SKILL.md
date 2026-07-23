---
name: edge-detection
description: Calculate expected value, break-even probability, model edge versus a no-vig market, and minimum acceptable odds. Use when the user asks whether a bet is +EV, mikä on EV, edge, value bet, fair odds, price threshold, or whether current decimal odds qualify under Doctore thresholds.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for deterministic calculations.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: mathematics
allowed-tools: Read Grep Glob Bash(python:*)
---

# Edge detection

Use only a validated executable price and validated model probability.

## Workflow

1. Receive decimal odds `d`, model probability `p`, no-vig market probability `m`, minimum EV, and minimum market edge.
2. Run `scripts/calculate_edge.py` with substituted values.
3. Report break-even probability, EV, edge versus market, break-even odds, and minimum qualifying odds.
4. Return `PASS` when EV or market-edge thresholds fail.
5. Send qualifying candidates to sport validation, anti-bias audit, and risk management.

## References

- Read `references/formulas.md` for definitions and examples.
- Read `references/decision-policy.md` for BET, WATCH, and PASS economics.

## Hard rule

No-vig market probability is used for relative edge reporting. The executable decimal price is used for EV and Kelly.
