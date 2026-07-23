# Portfolio limits

Default hard limits:

```yaml
max_bankroll_per_bet: 0.02
max_open_exposure: 0.10
max_daily_turnover: 0.25
max_league_exposure: 0.15
max_rolling_3d_turnover: 0.40
```

Group dependent positions by event, team, player, weather scenario, lineup assumption, pitcher/goalie, and shared model error. Do not assume parlays or same-game legs are independent. The final stake is the minimum remaining capacity across all applicable caps.
