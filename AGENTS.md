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
3. `model-probability` for model provenance, calibration, and exact validation-domain checks.
4. One relevant sport skill: `mlb`, `kbo-npb`, `tennis`, `soccer`, `nba`, or `nfl`.
5. `anti-bias-audit` before approval.
6. `bet-decision-core` for canonical no-vig, EV, edge, Kelly, exposure caps, and machine-readable decision output.
7. `output-format` for channel-specific rendering of the deterministic result.
8. `performance-tracking` only when creating or reviewing records and KPIs.

The standalone `market-baseline`, `edge-detection`, and `risk-management` skills remain available for isolated calculations. For an actionable canonical JSON workflow, `bet-decision-core` is the single execution boundary and must not be duplicated manually.

## Global invariants

- A language model must not invent or silently modify a model probability.
- No timestamped executable price means no actionable bet.
- No-vig market probability is a reference baseline, not the Doctore model.
- Context can reject a model candidate but cannot turn negative EV into a bet.
- Use deterministic scripts for no-vig, EV, Kelly, exposure, and performance calculations.
- Do not infer sharp action from line movement without verified source data.
- Do not claim live data unless it was retrieved or supplied in the current analysis.
- A `BET` output is a recommendation and always requires human approval.

## Tool policy

`allowed-tools` in skill frontmatter is an experimental pre-approval hint. It is not a universal security boundary. The hosting runtime must separately enforce permissions, network access, filesystem scope, secrets handling, and automatic execution policy.
