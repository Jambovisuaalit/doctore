---
name: mlb
description: Validate Doctore MLB betting candidates for moneyline, run line, totals, first five innings, and related baseball markets. Use when the user asks to analyze an MLB game, MLB odds or kertoimet, starting pitchers, bullpen availability, handedness splits, lineups, park, roof, umpire, or weather before a baseball bet.
license: MIT
compatibility: Agent Skills filesystem. Current external data may require network tools. Python is optional for supplied validators.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# MLB context validation

Validate whether the live event still matches the MLB model's feature assumptions. Do not manually invent run or probability adjustments.

## Workflow

1. Read `references/required-inputs.md` and confirm the fields required by the requested market.
2. Confirm listed/action pitcher settlement rules and current starter status.
3. Confirm lineup compatibility, handedness assumptions, bullpen availability cutoff, park/roof, weather, and event status.
4. Read `references/market-rules.md` only for the requested market type.
5. Return `VALID`, `WATCH`, or `BLOCKED` with the exact changed assumption.
6. Preserve the supplied model probability; request a refreshed model when a critical feature changed.

Do not load KBO/NPB rules for MLB events.
