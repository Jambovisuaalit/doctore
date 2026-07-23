---
name: data-quality-gate
description: Validate Doctore betting candidates before any EV or stake calculation. Use when checking whether odds, model outputs, timestamps, event identity, lines, settlement rules, lineups, starters, injuries, weather, or portfolio exposure are complete and fresh enough for BET, WATCH, PASS, or BLOCKED status.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ for the bundled candidate validator.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: validation
allowed-tools: Read Grep Glob Bash(python:*)
---

# Data quality gate

Run this gate before market normalization, EV, or sizing.

## Workflow

1. Confirm event identity, start time, and pregame/in-play status.
2. Confirm market identity, line, period, settlement rules, book, and synchronized outcome set.
3. Confirm price age against the configured freshness limit.
4. Confirm model target, selection, version, generation time, and calibration status.
5. Confirm sport-specific assumptions that can invalidate the model.
6. Confirm current portfolio state before sizing.
7. Run `scripts/validate_candidate.py INPUT.json` for mechanical checks.
8. Assign `VALID`, `WATCH`, or `BLOCKED`. Do not estimate missing critical values.

## References

- Read `references/blocking-rules.md` for the full blocking matrix.
- Read `references/status-semantics.md` when choosing VALID, WATCH, or BLOCKED.
