# Bet decision contract

## Field ownership

| Document | Owns |
|---|---|
| `model-output` | immutable model probability, calibration status, model version, feature cutoff, validation domain |
| `market-snapshot` | executable price, complete outcome set, book, line, settlement, capture time |
| `portfolio-state` | bankroll, available balance, drawdown, current exposure amounts |
| `risk-policy` | EV and edge thresholds, Kelly fractions, shrinkage weights, freshness limits, exposure caps |
| sport context | whether live facts still match model assumptions |
| `decision-output` | deterministic result and audit hashes |

## Probability use

The decision core preserves three separate values:

1. `probability_used_for_economics`
   - validated model: calibrated probability;
   - allowed uncalibrated model: raw probability.
2. `no_vig_probability`
   - proportional normalization of the complete current market;
   - used only as the market baseline.
3. `sizing_probability`
   - `market + weight × (model − market)`;
   - used only for Kelly sizing.

EV and edge qualification use the immutable model probability. Kelly uses the sizing probability. The model probability is never overwritten.

## Exact matching

The following fields must match between model and market documents:

- event ID;
- market ID;
- sport and competition;
- market type and target market;
- period;
- exact line;
- settlement rules;
- selection.

The model validation domain must also match sport, competition, market type, target market, period, line, and settlement rules.

## Determinism

The evaluation timestamp is an explicit input. The decision ID is a SHA-256 hash of:

- all input documents;
- the evaluation timestamp;
- the formula version.

Identical inputs produce an identical decision document.

## Human boundary

`human_approval_required` is always `true`. A `BET` decision is a qualified recommendation, not evidence that a wager was submitted.
