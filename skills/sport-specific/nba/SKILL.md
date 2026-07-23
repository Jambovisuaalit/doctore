---
name: nba
description: Validate Doctore NBA and WNBA betting candidates for moneyline, spread, totals, team totals, and player props. Use when the user asks to analyze NBA or WNBA odds, kertoimet, injuries, active roster, projected starters, minutes, back-to-back rest, travel, pace, or player availability before a basketball bet.
license: MIT
compatibility: Agent Skills filesystem. Current injury and lineup data may require network tools.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# NBA and WNBA context validation

Treat NBA and WNBA as separate calibration domains.

1. Read `references/required-inputs.md`.
2. Confirm event status, active roster, projected starters, late scratches, minutes assumptions, rest, travel, and schedule context.
3. For props, confirm player identity, line, stat definition, overtime treatment, and minutes projection cutoff.
4. Request a refreshed model after material availability or minutes changes.
5. Do not manually shift spreads or probabilities from generic injury tables.
