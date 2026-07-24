# doctore_mcp

Personal stdio MCP server for the canonical Doctore betting research pipeline.
It does not place bets. Every logged bet requires a deterministic `BET` output
and an explicit human `APPROVE` or `REDUCE` decision.

## Architecture

```text
Pinnacle table / versioned model artifact / portfolio / risk policy
                              |
                              v
                   doctore_mcp adapters
                              |
                              v
                 src/bet_decision_core.py
                              |
                              v
            BET / WATCH / PASS / BLOCKED + decision_id
                              |
                              v
                 explicit human approval only
```

The MCP layer does not implement separate EV, no-vig, Kelly, domain matching,
or exposure logic. `doctore_calculate_edge_and_stake` and
`doctore_evaluate_bet` both call `evaluate_bet_decision()` from the repository.

## Required environment

| Variable | Required | Purpose |
|---|---:|---|
| `DOCTORE_REPO_PATH` | yes | Absolute path to the Doctore repository root |
| `DOCTORE_BET_LOG` | yes | Private canonical CSV bet log; no sample fallback exists |
| `DOCTORE_CLOSING_SNAPSHOT_LOG` | no | Closing-snapshot JSONL path; defaults beside the bet log |
| `DOCTORE_MAX_SNAPSHOT_AGE_MIN` | no | Standalone quality-gate freshness limit, default 5 minutes |

An old bet log with the legacy CSV header is rejected. Migrate it or use a new
private path. Do not commit bet logs, closing snapshots, bankroll values, model
artifacts, or review data.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r doctore_mcp/requirements.txt
```

## Start

```bash
export DOCTORE_REPO_PATH="$PWD"
export DOCTORE_BET_LOG="$HOME/.local/share/doctore/bet-log.csv"
python doctore_mcp/server.py
```

## Tools

| Tool | Access | Contract |
|---|---|---|
| `doctore_parse_pinnacle_table` | read | Header-aware table parser; six selected-side canonical snapshots per game |
| `doctore_check_data_quality` | read | Stale/future timestamp and odds contradiction gate |
| `doctore_load_model_prediction` | read | Versioned rich artifact to `doctore.model-output.v1` |
| `doctore_calculate_edge_and_stake` | read | Canonical no-vig, EV, edge, Kelly and caps through decision core |
| `doctore_evaluate_bet` | read | Complete canonical decision output plus zero-safe recommended stake |
| `doctore_log_bet` | write | Recomputes the decision, verifies `decision_id`, and prevents stake increase |
| `doctore_settle_bet` | write | Exact-domain closing snapshot, CLV and result settlement |
| `doctore_portfolio_status` | read | Open exposure, P/L, result counts and CLV summaries |

All tools return structured Pydantic/dictionary outputs, not JSON-encoded
strings.

## Parser behavior

The parser:

- detects and skips copied browser/header rows;
- reports every parsed, skipped and rejected row;
- stores run-line/spread values in the canonical top-level `line` field;
- emits separate selected-side snapshots while retaining all outcomes for
  no-vig calculation;
- includes scheduled time and the Pinnacle numeric identifier in `event_id`,
  preventing same-team doubleheader collisions.

## Logging controls

`doctore_log_bet` requires:

1. the original canonical evaluation inputs;
2. the returned canonical decision output;
3. `decision == BET`;
4. a human decision of `APPROVE` or `REDUCE`;
5. an approved stake not exceeding the canonical recommendation;
6. a previously unused `decision_id`.

The tool reruns `evaluate_bet_decision()` and requires byte-equivalent structured
output. A caller cannot convert `PASS`/`BLOCKED` into a logged bet by editing the
response payload.

## Settlement and CLV

`doctore_settle_bet` requires a complete canonical closing market snapshot. It
checks event, market, sport, competition, market type, target market, period,
line, settlement rules, selection, book, selected price and event timing.

It stores:

- closing decimal odds;
- closing no-vig probability;
- price CLV: `odds_taken / closing_odds - 1`;
- probability CLV: `closing_no_vig_probability - no_vig_probability_at_bet`;
- result and realized P/L;
- a SHA-256 content hash;
- the complete snapshot in append-only JSONL.

Identical settlement retries are idempotent. Conflicting second settlements are
rejected.

## Tests

Repository tests:

```bash
python -m unittest tests/test_doctore_mcp.py
```

Real MCP Inspector CLI smoke suite for all eight tools:

```bash
python doctore_mcp/scripts/run_inspector_smoke.py --repo "$PWD"
```

The script pins `@modelcontextprotocol/inspector@0.21.2`, runs `tools/list`, and
then calls every tool over an actual stdio MCP connection using an isolated
temporary bet log.
