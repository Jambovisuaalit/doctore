# Doctore MCP verification status

Commit-specific verification must be read from the exact commit and its CI results. This file records what has and has not been demonstrated.

## Repository state

PR #13 was merged into `main` at commit `54b8f052380b0bcc2757f88417faaa68221868af` even though its documented merge gate was still HOLD.

The merge is not verification evidence. Until the gates below pass on one exact commit, the MCP in `main` must be treated as **merged but unverified** and must not be used for live bankroll decisions.

## Demonstrated locally before merge

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

- Full repository unit test discovery against the exact merged GitHub commit.
- MCP Inspector `tools/list` and `tools/call` 8/8 through real stdio transport.
- Blind evaluation accuracy.
- A GitHub Actions run with visible workflow steps and downloadable logs for the merged commit.

## CI correction

Branch `fix/post-merge-verification-gates` replaces the diagnostic workflow's false-green behavior:

- dependency retries now fail after the final unsuccessful attempt;
- unit tests no longer use `|| true`;
- compile, baseline verification, full unit discovery and Inspector are mandatory gates;
- logs are uploaded with `if: always()` for diagnosis.

## Required verification gate

```text
exact_commit_full_repository_unit_tests = PASS
exact_commit_baseline_hash_verification = PASS
exact_commit_golden_differential_tests = PASS
exact_commit_mcp_inspector_tools_list = 8/8
exact_commit_mcp_inspector_tool_calls = 8/8
github_actions_steps_and_logs = AVAILABLE
blind_evaluation_created = false until all previous gates pass
```

Current operational decision: **HOLD — merged but not validated for live use**.
