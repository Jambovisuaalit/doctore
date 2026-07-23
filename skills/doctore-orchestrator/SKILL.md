---
name: doctore-orchestrator
description: Route complete Doctore sports-betting workflows without loading unrelated skills. Use when the user asks to scan today's markets, analyze one or more bets, find value bets, arvioi vedot, produce Doctore picks, or run the full BET/WATCH/PASS/BLOCKED decision process across supported sports.
license: MIT
compatibility: Agent Skills filesystem. Designed to compose other Doctore skills through progressive disclosure.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: orchestration
allowed-tools: Read Grep Glob Skill
---

# Doctore orchestrator

Route the task. Do not preload every skill and do not perform unsupported calculations yourself.

## Routing workflow

1. Identify the requested sport, market, decision type, and whether current data is required.
2. Read `references/skill-map.md` and activate only the matching skills.
3. Use one sport skill per event unless the request explicitly spans multiple sports.
4. Require `data-quality-gate`, `market-baseline`, `model-probability`, `edge-detection`, `anti-bias-audit`, `risk-management`, and `output-format` for an actionable BET.
5. Activate `performance-tracking` only for logging, settlement, KPI, CLV, calibration, or review work.
6. Stop at the first hard BLOCKED condition instead of loading downstream skills unnecessarily.

## Efficiency rules

- Skip data ingestion when the user already supplied complete current structured data.
- Skip risk management for a pure mathematical EV question unless stake sizing is requested.
- Skip output formatting when the user requests only a calculation or audit.
- Never activate unrelated sport skills as background context.
