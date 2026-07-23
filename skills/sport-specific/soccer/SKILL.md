---
name: soccer
description: Validate Doctore soccer betting candidates for 1X2, Asian handicap, totals, both teams to score, draw-no-bet, team totals, and related football markets. Use when the user asks to analyze football or soccer odds, kertoimet, projected lineups, injuries, rotation, xG, venue, weather, schedule congestion, or settlement rules.
license: MIT
compatibility: Agent Skills filesystem. Current lineup and competition data may require network tools.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# Soccer context validation

1. Read `references/required-inputs.md`.
2. Confirm competition, fixture identity, venue, regulation-time definition, and event status.
3. Confirm projected or official lineups, rotation, key absences, formation assumptions, and schedule context against the feature cutoff.
4. Read `references/market-rules.md` only for the requested market.
5. Request a refreshed probability when material lineup assumptions changed.
6. Do not manually add xG, injuries, or motivation to a probability already produced by the model.
