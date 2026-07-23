# Analysis notebooks

Use this directory for exploratory analysis that supports, but never silently replaces, the deterministic production scripts.

## Rules

1. Use chronological train, calibration, and test boundaries.
2. Record the model version, feature schema version, data cutoff, and notebook run timestamp.
3. Never calculate historical probabilities using future residuals or future closing lines.
4. Compare model Brier score, log loss, ECE, and CLV against the relevant no-vig market baseline.
5. Keep sport, competition, market type, period, line rules, and settlement domain explicit.
6. Export reusable logic into `src/` or `research/scripts/`; do not leave decision-critical logic only in a notebook.
7. Do not commit licensed data, private bankroll records, credentials, or generated model artifacts.

## Naming

```text
YYYY-MM-DD_<sport>_<market>_<question>.ipynb
```

Example:

```text
2026-07-23_nba_game-total_residual-drift.ipynb
```

## Required notebook conclusion

Every notebook should end with:

- evidence inspected;
- data and feature cutoffs;
- leakage checks;
- metrics by model version and exact domain;
- limitations;
- recommended action: retain, investigate, recalibrate, retrain, or block.
