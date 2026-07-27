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
