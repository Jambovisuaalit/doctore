# Metrics

```text
ROI or yield = total profit / total stake
Brier = mean((predicted_probability - outcome)^2)
Log loss = -mean(y*ln(p) + (1-y)*ln(1-p))
Probability CLV = closing_no_vig_probability - taken_break_even_probability
Price CLV ratio = odds_taken / closing_odds - 1
```

Report CLV convention explicitly. Segment by sport, competition, market, model version, probability bucket, time-to-start, and price range. Use confidence intervals and minimum sample requirements before changing production risk.
