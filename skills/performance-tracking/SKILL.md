---
name: performance-tracking
description: Record and evaluate Doctore betting performance by model version, sport, market, and price timing. Use when the user asks for bet logging, tulosseuranta, ROI, yield, units, CLV, Brier score, log loss, calibration, drawdown, model drift, or a monthly performance review.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for CSV metric calculation.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: analytics
allowed-tools: Read Grep Glob Bash(python:*)
---

# Performance tracking

Measure model quality separately from realized betting variance.

## Workflow

1. Log every approved bet at decision time with immutable model and market fields.
2. Add closing price and result after settlement without overwriting decision-time data.
3. Run `scripts/calculate_metrics.py BET_LOG.csv`.
4. Report ROI, yield, units, CLV, Brier score, log loss, calibration, and drawdown by relevant segment.
5. Flag insufficient samples and model-version mixing.

## References

- Read `references/bet-log-schema.md` when creating or validating records.
- Read `references/metrics.md` when interpreting CLV, calibration, or model quality.

Do not validate a model from win rate alone. Do not combine incompatible market domains into a single calibration claim.
