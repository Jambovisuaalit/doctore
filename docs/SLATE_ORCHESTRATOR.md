# Doctore Autonomous Slate Orchestrator

## Scope

One MCP command sequences the existing eight Doctore tools. No new prediction logic is introduced.

## Tool order

1. `doctore_parse_pinnacle_table`
2. `doctore_portfolio_status`
3. `doctore_check_data_quality`
4. `doctore_load_model_prediction`
5. `doctore_calculate_edge_and_stake`
6. `doctore_evaluate_bet`
7. `doctore_log_bet` only after explicit matching human approval
8. `doctore_settle_bet` remains available to the orchestrator interface for the post-event lifecycle; it is not called during a pregame slate run

## Command

`doctore_run_slate`

## Guarantees

- Returns `doctore.slate-run.v1` structured output.
- Every rejected or blocked item includes one or more `reason_codes`.
- A canonical `BET` becomes `AWAITING_HUMAN_APPROVAL` unless the request includes an approval matching its `decision_id`.
- Human approval can approve, reduce, or reject; it cannot increase the canonical recommended stake because `doctore_log_bet` revalidates this rule.
- Parser, quality, model, edge/stake, evaluation, approval and logging evidence are preserved per item.
- No LLM-generated probability, EV, Kelly, price or stake calculation is introduced.

## Input model

A slate request contains:

- copied source table and capture metadata;
- bankroll, canonical portfolio state and risk policy;
- one entry per market with exact `market_id`, model artifact path, market snapshot and optional context;
- optional human approvals keyed by canonical `decision_id`.

## Reason-code examples

- `SLATE_MARKET_NOT_IN_PARSED_INPUT`
- `DATA_QUALITY_GATE_FAILED`
- source quality reasons returned by `doctore_check_data_quality`
- `MODEL_PREDICTION_LOAD_FAILED`
- canonical reason codes returned by the decision core
- `HUMAN_APPROVAL_REQUIRED`
- `HUMAN_REJECTED`
- `LOGGING_REJECTED` or the exact ledger rejection reason

## Human approval flow

Recommended production flow is two-phase:

1. Run without approvals and show all `AWAITING_HUMAN_APPROVAL` items.
2. Submit a second run with explicit approvals keyed by the immutable `decision_id`.

The ledger recomputes and validates the canonical decision before writing.

## Verification

```bash
python -m compileall -q src scripts doctore_mcp tests
python -m unittest discover -s tests -p 'test_*.py' -v
python doctore_mcp/scripts/run_inspector_smoke.py --repo "$PWD"
```

The PR must not be merged unless the complete unit suite and MCP Inspector pass on the same commit.
