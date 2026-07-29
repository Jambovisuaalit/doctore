# Doctore sport-specific context agents

## Boundary

Context agents are gate-only components. They must never modify model probability, no-vig probability, EV, Kelly, stake, or canonical decision calculations.

Every agent returns exactly:

- `status`: `CLEAR | WATCH | BLOCKED | UNCERTAIN`
- `reason_codes`
- structured `evidence`
- optional notes

Contract: `doctore.context-gate.v1`.

## MCP tool

`doctore_run_context_gate`

The input contains exact event/market identity, timestamps, evidence records, and structured signals. The output is deterministic for the supplied input.

## Implemented adapters

### MLB context

Checks only operational context gates such as:

- game status
- pregame/in-play state
- starting pitcher confirmation or scratch
- confirmed lineup
- weather risk
- roof-status availability when required

### KBO context

Checks:

- game status
- pregame/in-play state
- starting pitcher and lineup confirmation
- weather risk
- travel-stress status

Travel stress is a gate signal only. It does not change probabilities.

### Tennis withdrawal risk

Checks only withdrawal/fitness risk evidence:

- official withdrawal
- recent retirement
- recent medical timeout
- negative or limited fitness statement
- recent pullout or late replacement
- recurring injury match
- completeness of the seven-day research window

Official withdrawal blocks. Other credible fitness signals produce WATCH. Incomplete research produces UNCERTAIN.

## Reserved adapters

NBA and soccer are registered as fail-closed placeholders. They return `BLOCKED / CONTEXT_AGENT_NOT_IMPLEMENTED` until their sport-specific contracts, evidence rules, fixtures, and validation gates exist.

## Orchestrator integration rule

The slate orchestrator may pass the context output into `sport_context`, but the canonical decision core remains the only component allowed to interpret it. A context agent itself cannot call calculation, logging, or settlement tools.

## Verification

```bash
python -m compileall -q src scripts doctore_mcp tests
python -m unittest discover -s tests -p 'test_*.py' -v
python doctore_mcp/scripts/run_inspector_smoke.py --repo "$PWD"
```

Update Inspector expectations because the MCP server now exposes an additional read-only context-gate tool.
