# Economic decision policy

- `PASS`: EV is non-positive or below the configured threshold; market edge is below threshold; or the price is worse than the minimum qualifying price.
- `WATCH`: the model qualifies at a clearly defined better price that may become available before start.
- `BET`: economic thresholds pass and all quality, context, bias, and risk gates also pass.
- `BLOCKED`: data or model validation failed. Do not confuse BLOCKED with PASS.

Confidence labels never override the numerical thresholds.
