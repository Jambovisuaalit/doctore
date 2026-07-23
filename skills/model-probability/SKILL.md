---
name: model-probability
description: Validate Doctore XGBoost or statistical model probabilities before betting analysis. Use when the user supplies or asks about true probability, mallin todennäköisyys, model version, calibration, Brier score, log loss, ECE, validation sample size, feature cutoff, exact sport-market matching, or whether a prediction is valid for current odds.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ and jsonschema for model-output validation.
metadata:
  author: doctore-sports
  version: "2.1.0"
  category: model-governance
allowed-tools: Read Grep Glob Bash(python:*)
---

# Model probability

The language model is not the probability model. Validate externally produced output; never replace it with an intuitive estimate.

## Workflow

1. Require the canonical `contracts/model-output.schema.json` contract.
2. Match sport, competition, market type, target market, period, line, and settlement definition exactly against `validation_domain`.
3. Confirm model name, immutable version, prediction time, feature cutoff, training cutoff, and feature schema version.
4. For `validated`, require calibrated probability, validation sample size, Brier score, log loss, ECE, validation window, and a non-`none` calibration method.
5. Treat schema-valid `uncalibrated` output as `UNCALIBRATED`; never promote it to validated.
6. Treat unknown provenance, missing validated evidence, domain mismatch, or invalid schema as `BLOCKED`.
7. Check whether critical live facts changed after the feature cutoff.
8. Run `scripts/validate_model_output.py INPUT.json`.
9. Return the supplied probability and validator status without narrative adjustment.

## References

- Read `references/model-contract.md` for required fields, decision states, and exact domain matching.
- Read `references/calibration-policy.md` when assessing model maturity or choosing a Kelly fraction.

## Prohibited behavior

- Do not derive a replacement probability from injuries, form, line movement, public betting, or intuition.
- Do not blend market and model probabilities unless a documented production calibration method explicitly does so.
- Do not treat accuracy or a short winning streak as probability calibration.
- Do not transfer validation evidence between sports, competitions, market types, periods, lines, or settlement rules.
