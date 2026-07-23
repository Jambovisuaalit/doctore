---
name: nfl
description: Validate Doctore NFL betting candidates for moneyline, spread, totals, team totals, and player props. Use when the user asks to analyze NFL odds or kertoimet, quarterback status, offensive line, defensive injuries, weather, travel, rest, pace, snap projections, or football over/under markets.
license: MIT
compatibility: Agent Skills filesystem. Current injury, roster, and weather data may require network tools.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# NFL context validation

1. Read `references/required-inputs.md`.
2. Confirm event, venue, surface, roof, weather, and overtime settlement.
3. Confirm quarterback, offensive line, key skill-player, secondary, pass-rush, and special-teams assumptions against the feature cutoff.
4. Confirm travel, rest, short week, and snap/role assumptions for props.
5. Request a refreshed model after material status changes.
6. Do not apply generic point-value injury adjustments outside the production model.
