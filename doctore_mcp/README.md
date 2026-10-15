# doctore_mcp

Personal stdio MCP server for the canonical Doctore betting research pipeline. It never places bets automatically. Logging requires a deterministic `BET` decision and explicit human approval or stake reduction.

## Architecture

```text
MCP client
   ↓
doctore_mcp/server.py          bootstrap + compatibility exports
   ↓
doctore_mcp/tools.py           FastMCP tool registration only
   ├── decision_adapter.py    canonical model/market/portfolio/policy orchestration
   ├── ledger.py              decision-bound logging and portfolio aggregation
   ├── settlement.py          closing snapshot, CLV and P/L
   ├── schemas.py             Pydantic and JSON Schema contracts
   ├── runtime.py             paths, time parsing, hashes and artifact policy
   └── pinnacle_parser.py     copied-table normalization
          ↓
src/bet_decision_core.py
   └── src/market_probability.py  public canonical no-vig API
```

`server.py` contains no business functions. EV, no-vig, Kelly, domain matching, drawdown and exposure rules are controlled by the canonical decision core.

## Environment

| Variable | Required | Purpose |
|---|---:|---|
| `DOCTORE_REPO_PATH` | yes | Absolute repository root |
| `DOCTORE_BET_LOG` | yes | Private canonical CSV state file; no example fallback |
| `DOCTORE_CLOSING_SNAPSHOT_LOG` | no | Closing-snapshot JSONL; defaults beside bet log |
| `DOCTORE_MODEL_ARTIFACT_ROOT` | no | Allowed model-artifact root; defaults to `<repo>/artifacts` |
| `DOCTORE_MAX_SNAPSHOT_AGE_MIN` | no | Standalone quality-gate age limit; default 5 minutes |

`prediction_path` is restricted to `DOCTORE_MODEL_ARTIFACT_ROOT` or repository `examples/`. Bet logs, snapshots, bankrolls, model artifacts and review data must not be committed.

## Install and start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DOCTORE_REPO_PATH="$PWD"
export DOCTORE_BET_LOG="$HOME/.local/share/doctore/bet-log.csv"
export DOCTORE_MODEL_ARTIFACT_ROOT="$HOME/.local/share/doctore/artifacts"
python doctore_mcp/server.py
```

## Tools

| Tool | Access | Contract |
|---|---|---|
| `doctore_parse_pinnacle_table` | read | Required explicit `captured_at`; header-aware; six selected-side snapshots per game |
| `doctore_check_data_quality` | read | Stale/future time, odds-pair completeness and contradiction gate |
| `doctore_load_model_prediction` | read | Restricted artifact path → canonical model output + schema validation |
| `doctore_calculate_edge_and_stake` | read | Canonical no-vig, EV, edge, Kelly and portfolio caps |
| `doctore_evaluate_bet` | read | Full `BET/WATCH/PASS/BLOCKED` decision and zero-safe stake |
| `doctore_log_bet` | write | Recomputes decision, checks hashes, prevents increase and duplicates |
| `doctore_settle_bet` | write | Exact-domain close, CLV, result and P/L |
| `doctore_portfolio_status` | read | Exposure, result counts, P/L and CLV summaries |
| `doctore_run_context_gate` | read | Sport context without probability changes |
| `doctore_run_slate` | mixed | Existing slate orchestration; explicit approvals required for logging |
| `doctore_tennis_data` | read/network | Optional explicit ATP/WTA source adapter; no probabilities |

All outputs are structured objects, not JSON-encoded strings.

## Baseline and compatibility

The exact original seven-tool session implementation is locked under:

```text
doctore_mcp/baseline/session_v1/
```

Verify it with:

```bash
python doctore_mcp/baseline/session_v1/materialize.py --verify-only
```

Tool-level input/output differences and classifications are documented in:

```text
doctore_mcp/compatibility/tool_contract_diff.md
doctore_mcp/compatibility/golden_fixtures.json
tests/test_doctore_mcp_differential.py
```

A difference not explicitly classified in the compatibility document is treated as a regression.

## Parser guarantees

- copied headers are skipped and diagnosed;
- every source row is `PARSED`, `SKIPPED` or `REJECTED`;
- run-line/spread handicap is stored in top-level `line`;
- selected-side snapshots retain the complete outcome set for no-vig;
- event identity includes sport, scheduled time and Pinnacle identifier;
- decimal odds must be greater than 1;
- `captured_at` is required so the read tool is actually idempotent.

## Human-in-the-loop controls

`doctore_log_bet` requires the original evaluation inputs, byte-equivalent canonical decision, `decision == BET`, explicit `APPROVE` or `REDUCE`, an approved stake no larger than the recommendation, and an unused `decision_id`.

`doctore_settle_bet` validates exact event/market/domain/line/selection/book identity and event timing. It records closing odds, closing no-vig probability, price CLV, probability CLV, result, realized P/L, content hash and complete closing snapshot.

## Verification

```bash
python -m compileall -q src scripts doctore_mcp tests
python doctore_mcp/baseline/session_v1/materialize.py --verify-only
python -m unittest discover -s tests -p 'test_*.py' -v
python doctore_mcp/scripts/run_inspector_smoke.py --repo "$PWD"
```

The Inspector script pins `@modelcontextprotocol/inspector@0.21.2`, runs `tools/list`, and calls all eleven tools through a real stdio MCP connection using isolated ledger and artifact paths.

## Blind evaluation gate

No blind evaluation XML is committed until the full unit suite and Inspector **11/11** pass on the same commit. See `doctore_mcp/evaluations/README.md`. Contract-derived cases belong to golden regression tests, not to the blind evaluation.

## Result without closing prices

Call `doctore_settle_bet` with `decision_id`, `result`, `settled_at` and
`closing_missing_reason` when no closing snapshot is available. Omit
`closing_market_snapshot`. CLV and closing fields return null; P/L and open
exposure still update. Identical retries are idempotent. Changing an already
settled result or attaching a later close is rejected, pending an explicit
revision workflow. Legacy rows without original event timing still require a
closing snapshot. Original-time retention is additive to the CSV header; the
previous header remains readable.

## Optional tennis data

Install the reviewed source with `pip install -r requirements-tennis.txt` in the
server environment. The optional adapter accepts only `get_scoreboard`,
`get_rankings`, `get_calendar`, and `get_player_info` and requires `tour=atp|wta`.
The calendar year defaults to the runtime UTC year. Player IDs must be numeric;
this source's player endpoint does not verify tour membership. Responses retain
the source payload and request time, never claim source/event freshness, and
never infer bookmaker identity, odds, or a model probability from names/rankings.
Unknown/mismatched source shapes fail closed. Normal MCP startup and CI do not
install this dependency or perform public sports-data requests.

Upstream inspected commit: `39092bbb6f146cc9d5631dabcf53f57f601fde6c`, version
`0.37.1`, MIT; runtime dependencies declared upstream: requests and feedparser.
The version guard is a compatibility check, not a package integrity guarantee;
use the pinned source requirement. Live ESPN retrieval is not part of the
fixture acceptance evidence.

For a smoke check without npm, run:

```bash
python doctore_mcp/scripts/run_stdio_smoke.py --repo "$PWD"
```

This uses the official Python MCP stdio client, invokes the same eleven tool
cases in isolated state and rejects protocol-level tool errors. Optional tennis
provider must be absent for the documented missing-dependency case.
