# Doctore MCP verification status

## Current acceptance policy (14-tool implementation)

This document records the current gate, not a blanket declaration that any branch is verified. Read the exact commit SHA and GitHub Actions logs. The canonical tool inventory is `EXPECTED_TOOLS` in `doctore_mcp/scripts/run_inspector_smoke_v2.py`.

Required on **one exact commit**:

1. Python compile and complete unit-test discovery: PASS.
2. Locked baseline verification and golden differential tests: PASS.
3. MCP Inspector over real stdio: `tools/list` exposes all **14/14** expected tools, and `tools/call` exercises **14/14** with no protocol errors.
4. CI report records the exact SHA and **14/14**, and downloadable logs exist.
5. Independent, blind, read-only agent-use evaluation is performed separately after freezing the public tool schemas. The evaluator must not use implementation source, regression fixtures or their answers to author tasks.

**Operational status:** CI success proves contract/transport behavior only. Live bankroll decisions remain **HOLD** until independently validated probabilities, market execution data, and the separate blind evaluation are evidenced for the exact deployment.

## Historical verification (superseded)

Earlier PR #13 at `54b8f052380b0bcc2757f88417faaa68221868af` was merged while its then-current gate was HOLD. The original session-v1 baseline had seven tools and subsequent documents referred to 8/8 or 12/12. Those counts are historical and must not be reused as current acceptance thresholds.

See `doctore_mcp/README.md`, `doctore_mcp/evaluations/README.md`, and the CI run for the target commit.
