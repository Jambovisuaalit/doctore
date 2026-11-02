# Doctore MCP independent blind evaluation gate

## Current gate: 14 exposed MCP tools

The canonical list is `EXPECTED_TOOLS` in `doctore_mcp/scripts/run_inspector_smoke_v2.py`. Earlier 8/8 and 12/12 counts are obsolete. No independent blind evaluation result is claimed by this document.

### Prerequisites — same exact commit

1. Full unit suite: PASS.
2. Baseline hash verification and golden differential suite: PASS.
3. Real stdio MCP Inspector `tools/list`: **14/14**.
4. Real stdio MCP Inspector `tools/call`: **14/14**, no protocol errors.
5. Freeze public tool descriptions, JSON schemas, commit SHA and environment configuration.
6. CI logs and exact-SHA verification artifact available.

### Independent evaluation protocol

- Author tasks **only** from published README, public tool descriptions and generated schemas. Do not inspect implementation code, golden fixtures, unit tests, or expected-answer internals when designing the blind tasks.
- Use a fresh isolated client session, synthetic model artifacts, synthetic odds and a temporary ledger; no bookmaker execution, paid provider calls, real account state or write operations to production paths.
- Include read-only tasks covering parsing, data quality, model provenance, no-vig/EV calculations, risk caps, context rejection, slate fail-closed behavior, portfolio read, tennis research-only and NHL source failure behavior.
- Evaluate schema-validity, correct tool selection, refusal to invent probabilities, fail-closed behavior and evidence-based explanation. Grade with a separate evaluator and store task definitions, output traces, rubric, model/runtime version and pass/fail summary.
- Keep approval, placement and settlement mutation flows in isolated deterministic regression tests; do not include destructive writes in the blind evaluation.

### Acceptance

Independent evaluation is **NOT RUN / HOLD** until a separate evaluator publishes reproducible traces and rubric results on the same frozen commit. CI/Inspector passing alone must never be represented as independent evaluation success or profitable prediction validation.

Regression coverage remains in `doctore_mcp/compatibility/golden_fixtures.json`, `doctore_mcp/compatibility/tool_contract_diff.md`, and `tests/test_doctore_mcp_differential.py`.
