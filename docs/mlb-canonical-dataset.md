# MLB canonical full-game totals dataset

## Required chain

```text
historical closing odds
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

## Odds provenance

The local Drive sheet has been identified with high confidence as an odds-only projection of Christopher Treasure's public **MLB Odds Data** dataset:

- exact header match;
- exact first six rows match the published analysis;
- exact 45,530-row count;
- exact 2012–2021 coverage.

The dataset description defines the prices as **closing numbers**. Therefore the accepted contract is:

```yaml
odds_snapshot_provenance: documented_pre_game_closing_line
odds_semantics: closing_line
bookmaker_scope: unknown_or_aggregated
row_level_captured_at: null
license_status: research_use_pending_license_review
```

This supports historical closing-market validation. It does **not** support claims that the rows are Pinnacle-specific, from one named executable sportsbook, or timestamped intraday snapshots.

Evidence is stored in:

```text
docs/audits/mlb-odds-provenance-2026-07-27.json
examples/mlb-odds-source-manifest-2012-2021.json
```

## Schedule cache acquisition

Acquire the authoritative regular-season cache with:

```bash
python scripts/fetch_mlb_schedule_cache.py \
  --start-year 2012 \
  --end-year 2021 \
  --output-dir data/cache/mlb-schedule-2012-2021
```

The acquisition module:

- requests the MLB StatsAPI schedule endpoint by season;
- preserves `gamePk`, UTC start time, official date, game number, scheduled innings, team IDs and final scores;
- excludes postponed, cancelled and suspended placeholders;
- detects conflicting duplicate `gamePk` records;
- writes one create-only JSON and SHA-256 sidecar per season;
- writes one immutable cache manifest for all seasons.

The cache files are inputs, not repository source files. Store them outside Git unless their redistribution terms have been reviewed.

## Current Drive audit

The remaining candidate files do not replace the schedule cache:

- `Clean_MLB_Data.csv`: 2023 games, first 20 rows partially overwritten, no historical totals prices;
- `RAW_LEGACY — MLB Games Scrape — 2025`: semi-structured 2025 results;
- `all_data_mlb`: team-level aggregate snapshot, not event-level point-in-time features.

## Current gate

The odds-provenance gate is now **PASS with restrictions**.

The canonical dataset remains `BLOCKED` until the 2012–2021 MLB schedule cache is successfully downloaded, hash-locked and fully joined with zero unmatched odds rows.
