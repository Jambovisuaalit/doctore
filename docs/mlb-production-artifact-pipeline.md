# MLB production artifact pipeline

This workflow converts one locked MLB full-game-total dataset and one live event snapshot into immutable model and decision artifacts.

```text
locked training dataset
→ expanding walk-forward XGBRegressor
→ prior-only OOS residual CDF
→ exact-line P(Over) / P(Under) / P(Push)
→ chronological Platt calibration
→ Brier + log loss vs no-vig market
→ canonical model-output adapter
→ JSON Schema validation
→ SHA-256 sidecar
→ create-only prediction artifacts
→ bet_decision_core
```

## Fail-closed input set

The runner requires seven external files:

1. `training.csv`
2. `training-dataset-manifest.json`
3. `live-features.json`
4. `market-snapshot.json`
5. `portfolio-state.json`
6. `risk-policy.json`
7. `mlb-context.json`

The dataset manifest must use `doctore.training-dataset.v1` and lock:

- exact CSV SHA-256;
- exact ordered header;
- exact row count;
- sport, competition, market and settlement domain;
- target definition;
- feature schema and ordered feature columns;
- target, line, over-odds, under-odds and timestamp columns;
- strictly ascending timestamp order.

A spreadsheet title, a copied CSV, model code, an odds snapshot or a historical report is not a locked training dataset.

## Required CSV semantics

Each row must represent one historical pregame prediction opportunity and include only information available at that row's feature cutoff.

Minimum semantic fields:

```text
timestamp              point-in-time feature cutoff or prediction timestamp
<feature columns>      numeric pregame features using the locked schema
final_total_runs       settled full-game home + away runs
total_line             historical offered full-game total line
over_odds_decimal      historical executable Over price
under_odds_decimal     historical executable Under price
```

The dataset must not be assembled by joining final lineups, final weather, current-season aggregates or current-game outcomes back into earlier prediction rows.

## Live feature payload

```json
{
  "schema_version": "doctore.live-features.v1",
  "event_id": "MLB-2026-07-27-SEA-TEX",
  "feature_schema_version": "mlb.full-game-total.v1",
  "feature_cutoff_at": "2026-07-27T17:55:00+00:00",
  "features": {
    "feature_a": 0.0,
    "feature_b": 0.0
  }
}
```

Feature keys must match the manifest exactly. Missing and additional features are both rejected.

## Market normalization

The current runner is deliberately narrow:

```text
sport: MLB
market_type: total
target_market: full_game_total
period: full_game
selection: over | under
line: numeric
outcomes: exactly two complete prices
```

Selection names must be lowercase `over` and `under` so the rich prediction, canonical model output and market snapshot remain exact-domain identical.

## Point-in-time ordering

The runner enforces:

```text
training_cutoff_at
< feature_cutoff_at
≤ market.captured_at
≤ prediction_generated_at
≤ evaluated_at
< event_start_at
```

Any violation stops the run before artifact publication.

## Command

```bash
python scripts/run_production_artifact_pipeline.py \
  --csv private_data/mlb_full_game_totals_v1.csv \
  --dataset-manifest private_data/mlb_full_game_totals_v1.manifest.json \
  --live-features private_data/SEA_TEX_20260727.features.json \
  --market-snapshot private_data/SEA_TEX_20260727.total_8_over.market.json \
  --portfolio-state private_data/portfolio-state.json \
  --risk-policy research/config/risk-policy.json \
  --mlb-context private_data/SEA_TEX_20260727.mlb-context.json \
  --output-dir private_artifacts/2026/07/27/SEA_TEX_TOTAL_8_OVER \
  --model-name doctore-mlb-full-game-total \
  --model-version 1.0.0 \
  --prediction-generated-at 2026-07-27T17:58:00+00:00 \
  --evaluated-at 2026-07-27T17:58:30+00:00 \
  --min-train-size 1000 \
  --test-size 25 \
  --min-residual-history 300 \
  --min-calibration-history 500 \
  --minimum-validation-sample 500
```

Do not commit the private CSV, live features, bankroll state or produced prediction artifacts to the public repository.

## Produced artifacts

```text
xgb-model.json
residual-distribution.json
platt-calibrator.json
validation-report.json
rich-prediction.json
canonical-model-output.json
canonical-model-output.sha256
decision-output.json
run-manifest.json
```

The output directory must not already exist. JSON artifacts use create-only writes. The model file is written only after all input, dataset, domain and point-in-time checks pass.

## Status handling

| Probability pipeline | Canonical status | Decision consequence |
|---|---|---|
| `validated` | `validated` | eligible for normal decision gates |
| `provisional` | `unknown` | `BLOCKED`, stake 0 |
| `degraded` | `unknown` | `BLOCKED`, stake 0 |

The runner does not promote a model based on edge, ROI or a single prediction. Validation still requires sufficient chronological OOS volume and superiority to the no-vig market on both Brier score and log loss.

## Current data blocker

The Drive files currently identified do not satisfy this contract as one locked dataset:

- `Clean_MLB_Data.csv` contains mixed code/data structure and does not expose the required timestamp, market line and two-sided odds contract.
- `MLB ODDS DATA 2023` contains historical teams, lines and prices, but does not include the settled full-game total target or the locked point-in-time feature block.

They may be source inputs for a future join, but the join must be reconstructed, audited, sorted chronologically and hash-locked before this runner accepts it.
