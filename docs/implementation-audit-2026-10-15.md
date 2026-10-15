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

P2 source adapter is implemented, fixture-tested and live-tested as described
below. Network is disabled explicitly during standard smoke tests.
Strict source/entity mapping is still needed
before joining tennis profiles to bookmaker events, especially doubles.

Broader brief items not completed by these patches:
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

## Completed follow-up: approval and actual placement

`doctore_log_bet` now records APPROVED, awaiting actual placement; the slate
orchestrator reports APPROVED_AWAITING_PLACEMENT. The separate
`doctore_confirm_placement` tool requires explicit confirmation, actual stake,
actual odds, a timezone-aware placement time and bookmaker reference. It never
contacts a bookmaker. Original approved stake/odds remain in the state.

Only confirmed bets contribute to actual exposure and can be settled. Pending
approvals have separate count/amount metrics. Historical open rows are marked
LEGACY_UNCONFIRMED and retain conservative exposure, without inventing proof of
placement. Actual excess stake or worse odds are recorded with warnings, rather
than hiding already-incurred liability. P/L and CLV use actual execution values.

The placement JSONL is written and fsynced before atomic CSV replacement, under
the shared lock. Same-fact replay repairs an interrupted state write; conflicting
facts or duplicate bookmaker references are rejected. This does not replace the
remaining settlement revision and cross-file transaction work.

## Completed follow-up: explicit live source checks

Pinned sports-skills source was installed in the test environment. Live HTTP
reads on 2026-10-15 returned these successful source results:

| UTC request time | Operation | Tour | Observed result |
|---|---|---|---|
| 00:38:34 | get_scoreboard | ATP | 1 tournament |
| 00:37:27 | get_scoreboard | WTA | 4 tournaments |
| 00:38:36 | get_rankings | ATP | 3 entries, names and IDs present |
| 00:38:37 | get_rankings | WTA | 3 entries, names and IDs present |
| 00:37:06 | get_calendar | ATP | 60 tournaments |
| 00:37:07 | get_player_info | ATP scope | ESPN id 3623 returned a named player profile |

The profile endpoint has no tour filter, so ATP scope is not proof of tour
membership. Neither transport success nor counts prove current match freshness
or complete historical data. `source_updated_at=null` and
`event_freshness_verified=false` remain explicit. WTA calendar/profile calls were
not separately verified.

Earlier attempts encountered timeouts and an ATP scoreboard HTTP 502. The
adapter now upgrades provider-published HTTP athlete references to the same
HTTPS resources in a disposable process, caps each request at ten seconds with
no retry, and enforces a 45-second total deadline. A source failure returns
BLOCKED and no substitute event/model data. Ranking entries missing names/IDs
also fail closed. `verify_tennis_live.py` reproduces explicit source checks;
live calls are not part of CI or the deterministic smoke suite.

The Inspector runner now checks protocol errors and actual logged=true, rather
than equating a successful tools/call transport with persisted approval.
Its locally computed fixture hashes use the same integral numeric representation
as the JavaScript CLI transport. Use --inspector-offline when the pinned npm
package is cached; a registry 403 is an environment failure, not MCP evidence.
