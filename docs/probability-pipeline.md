# XGBRegressor point estimate to calibrated exact-line probability

This module implements the production boundary between a regression point estimate and a Doctore betting probability.

```text
Expanding walk-forward XGBRegressor
  -> strictly OOS point estimates
  -> residuals grouped by model version
  -> empirical residual CDF at the exact market line
  -> chronological walk-forward Platt calibration
  -> Brier and log loss against the no-vig market
  -> content-addressed immutable prediction JSON
```

## Leakage controls

1. Observations must be strictly chronological and include timezone-aware timestamps.
2. Every test block is predicted by a model trained only on earlier rows.
3. The empirical CDF for historical row `t` uses only residuals observed before `t`.
4. The Platt prediction for historical row `t` is fitted only on raw probabilities and outcomes before `t`.
5. Validation metrics use only rows that received a strictly OOS calibrated probability.
6. The final production model and calibrator may use all completed historical rows because the new event outcome is not included.

Using the complete residual sample to price its own historical rows would leak future residuals and understate uncertainty. It is explicitly forbidden.

## Exact-line probability

For point estimate `mu`, market line `L`, and OOS residual `r = actual - prediction`:

```text
threshold = L - mu
P(Over) = P(r > threshold)
P(Under) = P(r < threshold)
P(Push) = P(r = threshold)
```

The implementation uses the empirical distribution directly. It does not silently assume a normal distribution.

For integer lines, Platt calibration is applied to the conditional Over probability among non-push outcomes. The empirical push mass is retained separately:

```text
P(Over calibrated) = (1 - P(Push)) * P(Over | non-push, calibrated)
P(Under calibrated) = (1 - P(Push)) * (1 - P(Over | non-push, calibrated))
```

## Calibration status

| Status | Rule |
|---|---|
| `validated` | OOS evaluation sample meets the configured minimum and calibrated probabilities beat the no-vig market in both Brier score and log loss. |
| `provisional` | The OOS process is valid, but the evaluation sample is below the configured minimum. |
| `degraded` | The sample is large enough, but the calibrated model fails to beat the no-vig market in Brier or log loss. |

`degraded` must not receive the validated Kelly tier.

## CLI

Input CSV rows must already be sorted chronologically.

```bash
python scripts/run_probability_pipeline.py \
  --csv data/nba_totals.csv \
  --features pace,off_rating,def_rating,rest_delta \
  --target actual_total \
  --line market_line \
  --over-odds over_odds_decimal \
  --under-odds under_odds_decimal \
  --timestamp feature_cutoff_at \
  --model-name doctore-nba-total-xgb \
  --model-version 1.4.2 \
  --feature-schema-version nba-total-features-v7 \
  --output-dir artifacts/nba-total-xgb-1.4.2 \
  --min-train-size 1000 \
  --test-size 25 \
  --min-residual-history 300 \
  --min-calibration-history 500 \
  --minimum-validation-sample 500
```

The output directory is create-only. Existing artifact directories are never overwritten.

## Versioned prediction fields

Every production prediction includes:

- model name, semantic version, feature schema and model artifact SHA-256;
- residual-distribution version, method, sample size and artifact SHA-256;
- exact line, raw Over/Under/Push probabilities and threshold residual;
- Platt-calibration version, artifact SHA-256 and calibrated probabilities;
- OOS Brier score, log loss, ECE and no-vig market baselines;
- deterministic prediction ID and content SHA-256;
- create-only immutability policy.

The JSON hash identifies the prediction content. A different market snapshot, line, feature cutoff, model artifact, residual artifact or calibrator produces a different prediction ID.
