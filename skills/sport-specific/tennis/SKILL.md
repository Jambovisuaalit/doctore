---
name: tennis
description: Validate Doctore tennis betting candidates for match winner, set, game handicap, totals, and player markets. Use when the user asks to analyze tennis odds or kertoimet, ATP, WTA, Challenger, ITF, surface, retirement rules, best-of format, fatigue, travel, injury, or whether a tennis match has already started.
license: MIT
compatibility: Agent Skills filesystem. Current tournament and player data may require network tools.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# Tennis context validation

Validate the exact event and market contract. Tennis identity and retirement rules are frequent failure points.

1. Read `references/required-inputs.md`.
2. Confirm tournament, round, surface, indoor/outdoor, format, start status, and player identity.
3. Confirm book-specific retirement, walkover, and settlement rules.
4. Confirm the model target matches match, set, handicap, or total market.
5. Treat unresolved injury, fitness, or schedule changes as WATCH or BLOCKED.
6. Preserve the supplied model probability; do not create a manual surface or fatigue adjustment.
