# SKILL: Model Probability

> Purpose: Validate that a candidate probability is a real, versioned, market-matched model output rather than an LLM estimate or narrative adjustment.

## Non-negotiable boundary

The language model is not the probability model. It may explain, audit, and reject a supplied probability. It may not generate a replacement probability from recent form, injuries, line movement, public splits, or intuition.

## Required model output

```yaml
model_name: string
model_version: string
target_market: string
selection: string
probability_raw: number
probability_calibrated: number | null
calibration_status: calibrated | uncalibrated | stale | unknown
calibration_method: isotonic | platt | beta | none | other
prediction_generated_at: ISO-8601
feature_cutoff_at: ISO-8601
feature_schema_version: string
training_cutoff_at: ISO-8601
validation_window: string | null
validation_sample_size: integer | null
brier_score: number | null
log_loss: number | null
expected_calibration_error: number | null
```

Use `probability_calibrated` when available and valid. Otherwise use `probability_raw` only under the stricter uncalibrated risk tier.

## Target matching

Confirm exact alignment between model target and sportsbook market:

- event identity;
- selection orientation;
- market type;
- period;
- line or handicap;
- inclusion of overtime, extra innings, shootouts, retirements, pushes, or void rules;
- scheduled participants and venue conditions assumed by the model.

A full-game moneyline probability cannot price a first-five-innings, regulation-only, set, map, or alternative handicap market.

## Calibration states

### Validated

A model may use the validated Kelly tier only when:

- calibration was measured out of sample;
- the current model version has a meaningful sample;
- Brier score, log loss, and calibration plots are available;
- recent CLV does not show material deterioration;
- target and feature schemas are stable;
- no leakage or survivorship issue is known.

### Uncalibrated

Use the uncalibrated tier when:

- probability calibration has not been fitted;
- sample size is insufficient;
- a new model or feature schema was deployed;
- the market or competition is outside the validated domain;
- only raw classifier scores are available.

### Stale or unknown

Return `BLOCKED` when:

- model version is unknown;
- prediction timestamp is missing;
- model inputs changed materially after prediction;
- calibration artifact belongs to a different model version;
- target mapping is ambiguous;
- the probability was manually typed without provenance.

## Probability integrity checks

Verify:

```text
0 < probability < 1
```

For complete mutually exclusive model outputs, verify probabilities sum close to 1 within documented tolerance. Do not renormalize a single supplied probability without the model contract authorizing it.

Flag extreme probabilities for review. An extreme value is not automatically wrong, but it requires evidence that the model was trained and calibrated in that range.

## Market leakage checks

If market odds are model features, disclose:

- source books;
- snapshot timing;
- whether the evaluated price was included;
- whether no-vig transformation was used;
- whether live production timing matches backtest timing.

A model that uses the current market as an input may still add value, but apparent edge can be overstated if the same price is reused inconsistently.

## Uncertainty handling

When a model supplies uncertainty or an ensemble distribution, use the lower confidence bound for sizing where configured.

Example shrinkage:

```text
p_sized = market_no_vig_p + shrinkage_factor * (model_p - market_no_vig_p)
```

Suggested starting factors:

| Validation status | Shrinkage factor |
|---|---:|
| New or uncalibrated | 0.25–0.50 |
| Partially validated | 0.50–0.75 |
| Validated and stable | 0.75–1.00 |

Use the original calibrated model probability for reported EV, but clearly show the probability used for stake sizing.

## Model change controls

Every model deployment should record:

- previous and new version;
- feature changes;
- target changes;
- training window;
- validation results;
- calibration artifact;
- expected affected sports and markets;
- rollback rule.

Do not pool performance across materially different model versions without segmentation.

## Required output

```text
MODEL VALIDATION
Model: [name and version]
Target match: YES | NO
Prediction timestamp: [ISO-8601]
Feature cutoff: [ISO-8601]
Probability raw: [percentage]
Probability calibrated: [percentage or unavailable]
Probability used for EV: [percentage]
Probability used for sizing: [percentage]
Calibration status: [state]
Validation sample: [N or unavailable]
Known limitations: [list]
Decision: VALIDATED | UNCALIBRATED | BLOCKED
```