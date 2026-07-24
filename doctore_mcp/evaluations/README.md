# Doctore MCP blind evaluation gate

No blind MCP evaluation is committed yet.

The previous `readonly_evaluation.xml` was removed because it was authored from implementation code and unit-test fixtures. It was a contract regression suite, not a blind evaluation of whether an LLM can use the documented tools effectively.

Regression coverage now lives in:

- `doctore_mcp/compatibility/golden_fixtures.json`
- `doctore_mcp/compatibility/tool_contract_diff.md`
- `tests/test_doctore_mcp_differential.py`

## Preconditions for a new blind evaluation

A new evaluation XML may be created only after all of the following are evidenced on the same commit:

1. Full repository unit suite passes.
2. MCP Inspector smoke suite returns `8/8` tools over stdio.
3. Tool descriptions and generated input/output schemas are frozen for the evaluation run.
4. The evaluation author inspects only public documentation, tool names, descriptions and schemas—not the MCP implementation source or existing unit fixtures.
5. Questions are read-only, independent, non-destructive and have stable scalar answers.

## Required evidence

```text
unit_tests: PASS
inspector_tools_list: 8/8
inspector_tools_call: 8/8
blind_eval_created_after_gate: true
```

Until these conditions are met, this directory intentionally contains no evaluation XML.
