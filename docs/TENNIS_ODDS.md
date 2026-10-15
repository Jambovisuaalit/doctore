# Tennis odds research

`doctore_tennis_data` supports `import_odds` and `compare_odds` without a provider key or network access. These commands normalize supplied prices and compare observed quotes. They never provide a model probability, stake, or betting recommendation. Match freshness and executable prices remain unverified.

## Copy prices from a bookmaker

Pass `command: import_odds`, `tour: atp` (or `wta`) and `odds_import` containing the following synthetic example. Replace all identifiers, times and prices with the actual source values before use.

```json
{
  "source_format": "copied_table",
  "raw_table": "Player A\t1,91\nPlayer B\t2.05",
  "price_format": "decimal",
  "book": "example-book",
  "book_event_id": "actual-bookmaker-event-id",
  "source_url": "https://example.com/tennis/event",
  "captured_at": "2026-10-15T09:00:00Z",
  "event_start_at": "2026-10-15T12:00:00Z",
  "competition": "ATP example",
  "settlement_rules": "one_completed_set"
}
```

Two tab-separated rows or four separate lines (player, price, player, price) are accepted. Decimal comma is supported. American prices require `price_format: american` and explicit signs, for example `-110` and `+105`. Both sides must come from one complete market at the source time. Headers and extra rows are rejected. Quotes expire after 300 seconds; future timestamps and started matches are rejected. Use the actual public HTTPS event URL without credentials.

The output contains one snapshot for each selection, each retaining the complete price pair. `book_market_id` is optional and must only be supplied when known. Internal `research:` market IDs are not bookmaker IDs. `event_reference` may explicitly assert a shared event identity across books; without it, manual event IDs stay book-specific. This assertion never counts as verified identity.

## Import an existing Odds API export

Use `source_format: odds_api_v4`, `price_format: decimal`, and `payload` containing the original v4 `/odds` JSON array. The importer accepts future ATP/WTA two-way `h2h` markets, preserving `market.last_update` or `bookmaker.last_update`. Local import time never substitutes for a missing quote timestamp. Invalid markets are reported in `rejected`; partial imports retain that diagnostic. Duplicate event/book entries invalidate that pair.

Aggregator event IDs are not bookmaker event or market IDs. The export does not establish retirement rules. Supply `settlement_rules_by_book` only from checked book rules; otherwise rules remain `unverified` and comparison is blocked.

## Compare prices

Pass `command: compare_odds` and `comparison_snapshots` containing the same selected player from at least two books. Event identity, start time, competition, full-match market, both participant labels and settlement rules must match exactly. Do not pass both selections together. The latest complete snapshot per book is used; same-time conflicts, stale prices and source-time differences exceeding 60 seconds block comparison. A best observed price is arithmetic research, not evidence of positive expected value or executable matching terms.

## Optional single provider request

`python doctore_mcp/scripts/acquire_tennis_odds.py --sport-key tennis_atp_ACTUAL_KEY --allow-one-credit`

Requires `ODDS_API_KEY` or `THE_ODDS_API_KEY`, plus normal MCP runtime configuration. The explicit flag permits exactly one EU / h2h / decimal request, with an expected provider charge of one credit. There are no retries, polling, redirects or automatic bets. Returned provider quota headers expose actual usage. Transport errors redact the credential-bearing URL. This path was tested with mocks; no paid request or real price availability was verified during implementation.

Official API specification: https://the-odds-api.com/liveapi/guides/v4/
