---
name: bet-decision-core
description: Produce a deterministic Doctore BET, WATCH, PASS, or BLOCKED decision from canonical model output, market snapshot, portfolio state, risk policy, and optional sport context. Use when the user asks to combine model probability, current odds, no-vig, EV, edge, Kelly, bankroll limits, and reason codes into one auditable betting decision.
license: MIT
compatibility: Agent Skills filesystem. Python 3.11+ and jsonschema are required.
metadata:
  author: doctore-sports
  version: "1.0.0"
  category: decision
allowed-tools: Read Grep Glob Bash(python:*)
---

# Bet decision core

Use this skill only after timestamped model, market, portfolio, and policy documents exist. The language model must not reproduce or alter the deterministic calculations.

## Workflow

1. Require:
   - `contracts/model-output.schema.json`
   - `contracts/market-snapshot.schema.json`
   - `contracts/portfolio-state.schema.json`
   - `contracts/risk-policy.schema.json`
2. Require exact event, market, sport, competition, period, line, settlement, and selection matching.
3. For MLB, require `skills/sport-specific/mlb/contracts/mlb-context.schema.json`.
4. Run `scripts/evaluate_bet.py` with an explicit `--evaluated-at` timestamp.
5. Validate the result against `contracts/decision-output.schema.json`.
6. Return the script output without changing probability, EV, Kelly, stake, decision, or reason codes.
7. Keep `human_approval_required: true`; this module never places a bet.

## Command

```bash
python skills/bet-decision-core/scripts/evaluate_bet.py \
  --model-output model-output.json \
  --market-snapshot market-snapshot.json \
  --portfolio-state portfolio-state.json \
  --risk-policy risk-policy.json \
  --sport-context mlb-context.json \
  --evaluated-at 2026-07-23T18:05:00+03:00 \
  --pretty
```

Omit `--sport-context` only when the sport has no deterministic context module.

## Decision policy

- `BET`: economics qualify, context is valid, and stake capacity remains.
- `WATCH`: economics qualify but a required sport fact is projected, stale, or unconfirmed.
- `PASS`: economics fail or the rounded stake is below the policy minimum.
- `BLOCKED`: schema, identity, timestamp, calibration, settlement, context, drawdown, or hard-cap failure.

## References

Read `references/decision-contract.md` for field ownership, probability use, and reason-code semantics.

## Prohibited behavior

- Do not invent missing inputs.
- Do not replace an external model probability with an LLM estimate.
- Do not use no-vig probability as the model probability.
- Do not use the shrunken sizing probability for EV qualification.
- Do not increase the deterministic stake.
- Do not treat `BET` as automatic execution.
