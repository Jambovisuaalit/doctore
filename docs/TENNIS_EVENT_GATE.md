# Tennis event identity and freshness

The source read adapter still returns event_freshness_verified=false. No source
update timestamp is inferred from request time, a score change or successful HTTP.
This change adds a separate deterministic prematch gate to the canonical decision
core, not a live feed and not a claim of live source verification.

MCP evaluation injects the server-owned `governance/tennis-identity-registry.json`
(or DOCTORE_TENNIS_IDENTITY_REGISTRY). Caller-supplied identity registries are
ignored. Default mappings are empty, so tennis decisions fail closed.

The context's `tennis_event` needs: source, source_event_id, book_event_id, tour
(atp/wta), format (singles), tournament_id, round, event_start_at,
source_player_ids (ordered pair), book_player_ids (ordered pair), status=scheduled,
source_updated_at and received_at. A provider event-update time must be no older
than 120 seconds, not in the future, and precede receipt. Names are never used.

A reviewed mapping binds all identity fields above to `canonical_event_id`, book,
`book_market_id`, status=APPROVED, reviewer and valid_until. Book event ID and book
market ID are distinct; neither is synthesized from player names. Multiple matching
mappings, rescheduled starts, reordered IDs, withdrawals, live status, expired
mapping or changed tournament/round all block. Doubles and in-play are deliberately
unsupported by this first gate. Prematch price freshness remains a separate check.

All evidence and injected mapping are bound into the canonical context hash and
decision ID. Direct core callers must supply a trusted registry; MCP owns loading.
Supplied event-update times still require a trusted source acquisition path. This
validator does not authenticate arbitrary user-entered source claims. The existing
sports-skills/ESPN adapter has not demonstrated these required update/identity
fields, so no real mapping is pre-approved and no live readiness is claimed.
