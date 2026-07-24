# Doctore MCP session-v1 → hardened-v2 contract differential

This document compares the exact archived session-v1 baseline with the hardened MCP implementation. It does not assume that every difference is beneficial.

## Classification vocabulary

- **Compatible:** same externally relevant behavior for the golden case.
- **Intentional improvement:** changed behavior closes a documented correctness, audit or safety gap.
- **Breaking change:** an existing client input or output contract must change.
- **Regression:** the hardened implementation loses required behavior without an accepted replacement.
- **Additive:** new behavior with no session-v1 equivalent.

One difference may be both an intentional improvement and a breaking change.

## Global contract

| Area | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Tool count | 7 | 8 | Additive: settlement tool |
| Output transport | JSON encoded inside `str` | Structured Pydantic objects | Intentional improvement + breaking change |
| Decision authority | MCP-local EV/Kelly/verdict rules | `src/bet_decision_core.py` | Intentional improvement + breaking change |
| No-vig | Tool title claimed no-vig but direct edge tool had one price only | Complete outcome set through public `calculate_market_probabilities()` | Intentional improvement + breaking change |
| Bet log path | Optional; defaults to example CSV | Required private path | Intentional improvement + breaking change |
| Human decision | Not required by log tool | `APPROVE`, `REDUCE`, or `REJECT`; only canonical `BET` can log | Intentional improvement + breaking change |
| Settlement | Absent | Closing snapshot, CLV and P/L | Additive |
| MCP bootstrap | One 668-line source file | Bootstrap plus focused modules | Internal improvement; Python re-exports preserve current import surface |

## Tool-by-tool input and output changes

### `doctore_parse_pinnacle_table`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Input | `raw_table`, `sport`, `event_date: str` | Adds `timezone_name`, `competition`; `event_date: date`; requires `captured_at` | Breaking change; required `captured_at` fixes false idempotency |
| Header handling | Header-shaped rows can be parsed as games | Header rows explicitly skipped and diagnosed | Intentional improvement |
| Output granularity | Three markets per source game | Six selected-side executable snapshots per source game | Intentional improvement + breaking change |
| Spread/run line | Handicap embedded in selection and top-level `line=null` | Team selection and exact top-level line | Intentional improvement + breaking change |
| Event identity | Date + team names | Sport + scheduled time + teams + Pinnacle ID/fallback identity | Intentional improvement + breaking change |
| Output | `{snapshot_count,snapshots}` JSON string | Counts, snapshots and row diagnostics as structured output | Intentional improvement + breaking change |

### `doctore_check_data_quality`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Core contradiction formula | Absolute price difference / reference price | Same | Compatible |
| Future timestamp | Can pass because negative age is not blocked | Explicitly blocked | Intentional improvement |
| One odds map omitted | Silently skips contradiction check | Blocks partial pair | Intentional improvement + breaking change |
| Missing selection in current map | Silently skips | Blocks with diagnostic | Intentional improvement + breaking change |
| Invalid decimal odds | Not validated | Blocks odds `<=1` | Intentional improvement |
| Output | JSON string, age rounded to 0.1 min | Structured output, age rounded to 0.001 min | Breaking formatting change |

### `doctore_load_model_prediction`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Path access | Any readable local path | Restricted to model artifact root or repository examples | Intentional security improvement + breaking change |
| Adapter | `model_output_adapter` | Same canonical adapter | Compatible core transformation |
| Schema check | No canonical JSON Schema validation after adaptation | Validates `doctore.model-output.v1` | Intentional improvement |
| Output | Canonical object directly as JSON string, or ad-hoc error object | `{ok, model_output, error}` structured envelope | Intentional improvement + breaking change |

