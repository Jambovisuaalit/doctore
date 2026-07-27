---
name: kbo-npb
description: Validate Doctore KBO and NPB baseball betting candidates for moneyline, run line, totals, and first-five markets. Use when the user asks about KBO or NPB odds, Korean or Japanese baseball, starting pitchers, foreign-player status, bullpen usage, travel stress, KTX or team-bus movement, park, weather, tie rules, or league-specific settlement before a bet.
license: MIT
compatibility: Agent Skills filesystem. Current external data may require network tools.
metadata:
  author: doctore-sports
  version: "2.1.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# KBO and NPB context validation

Treat KBO and NPB as separate model and calibration domains.

1. Read `references/league-differences.md` for league and settlement differences.
2. Read `references/required-inputs.md` for the requested market.
3. For KBO travel analysis, read `references/travel-stress.md` and use `src/kbo_travel_stress.py` for deterministic scoring.
4. Confirm starter, lineup, bullpen, foreign-player, weather, park, travel mode, traveler scope, and tie/overtime assumptions.
5. Block cross-league calibration transfer unless explicitly validated.
6. Preserve the supplied model probability and request a refresh after critical changes.
