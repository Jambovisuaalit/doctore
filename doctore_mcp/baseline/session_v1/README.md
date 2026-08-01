# Doctore MCP session-v1 baseline

This directory preserves the canonical repository baseline used for differential verification of the original seven-tool MCP behavior.

## Provenance status

The first real GitHub Actions P0 verification exposed that the previously documented archive/source hashes did not match the bytes actually committed to the repository. The repository did not contain a separate byte-identical copy of the user-provided `Liitetty teksti(1).txt` source that could independently re-establish the old hash claim.

Therefore the provenance is now represented explicitly rather than silently redefining history:

- Source reference: user-provided session artifact `Liitetty teksti(1).txt`
- Original description: 668-line seven-tool server
- **Canonical repository decoded source SHA-256:** `2fdebce572f359df841ff55a4d67c2a59848f6264dd5e27ab15f8a081d570bfb`
- **Canonical whitespace-free Base64 archive SHA-256:** `4d69e0f2d8656b8538d2669692bc1be7c4cdd5a0ba7010274c9c1957262660e9`
- Legacy recorded source SHA-256: `305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395` — retained as an unreproduced historical claim, not an active integrity gate
- Legacy recorded Base64 SHA-256: `78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32` — retained as an unreproduced historical claim, not an active integrity gate
- Tool count: 7
- Output format: JSON-encoded strings
- Decision math: direct calls to `src/doctore_math.py`
- Settlement tool: not implemented

No Base64 part or decoded baseline source is modified by this provenance correction. The correction changes only which hashes are claimed as reproducible from the repository.

## Integrity semantics

`materialize.py` verifies two deterministic layers:

1. the four committed Base64 parts, after removing Base64-insignificant whitespace, must hash to the locked canonical archive SHA-256;
2. decoding those parts must reproduce the locked canonical repository source SHA-256.

Behavioral equivalence is then tested separately by the golden differential suite. A hash PASS does not replace differential verification.

## Verify and materialize

```bash
python doctore_mcp/baseline/session_v1/materialize.py --verify-only
python doctore_mcp/baseline/session_v1/materialize.py \
  --output /tmp/doctore-session-v1/server.py
```

Any edit that changes the canonical Base64 payload or decoded repository baseline fails verification.

## Locked tools

1. `doctore_parse_pinnacle_table`
2. `doctore_check_data_quality`
3. `doctore_load_model_prediction`
4. `doctore_calculate_edge_and_stake`
5. `doctore_evaluate_bet`
6. `doctore_log_bet`
7. `doctore_portfolio_status`

This baseline is retained for differential tests only. It must not be promoted to production or silently modified to match the hardened implementation.
