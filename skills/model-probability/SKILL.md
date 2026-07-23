---
name: model-probability
description: Validate Doctore XGBoost or statistical model probabilities before betting analysis. Use when the user supplies or asks about true probability, mallin todennäköisyys, model version, calibration, Brier score, log loss, feature cutoff, target-market matching, or whether a prediction is valid for current odds.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for model-output validation.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: model-governance
allowed-tools: Read Grep Glob Bash(python:*)
---

# Model probability

The language model is not the probability model. Validate externally produced output; never replace it with an intuitive estimate.

## Workflow

1. Match event, selection, market, period, line, and settlement definition.
2. Confirm model name, version, prediction time, feature cutoff, and training/validation provenance.
3. Confirm whether the probability is calibrated, uncalibrated, or unknown.
4. Check whether critical live facts changed after the feature cutoff.
5. Run `scripts/validate_model_output.py INPUT.json`.
6. Return the calibrated probability and validation status without narrative adjustment.

## References

- Read `references/model-contract.md` for required fields and target matching.
- Read `references/calibration-policy.md` when assessing model maturity or choosing a Kelly fraction.

## Prohibited behavior

- Do not derive a replacement probability from injuries, form, line movement, public betting, or intuition.
- Do not blend market and model probabilities unless a documented production calibration method explicitly does so.
- Do not treat accuracy or a short winning streak as probability calibration.
