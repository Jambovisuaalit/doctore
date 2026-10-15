# Doctore implementation audit — 2026-10-15

Baseline inspected: Jambovisuaalit/doctore main at
`ebe31d196a1e6f5b624628cc725b6a2bd2e9c0ba`.

## Evidence and changes

The attachment's seven-tool description is historical. Baseline code already
registered ten tools: the eight documented research/ledger tools plus context
and slate orchestration. Settlement, canonical decision authority, locking,
atomic CSV writes, model-artifact path restrictions, exact-domain checks and
hash-bound approval logging already existed. They were preserved.

Implemented in this branch:
- Independent result settlement with null CLV when closing data is unavailable;
  a nonempty missing reason is required and stored in CSV and JSONL.
- Retain original event start time in new ledger rows. Closing snapshots cannot
  rewrite it. Old CSV headers remain readable; missing original event times do
  not silently gain a caller-supplied default.
- Repeat settlement is idempotent; changed results/closing data are rejected.
- Optional explicit ATP/WTA provider adapter, pinned to reviewed sports-skills
  source version 0.37.1 at 39092bbb6f146cc9d5631dabcf53f57f601fde6c.
  Public data are not converted into model probabilities or bookmaker event
  identity. Provider request timestamps never imply event freshness.
- Source response validation and deterministic fake-provider regression tests.
- Official Python MCP stdio smoke entrypoint, sharing Inspector cases and
  rejecting MCP isError responses. All state remains isolated and synthetic.
- Declare PyYAML, required by the existing repository validator/tests.

## Scope and remaining decisions

This is a local research implementation, not a production launch. No actual
bet was placed. No Odds API credits, Telegram dispatch or polling was enabled.

The Odds Dropper source could not be accessed: GitHub connector returned 404
for GhoulHouse-Dev/the-odds-dropper. Its actual payload and deployment cannot be
verified. Therefore P3 integration is blocked; no substitute payload contract
was invented.

P2 source adapter is implemented and tested with fake provider responses. The
optional provider is not installed in the standard smoke environment and no
live ESPN query has been verified. Strict source/entity mapping is still needed
before joining tennis profiles to bookmaker events, especially doubles.

Broader brief items not completed by these patches:
- Separate approval from actual-placement confirmation and record actual odds,
  stake, bookmaker receipt, and placement time as distinct immutable events.
  Existing logging persists approved decision values.
- Recheck current wall-clock executable price and portfolio at actual placement;
  deterministic historical evaluations remain supported by the current API.
- Explicit revision/audit workflow for corrected settlements and later closing
  enrichment. Conflicting changes are currently rejected.
- Atomic multi-file transaction between CSV state and JSONL audit. Existing
  replay repair remains; a transactional database/event ledger is not added.
- User-approved bankroll, caps, close freshness/source policy and real calibrated
  model artifacts. No production values were assumed from conversation history.

## Verification commands

```
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python scripts/validate_skills.py
.venv/bin/python doctore_mcp/baseline/session_v1/materialize.py --verify-only
.venv/bin/python doctore_mcp/scripts/run_stdio_smoke.py --repo "$PWD"
.venv/bin/python doctore_mcp/scripts/run_inspector_smoke.py --repo "$PWD"
```

The runtime environment first lacked dependencies; those failed setup runs are
not product regressions. See the PR validation results for completed checks.
