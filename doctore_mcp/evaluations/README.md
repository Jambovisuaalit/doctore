# Doctore MCP read-only evaluations

`readonly_evaluation.xml` contains ten independent, deterministic evaluation tasks for the personal Doctore MCP server.

## Design constraints

- Every task uses only read-only tools:
  - `doctore_parse_pinnacle_table`
  - `doctore_check_data_quality`
  - `doctore_load_model_prediction`
  - `doctore_calculate_edge_and_stake`
  - `doctore_evaluate_bet`
- No task calls `doctore_log_bet` or `doctore_settle_bet`.
- Every answer is one stable value suitable for direct string comparison.
- Inputs use fixed event dates, snapshots, probabilities, risk policies and portfolio states.
- Each task is independent and does not rely on a previous task or mutated log state.
- The suite covers parser identity, snapshot counts, freshness, contradictions, model adaptation, no-vig/Kelly agreement, zero-safe PASS behavior, exact-domain blocking, exposure caps and calibration provenance.

## Run

Run from the repository root. The evaluation harness launches the stdio server; do not start it separately.

```bash
python scripts/evaluation.py \
  -t stdio \
  -c python \
  -a doctore_mcp/server.py \
  -e DOCTORE_REPO_PATH="$PWD" \
  -e DOCTORE_BET_LOG="$(mktemp -u)/doctore-eval-bets.csv" \
  -o doctore_mcp/evaluations/evaluation_report.md \
  doctore_mcp/evaluations/readonly_evaluation.xml
```

The harness additionally requires its model-provider API key, for example `ANTHROPIC_API_KEY` when using the reference evaluation script.

## Acceptance targets

| KPI | Target |
|---|---:|
| Correct answers | 10/10 |
| Write-tool calls | 0 |
| Tasks with exactly one direct-comparison answer | 10/10 |
| Parser/domain/risk safety cases passed | 100% |
| Average tool calls per task | at least 2 |

Do not treat the suite as passed until it has been run through an actual MCP client and the generated report confirms all ten answers.
