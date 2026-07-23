# Calibration policy

## Minimum monitoring

Track Brier score, log loss, calibration error, reliability curves, sample size, CLV, and drift by model version and market.

## Status

- `validated`: recent out-of-sample calibration is stable for the exact sport and market domain.
- `uncalibrated`: prediction exists but calibration evidence is insufficient; use stronger shrinkage and lower Kelly.
- `unknown`: provenance or calibration status is absent; block staking.

Do not transfer calibration status between MLB and KBO/NPB, NBA and WNBA, or different market types without evidence.
