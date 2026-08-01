# Doctore MCP session-v1 baseline

This directory preserves the repository baseline used for differential verification of the original seven-tool MCP behavior.

## Provenance status

The first real GitHub Actions P0 verification exposed that the previously documented archive/source hashes did not match the bytes actually committed to the repository. The repository does not contain a separate byte-identical copy of the user-provided `Liitetty teksti(1).txt` source that could independently re-establish the old hash claim.

The committed Base64 archive is therefore preserved as evidence and represented explicitly:

- Source reference: user-provided session artifact `Liitetty teksti(1).txt`
- Original description: 668-line seven-tool server
- **Canonical whitespace-free Base64 archive SHA-256:** `4d69e0f2d8656b8538d2669692bc1be7c4cdd5a0ba7010274c9c1957262660e9`
- **Archived decoded payload SHA-256:** `2fdebce572f359df841ff55a4d67c2a59848f6264dd5e27ab15f8a081d570bfb`
- **Minimally repaired executable baseline SHA-256:** `571b130b6a6d81066a45511722948efd6908095011356055884d9226e75aede7`
- Legacy recorded source SHA-256: `305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395` — retained as an unreproduced historical claim, not an active integrity gate
- Legacy recorded Base64 SHA-256: `78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32` — retained as an unreproduced historical claim, not an active integrity gate
- Tool count: 7
- Output format: JSON-encoded strings
- Decision math: direct calls to `src/doctore_math.py`
- Settlement tool: not implemented

## P0 corruption finding and repair layer

The decoded committed payload was not executable Python. P0 CI found three deterministic corruption fragments:

1. one `try:` line in `doctore_evaluate_bet` was indented by seven spaces instead of eight;
2. one orphaned fragment `rams.model_output.get("brier_score"),` appeared immediately after the complete `brier_score` field;
3. one standalone `-` line appeared between two comment lines before the portfolio-status section.

These fragments are repaired only at materialization time. The four Base64 part files remain unchanged. Each repair has an exact byte precondition and must occur exactly once; otherwise materialization fails closed. The repaired output compiles as Python and is then used by the golden differential suite.

This repair is not evidence that the repaired file is byte-identical to the historical user-provided source. It is the smallest reproducible transformation needed to make the committed repository baseline executable. Behavioral compatibility remains a separate test requirement.

## Integrity semantics

`materialize.py` verifies three deterministic layers:

1. the four committed Base64 parts, after removing Base64-insignificant whitespace, must hash to the locked canonical archive SHA-256;
2. decoding those parts must reproduce the locked archived-payload SHA-256;
3. applying exactly the three documented repairs must reproduce the locked repaired-source SHA-256.

Behavioral equivalence is then tested separately by the golden differential suite. A hash PASS does not replace differential verification.

## Verify and materialize

```bash
python doctore_mcp/baseline/session_v1/materialize.py --verify-only
python doctore_mcp/baseline/session_v1/materialize.py \
  --output /tmp/doctore-session-v1/server.py
python -m py_compile /tmp/doctore-session-v1/server.py
```

Any edit that changes the canonical Base64 payload, archived decoded payload, repair preconditions or repaired output fails verification.

## Locked tools

1. `doctore_parse_pinnacle_table`
2. `doctore_check_data_quality`
3. `doctore_load_model_prediction`
4. `doctore_calculate_edge_and_stake`
5. `doctore_evaluate_bet`
6. `doctore_log_bet`
7. `doctore_portfolio_status`

This baseline is retained for differential tests only. It must not be promoted to production or silently modified to match the hardened implementation.
