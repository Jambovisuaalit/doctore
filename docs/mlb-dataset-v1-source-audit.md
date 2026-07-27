# MLB dataset v1 source audit — 2026-07-27

## Current source inventory

| Source | Coverage | Usable rows | Decision |
|---|---|---:|---|
| `MLB ODDS DATA 2023` | 2012–2021 closing market rows | 45,530 team rows / 22,765 games | Keep as odds input |
| `Clean_MLB_Data.csv` | 2023 | 2,444 candidate game rows | Reject as canonical input |
| `RAW_LEGACY — MLB Games Scrape — 2025` | 2025-03-18–2025-06-22 | 1,173 final-score lines | No overlap with odds |
| `all_data_mlb` | 2025 aggregates | team-level tables | No exact game/market join |

## Hard findings

1. The odds file title is misleading. Its rows cover 2012–2021, not 2023.
2. Total, Over price and Under price are populated on all 45,530 odds rows.
3. The odds file is team-level. A canonical game requires two exact lookups after
   the result source establishes away/home identity and game number.
4. The 2023 clean sheet is not clean: its first 20 rows contain Python source
   fragments and broken headers.
5. The same 2023 sheet contains current-game box-score data, including final
   runs. Those fields are post-settlement and cannot enter pre-game features.
6. Current Drive result sources do not overlap the 2012–2021 odds period.
7. The exact closing-price capture time is not stored. A deterministic pre-start
   proxy can support research reconstruction but not production timing claims.

## Current gate

```json
{
  "accepted_canonical_rows": 0,
  "decision": "BLOCKED",
  "reason_codes": [
    "MISSING_2012_2021_FINAL_RESULTS_WITH_STABLE_GAME_ID",
    "MISSING_OBSERVED_MARKET_CAPTURE_TIMESTAMP",
    "SAME_SLATE_GROUPED_WALK_FORWARD_REQUIRED"
  ]
}
```

## Required acquisition

Generate the result contract for 2012–2021:

```bash
python scripts/export_mlb_statsapi_results.py \
  --start-year 2012 \
  --end-year 2021 \
  --output data/raw/mlb-results-2012-2021.csv
```

Then run the exact-identity builder. No date-and-team-only fallback is allowed.
