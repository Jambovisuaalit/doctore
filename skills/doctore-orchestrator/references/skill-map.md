# Skill map

| User intent | Activate |
|---|---|
| Fetch or refresh live inputs | data-ingestion, then data-quality-gate |
| Validate candidate data only | data-quality-gate |
| Remove vig or calculate fair market baseline | market-baseline |
| Validate XGBoost or model probability | model-probability |
| Calculate EV, edge, or minimum odds | edge-detection |
| Size stake or check exposure | risk-management |
| Audit bias before approval | anti-bias-audit |
| Format picks or daily scan | output-format |
| Review ROI, CLV, calibration, or log | performance-tracking |
| MLB | mlb |
| KBO or NPB | kbo-npb |
| Tennis | tennis |
| Soccer | soccer |
| NBA or WNBA | nba |
| NFL | nfl |

## Full actionable pipeline

```text
data-ingestion? -> data-quality-gate -> market-baseline -> model-probability
-> one sport skill -> edge-detection -> anti-bias-audit
-> risk-management -> output-format -> performance-tracking record
```

The question mark means data ingestion is optional when complete, current, structured inputs are already supplied.
