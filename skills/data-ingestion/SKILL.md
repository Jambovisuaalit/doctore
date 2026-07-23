---
name: data-ingestion
description: Collect and normalize timestamped sports-betting inputs for Doctore. Use when the user asks to fetch, refresh, scrape, import, or structure odds or kertoimet, schedules, injuries, weather, lineups, starting pitchers, goalies, event status, or market timestamps before analysis.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for bundled validators. Network tools are required only when current external data must be fetched.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: data
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# Data ingestion

Build an auditable input package. Do not calculate a bet from prose summaries or untimestamped prices.

## Workflow

1. Identify the event, competition, start time, status, participants, and venue.
2. Capture the complete market outcome set from one book and synchronized snapshot.
3. Capture the external model output and its version separately from market data.
4. Add sport-specific confirmations only for the requested sport.
5. Record source, source timestamp, and retrieval timestamp for every volatile input.
6. Run `scripts/validate_snapshot.py INPUT.json`.
7. Send valid output to `data-quality-gate`. Return `BLOCKED` on critical validation errors.

## Load references only when needed

- Read `references/input-contract.md` when creating or mapping an input schema.
- Read `references/freshness-policy.md` when deciding whether data is stale.
- Read `references/source-policy.md` when selecting or reconciling external sources.

## Boundaries

- Do not create a model probability.
- Do not mix prices from different lines or settlement rules.
- Do not claim a current price without a current timestamp.
- Do not load sport references unrelated to the requested event.
