# Doctore MCP verification status

Commit-specific verification must be read from the PR head and CI results. This file records what has and has not been demonstrated during development.

## Demonstrated locally

- Original session-v1 source SHA-256 matches the archived baseline.
- Archived baseline source compiles after materialization.
- New modular Python sources compile in the focused development workspace.
- Golden differential suite passed 7/7 using isolated baseline and hardened modules with a local MCP host stub.
- Focused hardened workflow passed by direct Python calls:
  - canonical `BET` evaluation;
  - per-bet cap of 1,000 EUR on 50,000 EUR bankroll;
  - stake-increase rejection;
  - canonical approval logging;
  - closing snapshot settlement;
  - positive price CLV and realized P/L;
  - settled portfolio aggregation.

These focused runs validate core Python behavior but are not substitutes for the real MCP transport test.

## Not demonstrated

- Full repository unit test discovery against the exact GitHub branch checkout.
- MCP Inspector `tools/list` and `tools/call` 8/8 through real stdio transport.
- Blind evaluation accuracy.

## Infrastructure blockers

- The execution environment cannot resolve GitHub/npm/PyPI hosts, so it cannot clone the branch or install `mcp[cli]` and Inspector packages.
- GitHub Actions jobs terminate before the first workflow step and provide no step logs.

## Merge gate

```text
full_repository_unit_tests = PASS
mcp_inspector_tools_list = 8/8
mcp_inspector_tool_calls = 8/8
blind_evaluation_created = false until all previous gates pass
```

Current decision: **HOLD**.
