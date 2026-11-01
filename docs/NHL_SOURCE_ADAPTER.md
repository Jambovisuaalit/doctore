# NHL source adapter — raw evidence, official event mapping and SHADOW-only scanning

## Scope and architecture

- Quote source: [The Odds API v4 NHL featured totals](https://the-odds-api.com/liveapi/guides/v4/) via pinned HTTPS host `api.the-odds-api.com`. Requires `DOCTORE_ODDS_API_KEY`; no key = zero HTTP calls, `BLOCKED_NO_ODDS_API_KEY`.
- Official event ID: [NHL public schedule](https://api-web.nhle.com/v1/schedule/now) via pinned HTTPS host `api-web.nhle.com`. Odds API home+away must match NHL's home+away **exactly after only Unicode/spacing normalization** and start time within 30 minutes, with exactly one match. No fuzzy matching or invented event IDs.
- Quotes: requires `markets=totals&oddsFormat=decimal&dateFormat=iso`. Uses **market-level** `last_update` as `source_observed_at`; this is the last time The Odds API saw a market's odds, **not** the bookmaker's own timestamp or a guarantee of execution. `captured_at` is local receipt time. These are never substituted for each other.
- Settlement: **unknown until independently reviewed**. A local operator-maintained registry records each bookmaker key's *exact NHL full-game totals* treatment of regulation, overtime, shootout deciding goal, plus fees. The adapter never guesses the scope. Missing/unreviewed entries are excluded.
- Scanner: passes normalized rows to the existing `scan_nhl_totals` fail-closed tool. Only exact official game, total, period, line, line role and settlement scope can compare. All output is `SHADOW`, stake 0. No bet placement and no model probability changes.

This is a source-acquisition integration, **not live-bookmaker price verification**. The Odds API may not cover a target book/region. It does not provide bookmaker-native quote IDs, complete order-book depth, or the bookmaker's exact market-specific OT/SO rules. A `local:sha256:` quote identifier is explicitly marked locally derived; it must never be presented as an exchange market identifier or a receipt.

## Install/configure

The adapter adds no new Python dependencies beyond the existing MCP Pydantic dependency. In the Doctore server environment:

```bash
export DOCTORE_ODDS_API_KEY='your-secret-provider-key'
export DOCTORE_ODDS_EVIDENCE_ROOT="$PWD/artifacts/nhl-raw-evidence"
# Optional after independently reviewing exact bookmaker/market settlement rules:
export DOCTORE_NHL_SETTLEMENT_RULES='/secure/path/nhl-rule-registry.json'
```

Protect the API key in secrets management; do **not** commit it or pass it in MCP tool arguments. The odds provider authenticates using `apiKey` as a query parameter; code pins the HTTPS host, blocks redirects, limits response sizes to 3 MB, and never writes the query string into manifests. Avoid exporting credentials to shared shell histories or CI logs.

A reviewed settlement registry has this structure (illustrative only; **do not set `reviewed: true` without evidence from the actual quoted market**):

```json
{
  "schema_version": "doctore.nhl-book-rules.v1",
  "books": {
    "bookmaker_provider_key": {
      "reviewed": false,
      "market_key": "totals",
      "period": "full_game",
      "scope": "REGULATION_OT_SO",
      "source_url": "https://example.org/replace-with-primary-market-rules",
      "verified_at": "2026-11-01T16:00:00+00:00",
      "commission_fraction": 0.0
    }
  }
}
```

Here `scope`, `source_url` and commission are placeholders, not assertions of the example bookmaker's true rules. A valid `reviewed: true` is manual attestation, not machine authentication. Account-specific restrictions still require separate verification.

## One-shot acquisition

Via MCP tool `doctore_collect_nhl_totals`:

```json
{
  "regions": "eu,us",
  "target_event_pairs": [
    "Anaheim Ducks|Ottawa Senators",
    "Edmonton Oilers|New York Rangers"
  ],
  "max_age_seconds": 300
}
```

The target pair is unordered **only for discovery**. Canonical event resolution requires exact official home/away ordering. The API may not list already-completed or missing games. For missing key the response is a structured blocker with no HTTP; if key is present but rules are unreviewed, fetched raw evidence is retained and candidate_count remains zero.

## Evidence records and verification

1. Each successful upstream JSON download is stored **byte-for-byte before parsing** as `$DOCTORE_ODDS_EVIDENCE_ROOT/sha256/<SHA256>.json`. Existing identical blobs are reused, not rewritten; writes are exclusive and fsynced.
2. Every download appends an entry to `manifest.jsonl` with source name, public endpoint URL **without credentials**, local receipt time, SHA-256 and relative blob path. The directory is gitignored under `artifacts/`, and files are created with restrictive permissions.
3. If JSON parsing, official ID match, or settlement check fails, raw downloaded sources are still retained and the reason code is returned. The result also preserves the SHA of the odds payload for each normalized row. Manifests are not a tamper-proof external audit log; for stronger assurance, replicate to restricted immutable object storage.
4. Re-check saved bytes with `sha256sum`. No model output, bet log or portfolio entry is modified.

## Risk and acceptance gates

- Unknown/missing `market.last_update` or only a date: `SOURCE_TIME_MISSING_OR_DATE_ONLY`, no manufactured timestamp.
- Official schedule missing, ambiguous or mismatching: `OFFICIAL_EVENT_ID_UNRESOLVED`/`OFFICIAL_EVENT_ID_AMBIGUOUS`.
- Missing reviewed 60-minute / OT / SO rules: `BOOK_MARKET_RULE_UNVERIFIED`.
- Different 6.0 and 6.5 totals, main vs alternate, or unequal period/scope: no arbitrage candidate.
- Quote past start, stale beyond policy, no verified fees, or in-play: scanner rejects.
- Even if all validation gates pass: `SHADOW_CANDIDATE`, `execution_verified=false`, `recommended_stake_eur=0`; no booking or automated execution.

## First two research targets

The original day-only Google Sheet cannot meet the time or settlement gates. The adapter's default scope is Anaheim Ducks–Ottawa Senators and Edmonton Oilers–New York Rangers (the order does not assert home advantage). The upstream providers may have no quotes when run or may not cover Unibet NL/1xBet/BetOnline/Pinnacle in requested regions. Do not classify missing provider coverage as no odds edge; record absence separately.

Testing: `python -m unittest tests.test_nhl_source_adapter -v` (or repository's `unittest discover`). The tests use synthetic data only; they do not prove actual 2026-11-01/02 market availability.