### `doctore_calculate_edge_and_stake`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Input | Probability, one price, calibration status, bankroll | Full model, market, portfolio and risk-policy package | Breaking change |
| EV | Direct `doctore_math.expected_value` | Canonical decision core | Compatible formula when inputs map exactly |
| No-vig | Not actually computable from one price | Complete market outcome normalization | Intentional improvement |
| Kelly | Raw full Kelly × hard-coded tier | Market-shrunk sizing probability, policy tier and portfolio caps | Intentional improvement + breaking change |
| Minimum EV | `>0` | Versioned risk-policy threshold | Intentional improvement + breaking change |
| Exposure caps | None | Per-bet, open, daily, league, rolling and correlation caps | Intentional improvement |
| Non-BET stake | Can be nonzero for unknown status | Always zero in MCP output | Intentional improvement + breaking change |
| Output | Small JSON string | Structured economics, no-vig, reasons, caps and decision ID | Intentional improvement + breaking change |

### `doctore_evaluate_bet`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Input | One simplified snapshot, model output, selection and bankroll | Exact canonical model, market, portfolio, policy and optional sport context | Breaking change |
| Domain matching | No event/market/line/period/settlement matching | Exact matching and validation-domain matching | Intentional improvement |
| Freshness | Checks only market snapshot wall-clock age | Evaluated-at-relative market/model/portfolio freshness | Intentional improvement + breaking change |
| Verdict vocabulary | `BET/PASS/BLOCKED` | `BET/WATCH/PASS/BLOCKED` | Additive + breaking for strict clients |
| Output | Selected summary as JSON string | Full canonical decision plus zero-safe stake | Intentional improvement + breaking change |

### `doctore_log_bet`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Input | Caller supplies arbitrary event, market, probability metadata and stake | Original evaluation, canonical decision, human decision and optional reduced stake | Intentional improvement + breaking change |
| Decision verification | None | Recomputes exact decision and verifies audit hashes | Intentional improvement |
| Stake increase | Allowed | Rejected | Intentional improvement |
| Duplicate decision | Allowed | Rejected by `decision_id` | Intentional improvement |
| Persistence | Direct CSV append | Locked atomic canonical CSV update | Intentional improvement; CSV remains mutable state rather than an append-only event ledger |
| Output | JSON string with row | Structured status and reason | Breaking change |

### `doctore_portfolio_status`

| Contract | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| Open exposure | `stake` column | Human-approved stake | Intentional improvement + log-schema breaking change |
| Settled metrics | Count, win rate, average price CLV | Adds decisive count, P/L, price and probability CLV, result counts | Additive output fields + strict-shape breaking change |
| Output | JSON string | Structured object | Breaking change |

### `doctore_settle_bet`

No session-v1 equivalent. Hardened-v2 requires a complete exact-domain closing market snapshot and calculates closing no-vig probability, price CLV, probability CLV and realized P/L. Classification: **Additive**.

## Golden differential classifications

| Golden case | session-v1 | hardened-v2 | Classification |
|---|---|---|---|
| One headerless MLB game | 3 market objects | 6 selected-side snapshots | Intentional improvement + breaking change |
| Header + one MLB game | Header may become pseudo-game | Header skipped with diagnostic | Intentional improvement |
| MIN 2.28 vs 2.08 | `BLOCKED` | `BLOCKED` | Compatible |
| Referenced selection missing from current odds | `PASS` | `BLOCKED` | Intentional improvement + breaking change |
| Validated p=0.60 at 1.90, bankroll 50k | `BET`, stake 1944.44 | `BET`, stake capped at 1000.00 | Intentional improvement + breaking change |
| Unknown p=0.60 at 1.90 | `PASS`, stake 777.78 | `BLOCKED`, stake 0 | Intentional improvement + breaking change |
| Exact market-domain mismatch | Not detected by baseline workflow | `BLOCKED` | Intentional improvement + breaking change |
| Arbitrary direct log call | Accepted | Rejected unless canonical `BET` and human-approved | Intentional improvement + breaking change |

## Regression status

No accepted regression is expected in the committed golden set. A differential test failure that is not listed above is classified as **regression by default** and blocks merge until this document is explicitly amended with justification.
