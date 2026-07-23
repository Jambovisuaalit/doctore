---
name: mlb
description: Validate Doctore MLB betting candidates for moneyline, run line, totals, first five innings, and related baseball markets. Use when the user asks to analyze an MLB game, MLB odds or kertoimet, starting pitchers, bullpen availability, handedness splits, lineups, park, roof, umpire, or weather before a baseball bet.
license: MIT
compatibility: Agent Skills filesystem. Current external data may require network tools. Python 3.11+ and jsonschema are required for deterministic context validation.
metadata:
  author: doctore-sports
  version: "2.1.0"
  category: sport
allowed-tools: Read Grep Glob WebSearch WebFetch Bash(python:*)
---

# MLB context validation

Validate whether the timestamped event still matches the MLB model's feature assumptions. Do not manually invent run or probability adjustments.

## Workflow

1. Read `references/required-inputs.md` and confirm the fields required by the requested market.
2. Normalize current facts into `contracts/mlb-context.schema.json`.
3. Confirm listed/action pitcher settlement rules and current starter status.
4. Confirm lineup compatibility, bullpen availability, roof, weather, umpire dependency, and event identity.
5. Read `references/market-rules.md` only for the requested market type.
6. Run:

```bash
python skills/sport-specific/mlb/scripts/validate_context.py \
  --context mlb-context.json \
  --market-snapshot market-snapshot.json \
  --evaluated-at 2026-07-23T18:05:00+03:00 \
  --max-age-seconds 900
```

7. Return `VALID`, `WATCH`, or `BLOCKED` with exact reason codes.
8. Preserve the supplied model probability. A changed critical feature requires a refreshed model.
9. Pass the context document unchanged to `bet-decision-core`.

## Hard rules

- A changed starter is `BLOCKED`.
- A listed-pitcher mismatch is `BLOCKED`.
- A material lineup or required environmental mismatch is `BLOCKED`.
- Required but projected, stale, or unknown facts are `WATCH`.
- Full-game markets may require current bullpen state; F5 markets do not inherit that requirement.
- Do not load KBO/NPB rules for MLB events.
