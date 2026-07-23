# Kelly policy

```text
full_kelly = (p*d - 1) / (d - 1)
provisional_fraction = full_kelly * allowed_kelly_fraction
```

Use calibrated sizing probability, not narrative confidence.

Default allowed fractions:

- uncalibrated or limited evidence: 0.10 Kelly or lower;
- validated model/market domain: 0.25 Kelly;
- higher fractions up to 0.60 only with explicit governance approval, stable calibration, adequate sample size, liquidity, and positive CLV evidence.

Shrink uncertain probabilities toward a documented reference before Kelly. Never increase Kelly after losses.
