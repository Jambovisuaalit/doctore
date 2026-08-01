# Doctore MCP session-v1 baseline

This directory locks the exact seven-tool MCP server that was built and directly exercised during the original working session.

## Provenance

- Source: user-provided session artifact `Liitetty teksti(1).txt`
- Original server source length: 668 lines
- Authoritative decoded source SHA-256: `305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395`
- Canonical whitespace-free Base64 archive SHA-256: `4d69e0f2d8656b8538d2669692bc1be7c4cdd5a0ba7010274c9c1957262660e9`
- Legacy recorded Base64 SHA-256: `78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32` — retained for audit history; this value did not match the repository archive when first exercised on GitHub Actions in the P0 verification run.
- Tool count: 7
- Output format: JSON-encoded strings
- Decision math: direct calls to `src/doctore_math.py`
- Settlement tool: not implemented

The source is split only to keep repository content writes auditable. The split files are Base64 packaging for the locked source; they are not edited source code.

## Integrity semantics

`materialize.py` now verifies two independent layers:

1. the four Base64 parts, after removing Base64-insignificant whitespace, must hash to the locked canonical archive SHA-256;
2. decoding those parts must reproduce the exact original `server.py` bytes with SHA-256 `305bba59...`.

The decoded source hash is the authoritative baseline. No source bytes were changed to correct the archive-packaging hash record.

## Verify and materialize

```bash
python doctore_mcp/baseline/session_v1/materialize.py --verify-only
python doctore_mcp/baseline/session_v1/materialize.py \
  --output /tmp/doctore-session-v1/server.py
```

Any edit that changes the canonical Base64 payload or decoded source fails verification.

## Locked tools

1. `doctore_parse_pinnacle_table`
2. `doctore_check_data_quality`
3. `doctore_load_model_prediction`
4. `doctore_calculate_edge_and_stake`
5. `doctore_evaluate_bet`
6. `doctore_log_bet`
7. `doctore_portfolio_status`

This baseline is retained for differential tests only. It must not be promoted to production or silently modified to match the hardened implementation.
