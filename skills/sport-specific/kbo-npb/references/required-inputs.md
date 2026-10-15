# KBO/NPB required inputs

- league-specific event identity and season phase;
- model trained and calibrated for the exact league and market;
- current odds, complete outcome set, and settlement rules;
- confirmed starters and recent role changes;
- lineup and foreign-player availability;
- bullpen usage, doubleheaders, travel, park, weather, and roof state;
- tie and innings-limit treatment.

## KBO travel inputs

Read `travel-stress.md` before computing a KBO travel feature.

Required primitives:

- previous completed game venue and completion timestamp;
- current venue and scheduled start timestamp;
- door-to-door travel hours;
- arrival timestamp or hours since arrival;
- actual travel mode and whether it is confirmed;
- traveler scope: `team` or `starting_pitcher`;
- consecutive away-series count;
- previous-game extra-innings flag;
- point-in-time source and observation timestamp.

Do not infer KTX merely because a rail route exists. Unknown transport uses the
conservative team-bus prior and must emit a warning. A starter traveling early
by KTX does not change the team-level travel mode.

## KBO bullpen inputs

Read `bullpen-stress.md` before computing the team-level composite Stress Index.
For every projected relief pitcher, require:

- stable pitcher ID;
- leverage role known at the feature cutoff;
- pitches thrown in `0–24h`, `24–48h`, and `48–72h` windows;
- consecutive days used;
- projected availability and confirmation state;
- source game IDs, game-end timestamps, and observation timestamp.

Use only appearances completed before `feature_cutoff_at` and exclude the current
event. Doubleheader Game 1 workload may enter Game 2 only when Game 1 ended before
the Game 2 cutoff. Do not use final postgame roles or availability during
historical backfill.

The combined team index requires `team` travel scope. Starting-pitcher KTX or
other early travel remains a separate feature and cannot reduce bullpen stress.
Bullpen stress is excluded from first-five markets unless the target explicitly
includes relief innings.
