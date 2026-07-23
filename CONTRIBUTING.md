# Contributing to Doctore Sports Intelligence

Contributions must improve mathematical correctness, data integrity, model validation, risk control, or auditability. Picks, unsupported heuristics, and guaranteed-profit claims are not accepted.

## High-value contributions

- New sport-specific validation skills.
- Better data contracts and freshness rules.
- Tested no-vig or consensus-market methods.
- Calibration, CLV, and drift-monitoring improvements.
- Risk and correlation controls.
- Reproducible examples and automated tests for formulas.
- Bug fixes with a concrete failing example.

## Not accepted

- Narrative picks without a model probability.
- Arbitrary injury or weather point adjustments.
- Confidence-based stake tables that bypass Kelly and caps.
- Results-only claims without decision-time records.
- Strategies that use stale or non-executable prices.
- Undocumented changes to thresholds or formulas.

## Required skill format

```markdown
# SKILL: Name

> Purpose: One sentence.

## Required inputs
## Validation sequence
## Blocking conditions
## Required output
```

A sport module must define:

- supported model domain;
- exact market-target matching requirements;
- critical confirmations;
- model-input freshness triggers;
- correlation risks;
- `VALID`, `DEGRADED`, and `BLOCKED` conditions.

## Mathematical changes

Any change to EV, no-vig, Kelly, CLV, calibration, or risk formulas must include:

1. Current formula.
2. Proposed formula.
3. Reason for the change.
4. Worked numerical example.
5. Tests or external validation.
6. Migration impact on historical records.

## Threshold changes

Threshold changes require evidence. Include:

- affected sport and market;
- model version and validation window;
- sample size;
- calibration metrics;
- CLV impact;
- ROI and drawdown impact;
- proposed rollback condition.

Do not optimize thresholds on the same sample used to report final performance.

## Testing checklist

Before submitting a change:

- verify all formulas with at least three numerical cases;
- include a negative-EV case;
- include a stale-data or missing-input case;
- verify price-threshold direction;
- verify positive CLV when the taken decimal price is higher than the closing price;
- verify Kelly returns zero for non-positive EV;
- verify risk caps bind correctly;
- verify sport and market targets cannot be mismatched.

## Pull request description

Include:

```text
Problem:
Change:
Why it is correct:
Evidence:
Risks:
Test cases:
Rollback plan:
```

## Responsible use

Doctore is an analytical framework, not a promise of profit. Contributions must preserve hard risk controls, audit trails, and human review.