---
name: risk-management
description: Size Doctore bets using fractional Kelly, uncertainty shrinkage, units, bankroll limits, exposure caps, correlation, and drawdown controls. Use when the user asks how much to stake, panos, units, Kelly, bankroll percentage, daily exposure, league exposure, correlated bets, or whether a candidate fits the risk budget.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for deterministic sizing.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: risk
allowed-tools: Read Grep Glob Bash(python:*)
---

# Risk management

Size only candidates that passed data, model, sport, edge, and bias gates.

## Workflow

1. Select the permitted model probability for sizing, including documented shrinkage when required.
2. Calculate full Kelly from the executable price.
3. Apply the allowed fractional Kelly based on calibration maturity.
4. Aggregate correlated positions before applying caps.
5. Apply per-bet, open-exposure, daily-turnover, league, and rolling-window limits.
6. Run `scripts/size_position.py`.
7. Round down to the supported stake increment. Never round upward through a cap.

## References

- Read `references/kelly-policy.md` for probability shrinkage and fraction selection.
- Read `references/portfolio-limits.md` for exposure and correlation rules.

Return zero stake when full Kelly is non-positive or any hard cap has no remaining capacity.
