# MLB player-hits data foundation v1

This vertical slice implements only the data foundation required by a future
player-hits probability model:

1. canonical settled plate-appearance rows;
2. exact `gamePk`, player and `atBatIndex` identity;
3. timestamped pregame lineup and probable-starter snapshots.

It does **not** implement a PA-count model, per-PA hit model, bullpen mixture,
Poisson-binomial aggregation, calibration, odds comparison, EV or staking.

## Identity

```text
event_id = mlb:{gamePk}
plate_appearance_id = mlb:{gamePk}:ab:{atBatIndex}
player_id = mlbam:{personId}
slate_id = mlb-slate:{officialDate}
```

No player-name/date fallback join is allowed.

## Point-in-time rule

A context snapshot is training-eligible only when:

```text
observed_at <= feature_cutoff_at < scheduled_start_at
```

The postgame feed may provide actual batting order, but it is not accepted as
proof that the lineup was known pregame. Historical acquisition must preserve a
pregame feed snapshot or timecode and its observed timestamp.

## Output contract

- `contracts/mlb-pa-row.schema.json`
- `contracts/mlb-pregame-context.schema.json`
- `src/mlb_player_hits_data.py`
- `scripts/export_mlb_player_hits_data.py`

The plate-appearance dataset contains settled outcomes and is explicitly kept
separate from pregame features. A later feature builder must compute rolling
statistics using only events completed before each prediction cutoff.

## Example execution

```bash
python scripts/export_mlb_player_hits_data.py \
  --game-pk 822868 \
  --output-dir artifacts/mlb-pa/822868
```

For reproducible research, prefer a locally hash-locked feed file:

```bash
python scripts/export_mlb_player_hits_data.py \
  --feed-json data/cache/mlb-feed/822868.json \
  --extraction-generated-at 2026-07-28T05:00:00Z \
  --output-dir artifacts/mlb-pa/822868
```

## Fail-closed conditions

- non-final game for settled PA export;
- missing or duplicate `atBatIndex` identity;
- malformed team or player identity;
- observed context timestamp after feature cutoff;
- lineup or starter incompleteness;
- post-start context snapshot;
- overwrite attempt.

## Current status

```yaml
pipeline_component: MLB-HITS-01
data_foundation: implemented
real_historical_backfill: not_executed
player_hits_model: not_implemented
market_comparison: out_of_scope
production_eligible: false
recommended_stake_eur: 0
```
