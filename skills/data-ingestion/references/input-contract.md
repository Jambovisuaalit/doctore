# Input contract

## Required event fields

```yaml
event_id: string
sport: MLB | KBO | NPB | TENNIS | SOCCER | NBA | WNBA | NFL
competition: string
event_start_at: ISO-8601
status: scheduled | delayed | postponed | started | finished
participants: [string, string]
venue: string | null
source: string
retrieved_at: ISO-8601
```

## Required market fields

```yaml
market_id: string
book: string
market_type: moneyline | spread | total | prop | 1x2 | asian_handicap
period: full_game | first_half | first_5 | set | other
line: number | null
selection: string
odds_decimal: number
snapshot_at: ISO-8601
outcomes:
  - selection: string
    odds_decimal: number
```

All outcomes must be mutually exclusive, collectively exhaustive, and governed by the same settlement rule.

## Required model fields

```yaml
model_name: string
model_version: string
target_market: string
selection: string
probability_raw: number | null
probability_calibrated: number
calibration_status: calibrated | uncalibrated | unknown
calibration_method: string | null
prediction_generated_at: ISO-8601
feature_cutoff_at: ISO-8601
validation_sample_size: integer | null
brier_score: number | null
log_loss: number | null
expected_calibration_error: number | null
```

## Required portfolio fields for sizing

```yaml
bankroll: number
open_exposure: number
daily_turnover: number
league_exposure: number
rolling_3d_turnover: number
as_of: ISO-8601
correlated_positions: []
```
