# Tennis source acquisition, identity and freshness

## Corrected trust boundary

MCP no longer accepts caller-supplied `tennis_event` timestamps, identities or
registries as source verification. It loads the reviewed server registry and
locally acquired provider bytes, rechecks their hash and normalizes them again at
evaluation time. Evaluation itself performs no network calls or quota spending.
The original sports-skills/ESPN read adapter remains exploratory and keeps
`event_freshness_verified=false`.

## Source semantics

Two different times must not be conflated:

- Event last-change time: when the provider changed match information. An unchanged
  scheduled match may legitimately have an old last-change time.
- Provider snapshot `generated_at`: the source's timestamp for its published summary.
  This can establish freshness of the supplied source snapshot; it is not a claim
  that the event changed at that instant or that the provider is infallible.

The Sportradar adapter uses its documented event-summary response and preserves
`source_updated_at=null`. It records `freshness_basis=provider_generated_at`,
`provider_generated_at`, actual receipt time and the source payload SHA-256.
No HTTP receipt time, Date header or logo modification time substitutes for the
provider-generated field. Snapshot age must be at most 120 seconds and
`generated_at <= received_at <= evaluated_at`. Price freshness is checked separately.

Primary references inspected on 2026-10-15:

- https://developer.sportradar.com/tennis/reference/sport-event-summary
- https://developer.sportradar.com/tennis/docs/tennis-ig-live-match-retrieval
- https://developer.sportradar.com/tennis/docs/tennis-ig-api-basics
- https://developer.sportradar.com/tennis/reference/sport-events-updated

The last endpoint's `updated_at` is an event change timestamp and is not called
by this adapter. It must not be invented from summary `generated_at`.

## Identity mapping

`governance/tennis-identity-registry.json`, or
`DOCTORE_TENNIS_IDENTITY_REGISTRY`, contains operator-reviewed mappings.
Every entry needs:

- `source=sportradar`, `source_event_id=sr:sport_event:<numeric ID>`
- `book`, `book_event_id`, `book_market_id`, `canonical_event_id`
- `tour=atp|wta`, `format=singles`, `tournament_id` (provider competition ID), `round`
- timezone-aware `event_start_at`, `valid_until`
- `source_player_ids`: provider IDs in home/away qualifier order
- `book_player_ids`: corresponding bookmaker IDs in exactly that order
- `status=APPROVED`, nonempty `reviewer`

Book event and market IDs are distinct. No names are matched; no actual mapping
is pre-approved or synthesized. A competition's type/category and round must
match the source summary. Confirmed start is required. Estimated starts,
postponements/replacements, resumed matches, virtual competitors, doubles and
non-prematch statuses fail closed. Start/round/player/mapping changes invalidate
previous observations.

## Explicit acquisition

Configure secrets privately; never commit or paste the API key into a registry:

- `SPORTRADAR_API_KEY`: existing Tennis API credential
- `SPORTRADAR_ACCESS_LEVEL`: `trial` or `production`, matching its entitlement
- `DOCTORE_REPO_PATH`, `DOCTORE_BET_LOG`: existing MCP runtime settings
- optional `DOCTORE_TENNIS_EVIDENCE_DB`: private SQLite path; defaults beside bet log

After a genuine bookmaker/provider mapping is reviewed, explicitly request one
source read:

```
python doctore_mcp/scripts/acquire_tennis_event.py \
  --book Pinnacle --book-market-id <actual-market-id> --allow-live-fetch
```

The command requires explicit opt-in and credentials before any network access.
It makes one fixed-host HTTPS request with header authentication, ten-second
network timeout, two-megabyte response bound, no redirects and no retries. It
never logs credential-bearing URLs or provider error bodies. It never registers
a model, calculates a probability, approves a bet, creates an account or purchases
a subscription. It can consume the configured provider's quota when explicitly run.

Explicit acquisitions are serialized using a separate POSIX filesystem lock;
platforms without that lock fail closed. Evaluation does not acquire this lock.
Append-only SQLite observations bind the raw source response to the reviewed
mapping hash. A new acquisition first persists a blocking in-progress observation.
Transport failure, malformed response, changed match status, interruption or failed
post-fetch persistence cannot silently restore an older cached success. Successful
normalized responses remain usable only within their source freshness window.
Current mapping expiry and exact canonical identity are rechecked during decision.
Back up this private SQLite file with the other runtime data.

## Acceptance and remaining external prerequisites

Fixture tests cover acquisition, source-time semantics, identity/status changes,
cache expiry, payload tampering, mapping changes, error redaction, missing opt-in
and missing credentials. Fixtures are not real provider or bookmaker verification.

On this environment the real setup check returned
`TENNIS_PROVIDER_CREDENTIALS_REQUIRED` before network access. No existing
SPORTRADAR_API_KEY, access-level configuration or real reviewed bookmaker mapping
was found. No subscription, key or entitlement is fabricated. To verify a real
match end-to-end, those external inputs must exist. Until then tennis decisions
remain BLOCKED. In-play betting remains unsupported even after source acquisition.

Direct calls to the pure core remain a research contract whose caller owns trusted
input acquisition. The MCP decision path owns loading and rejects arbitrary caller
evidence. Local filesystem permissions are the trust boundary; the hash is not a
defense against an administrator rewriting both provider bytes and their digest.
