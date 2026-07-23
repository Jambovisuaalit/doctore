# Model contract

The canonical contract is `contracts/model-output.schema.json` using JSON Schema Draft 2020-12. Every model output must declare `schema_version: doctore.model-output.v1` and pass `scripts/validate_model_output.py` before edge or risk calculations.

## Required identity and provenance

Every output must contain:

- stable `event_id` and `market_id`;
- `model_name` and immutable `model_version`;
- `prediction_generated_at`, `feature_cutoff_at`, and `training_cutoff_at`;
- `feature_schema_version`;
- raw probability and calibrated probability when available;
- calibration status and method;
- validation window, sample size, and calibration metrics;
- exact prediction and validation domains.

## Exact sport and market domain

The prediction target declares these top-level fields:

- `sport`;
- `competition`;
- `market_type`;
- `target_market`;
- `period`;
- `line`;
- `settlement_rules`.

`validation_domain` must contain the same fields with exactly matching values. Any mismatch returns `BLOCKED`, including NBA versus WNBA, MLB versus KBO or NPB, moneyline versus spread, full game versus first period, regulation versus overtime, different prop lines, or different settlement rules.

## Calibration states

### `validated`

Validated status requires all of the following:

- `probability_calibrated` strictly between 0 and 1;
- calibration method other than `none`;
- non-empty validation window;
- positive `validation_sample_size`;
- Brier score between 0 and 1;
- non-negative log loss;
- expected calibration error between 0 and 1;
- exact validation-domain match.

Missing or null evidence returns `BLOCKED`; it must not silently downgrade to validated.

### `uncalibrated`

Uncalibrated status requires `calibration_method: none`. `probability_calibrated` and validation metrics may be null. A schema-valid output returns `UNCALIBRATED` and must use the stricter uncalibrated risk tier.

### `unknown`

Unknown calibration provenance always returns `BLOCKED` even when the JSON structure is otherwise valid.

## Validator result

The validator emits machine-readable JSON with:

- `valid`;
- `decision`: `VALIDATED`, `UNCALIBRATED`, or `BLOCKED`;
- model identity;
- `domain_match`;
- structured error codes, paths, and messages.

Exit code `0` means `VALIDATED` or `UNCALIBRATED`, exit code `1` means candidate-level `BLOCKED`, and exit code `2` means the schema or input document could not be loaded.
