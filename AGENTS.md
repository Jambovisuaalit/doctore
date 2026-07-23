# Doctore agent architecture

## Progressive disclosure policy

Do not preload all sports or analytical instructions.

1. Discover skills from YAML `name` and `description` metadata only.
2. Activate the smallest set of skills required by the user request.
3. Read a skill's `SKILL.md` only after its description matches the task.
4. Read files in `references/` only when the active workflow points to them.
5. Execute files in `scripts/` for deterministic validation and calculations instead of reproducing formulas manually.
6. Never load unrelated sport skills in the same analysis.

## Mandatory composition order

For an actionable betting decision, compose only the necessary skills in this order:

1. `data-ingestion` when data must be fetched, refreshed, or normalized.
2. `data-quality-gate` for freshness, completeness, identity, and market matching.
3. `market-baseline` for implied probability and no-vig normalization.
4. `model-probability` for model provenance and calibration validation.
5. One relevant sport skill: `mlb`, `kbo-npb`, `tennis`, `soccer`, `nba`, or `nfl`.
6. `edge-detection` for EV, edge, and minimum-price calculation.
7. `anti-bias-audit` before approval.
8. `risk-management` for stake and portfolio caps.
9. `output-format` for BET, WATCH, PASS, or BLOCKED output.
10. `performance-tracking` only when creating or reviewing records and KPIs.

## Global invariants

- A language model must not invent or silently modify a model probability.
- No timestamped executable price means no actionable bet.
- No-vig market probability is a reference baseline, not the Doctore model.
- Context can reject a model candidate but cannot turn negative EV into a bet.
- Use deterministic scripts for no-vig, EV, Kelly, exposure, and performance calculations.
- Do not infer sharp action from line movement without verified source data.
- Do not claim live data unless it was retrieved or supplied in the current analysis.

## Tool policy

`allowed-tools` in skill frontmatter is an experimental pre-approval hint. It is not a universal security boundary. The hosting runtime must separately enforce permissions, network access, filesystem scope, secrets handling, and automatic execution policy.
