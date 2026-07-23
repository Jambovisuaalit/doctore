# Doctore Sports Intelligence

A structured skill system for disciplined sports-market analysis. It separates live market data, model probabilities, edge calculation, risk sizing, contextual review, and reporting.

> Doctore does not allow a language model to invent a win probability. A recommendation requires a timestamped market snapshot and an externally produced, versioned model probability.

## Core pipeline

```text
Market snapshot
  -> data quality gate
  -> no-vig market baseline
  -> calibrated model probability
  -> EV and edge calculation
  -> sport-specific context review
  -> uncertainty-adjusted risk sizing
  -> execution decision
  -> CLV and performance tracking
```

## What this repository is

- An operating system for repeatable +EV analysis.
- A set of reusable Markdown skills for ChatGPT, Claude, internal agents, and analyst workflows.
- A specification for the data contract between odds feeds, prediction models, risk controls, and the explanation layer.
- A guardrail against stale data, unsupported probabilities, narrative betting, and incorrect Kelly sizing.
- A tested reference implementation of the core market mathematics.

## What this repository is not

- It is not an XGBoost model or a replacement for one.
- It does not scrape or purchase live odds automatically.
- It does not guarantee profitable bets.
- It does not authorize automatic bet placement.
- It does not treat line movement, public betting splits, or recent form as proof of edge.

## Quick start

1. Copy `PROJECT_INSTRUCTIONS.md` into the system or project instructions of the analysis agent.
2. Copy `config/doctore.example.yaml` and adjust bankroll, thresholds, freshness limits, and enabled sports.
3. Load the core skills:
   - `skills/data-ingestion/SKILL.md`
   - `skills/market-baseline/SKILL.md`
   - `skills/model-probability/SKILL.md`
   - `skills/edge-detection/SKILL.md`
   - `skills/risk-management/SKILL.md`
   - `skills/performance-tracking/SKILL.md`
   - `skills/shared/data-quality-gate.md`
   - `skills/shared/anti-bias-checklist.md`
   - `skills/shared/output-format.md`
4. Load the relevant sport module.
5. Provide a timestamped odds snapshot and model output. See `examples/sample-model-output.json`.
6. Verify the mathematics with `python -m unittest discover -s tests -v`.
7. Ask the system to scan the market or evaluate a specific event.

## Supported initial domains

- MLB.
- KBO and NPB as separate calibration domains.
- Tennis.
- Soccer.
- NBA and WNBA as separate calibration domains.
- NFL.

New sports should follow the same model-boundary, data-quality, market-matching, and risk-control rules.

## Required input contract

Every actionable candidate must include:

```yaml
event_id: string
sport: MLB | KBO | NPB | TENNIS | SOCCER | NBA | WNBA | NFL
market: string
selection: string
book: string
odds_decimal: number
market_snapshot_at: ISO-8601
opposing_outcomes:
  - selection: string
    odds_decimal: number
model_probability: number
model_version: string
model_generated_at: ISO-8601
calibration_method: string
```

Additional sport-specific fields are required where relevant, such as confirmed starting pitchers, tennis surface, projected lineups, weather, or player availability.

## Mathematical definitions

For decimal odds `d`, calibrated model probability `p_model`, and uncertainty-adjusted sizing probability `p_sized`:

```text
Raw implied probability = 1 / d
EV = p_model * d - 1
Full Kelly fraction = (p_sized * d - 1) / (d - 1)
```

For a two-way market with decimal odds `d1` and `d2`:

```text
q1 = 1 / d1
q2 = 1 / d2
No-vig P1 = q1 / (q1 + q2)
No-vig P2 = q2 / (q1 + q2)
Edge in percentage points = Model P - No-vig market P
```

Do not substitute no-vig market probability for the bet's break-even probability when calculating EV. Do not size directly from an unadjusted model probability when uncertainty shrinkage is required. See `docs/mathematics.md` and `src/doctore_math.py`.

## Default Doctore controls

Defaults are conservative until the model demonstrates stable calibration and positive CLV over a meaningful sample.

```yaml
minimum_ev: 0.03
minimum_edge_pp: 0.015
kelly_fraction_uncalibrated: 0.10
kelly_fraction_validated: 0.25
kelly_fraction_maximum: 0.60
max_bankroll_per_bet: 0.02
max_open_exposure: 0.10
max_daily_turnover: 0.25
max_league_exposure: 0.15
max_rolling_3d_turnover: 0.40
```

The maximum Kelly fraction is not a default. It is permitted only when model calibration, sample size, market liquidity, and CLV evidence satisfy the risk-management skill.

## Decision states

| State | Meaning |
|---|---|
| `BET` | All required data is valid and the candidate clears EV and risk gates. |
| `WATCH` | Candidate is close, but price, confirmation, or timing is not yet executable. |
| `PASS` | No qualifying edge or risk-adjusted value. |
| `BLOCKED` | Required data is missing, stale, contradictory, or unsupported. |

## Repository structure

```text
doctore/
├── .github/workflows/test.yml
├── README.md
├── PROJECT_INSTRUCTIONS.md
├── CONTRIBUTING.md
├── LICENSE
├── config/
│   └── doctore.example.yaml
├── docs/
│   └── mathematics.md
├── examples/
│   ├── sample-model-output.json
│   ├── sample-daily-output.md
│   └── sample-bet-log.csv
├── src/
│   └── doctore_math.py
├── tests/
│   └── test_doctore_math.py
└── skills/
    ├── data-ingestion/SKILL.md
    ├── market-baseline/SKILL.md
    ├── model-probability/SKILL.md
    ├── edge-detection/SKILL.md
    ├── risk-management/SKILL.md
    ├── performance-tracking/SKILL.md
    ├── shared/
    │   ├── data-quality-gate.md
    │   ├── anti-bias-checklist.md
    │   └── output-format.md
    └── sport-specific/
        ├── mlb/SKILL.md
        ├── kbo-npb/SKILL.md
        ├── tennis/SKILL.md
        ├── soccer/SKILL.md
        ├── nba/SKILL.md
        └── nfl/SKILL.md
```

## Primary KPIs

- Average CLV in probability and price terms.
- Positive CLV rate.
- Realized ROI and yield.
- Brier score and log loss.
- Calibration error by probability bucket.
- EV capture by sport, market, model version, and time-to-start.
- Maximum drawdown.
- Rejection rate caused by stale or incomplete data.

## Non-negotiable rules

1. No model probability means no bet.
2. No timestamp means no bet.
3. Stale price means refresh or pass.
4. No-vig price is a baseline, not a predictive model.
5. Confidence labels never override EV or risk limits.
6. Correlated positions must be aggregated before sizing.
7. Results alone do not validate a model; calibration and CLV matter.
8. The explanation layer may reject a model candidate but may not manufacture a new probability.

## License

MIT. Use, modify, and extend the system while preserving the license notice.

## Responsible use

Sports betting involves financial risk. Use hard exposure limits, maintain complete records, comply with local law, and stop when the process or behavior becomes undisciplined.
