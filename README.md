# Doctore Sports Intelligence — Agent Skills

A modular Agent Skills package for data-driven sports-market analysis. The repository uses progressive disclosure: agents discover skills from compact YAML metadata, load only the selected `SKILL.md`, and access `references/` or execute `scripts/` only when required.

## Architecture

```text
skills/
├── doctore-orchestrator/
│   ├── SKILL.md
│   └── references/
├── data-ingestion/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
├── data-quality-gate/
├── market-baseline/
├── model-probability/
├── edge-detection/
├── risk-management/
├── performance-tracking/
├── anti-bias-audit/
├── output-format/
└── sport-specific/
    ├── mlb/
    ├── kbo-npb/
    ├── tennis/
    ├── soccer/
    ├── nba/
    └── nfl/
```

Each skill root contains a required `SKILL.md`. Detailed domain rules live in one-level `references/` files. Deterministic validators and calculators live in `scripts/` and return machine-readable JSON.

## Progressive disclosure

1. Startup loads only `name` and `description` metadata.
2. A matching user request activates the relevant `SKILL.md`.
3. The skill reads focused references or runs scripts only when its workflow calls for them.
4. The orchestrator stops at the first hard BLOCKED condition instead of loading unnecessary downstream skills.

Read `AGENTS.md` for the composition policy.

## Core safety boundary

Doctore separates:

```text
live market data -> data quality -> no-vig market baseline
-> externally produced calibrated model probability
-> sport validation -> EV -> bias audit -> risk sizing -> output -> tracking
```

The language model may explain, audit, reject, and route. It may not invent or silently alter the win probability.

## Frontmatter

Every skill defines:

- `name`
- specific trigger-oriented `description`
- `license`
- `compatibility`
- `metadata`
- `allowed-tools`

`allowed-tools` is an experimental pre-approval hint whose enforcement varies by runtime. Treat it as defense in depth, not the only permission control. Configure actual tool permissions in the hosting agent, API, or SDK.

## Validation

```bash
python scripts/validate_skills.py
python -m unittest discover -s tests -p 'test_*.py'
```

For strict specification validation, use the official reference implementation:

```bash
uvx --from git+https://github.com/agentskills/agentskills#subdirectory=skills-ref \
  skills-ref validate skills/data-ingestion
```

Run the command for each skill directory or use the bundled validator for repository-wide checks.

## Installation

Copy individual skill directories into the target agent's skill directory. Install only the skills required by the deployment.

Example for Claude Code:

```bash
mkdir -p ~/.claude/skills
cp -R skills/data-ingestion ~/.claude/skills/
cp -R skills/data-quality-gate ~/.claude/skills/
cp -R skills/market-baseline ~/.claude/skills/
```

For the complete Doctore workflow, install the orchestrator, core analytical skills, and only the sport skills the deployment supports.

## Decision states

- `BET`: all data, model, edge, context, bias, and risk gates pass.
- `WATCH`: a precise price or confirmation trigger is pending.
- `PASS`: no qualifying risk-adjusted edge.
- `BLOCKED`: critical data is absent, stale, contradictory, or mismatched.

## License

MIT.
