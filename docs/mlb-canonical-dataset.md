# MLB canonical full-game totals dataset

## Required chain

```text
historical odds
+ authoritative MLB schedule/results cache
+ prior-only feature construction
→ exact gamePk join
→ leakage audit
→ chronological grouped canonical CSV
→ SHA-256 training manifest
→ timestamp-grouped production runner
```

## Hard gates

- Odds adjacency is never an event identity rule.
- Every row must resolve to one MLB `gamePk` using date, away team, home team and game number.
- Both team-side odds rows must agree on total and prices.
- The odds source must prove either row-level pregame timestamps or documented pregame closing-line semantics.
- Seven-inning and other non-nine-inning games are excluded from the v1 domain.
- Same-official-date outcomes are unavailable to every game on that date. This also blocks Game 1 → Game 2 doubleheader leakage.
- Rows sharing `cutoff_group_at` form one OOS prediction, residual-pricing and calibration block.
- No synthetic microsecond ordering is permitted.

## Current Drive audit

The files currently identified do not overlap into one training dataset:

- historical odds: 2012–2021, no opponent, gamePk or captured_at;
- `Clean_MLB_Data.csv`: 2023 games, first 20 rows partially overwritten, no historical totals prices;
- `RAW_LEGACY — MLB Games Scrape — 2025`: semi-structured 2025 results;
- `all_data_mlb`: team-level aggregate snapshot, not event-level point-in-time features.

The builder therefore remains `BLOCKED` until an authoritative 2012–2021 schedule cache and odds-provenance contract are supplied.
