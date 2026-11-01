# NHL totals cross-book scanning — fail-closed policy

Scope: NHL full-game total O/U price-vector research only. No bet placement, model probability, EV claim, or stake allocation. Existing canonical model, math, and human-review contracts remain unchanged.

## Quote input contract

\`doctore_scan_nhl_totals\` accepts \`ScanNhlTotalsInput\`:
- \`rows\`: independent sportsbook quotes with both over/under prices, each with \`book\`, \`provider_event_id\`, \`provider_quote_id\`, externally verified \`canonical_event_id = nhl:{official_event_id}\` and \`event_identity_verified = true\`;
- \`source_observed_at\`: actual source quote observation/update with timezone and clock, not sheet date or ingestion time;
- \`captured_at\`: instrumented acquisition time, separate from source observation;
- \`source_capture_method\`: \`provider_api\` or \`instrumented_manual_capture\`; name of a workbook or file mtime is not evidence;
- \`scheduled_start_at\`: official scheduled start, full offset-aware ISO-8601 timestamp;
- \`market_state = pregame\`, \`quote_status = open\`; no default if missing;
- \`sport = NHL\`, \`competition = NHL\`, \`market_type = total\`, \`period = full_game\`;
- \`line\` and \`line_role\` (\`main\` or \`alternate\`), \`over_odds\` and \`under_odds\`;
- \`settlement_scope\`: one of \`REGULATION_60\`, \`REGULATION_OT\`, \`REGULATION_OT_SO\`; the final category explicitly counts a decisive shootout goal;
- \`settlement_rule_url\` HTTPS, \`settlement_rule_verified_at\` timestamp, \`settlement_rule_verified = true\` only after verifying the **specific quoted market** against sportsbook primary-source terms;
- \`commission_fraction\`: an account- and market-specific value, explicitly 0 if genuinely free; unknown must not be silently set to 0.

As-of time is separately required and must have an offset. Both source observation and capture must precede the actual scheduled start and evaluation time, and both must be younger than the freshness threshold (default 300s). Historical or day-only copied rows fail closed. Source capture metadata is caller evidence, **not independently authenticated** by the scanner; retention of raw screenshots/API payloads and provider IDs is recommended.

## Comparison rules

A pair is comparison-eligible only if it has the same verified canonical event, event start time, total line, full-game period, settlement scope, and line role; one quote offers the over side and the other offers under, from **different** books. Exact line matching is mandatory; different lines are not arbitrage (they can be studied as middle opportunities in a separate, non-risk-free analysis). \`REGULATION_60\` vs \`REGULATION_OT_SO\` must never be compared. If same-book historical updates repeat, only the latest valid quote per bookmaker/domain is retained.

Commission-adjusted effective winner odds are conservatively approximated as \`1 + (odds-1)*(1-commission_fraction)\`. A candidate is reported only if inverse effective odds sum below 1; it is still \`SHADOW_CANDIDATE\`, because order book depth, actual betting account access, both legs' simultaneous acceptance, max stakes, restrictions and cancellation rules are unverified. Exchange commission models can differ; use stronger independent settlement simulation before claiming executable profit.

## 1 November 2026 source audit

Source: user-provided \`doctoreodds1-11\` Google Sheet, \`Taulukko6\` (NHL totals). The rows contain **date-only** \`commence\` and \`last_update\`, not actual provider timestamp, sportsbook market IDs, league event IDs or verification of the market-specific OT/SO rules.

| Rank | Event (sheet naming) | Over | Under | Same listed line? | Theoretical gross | Scanner verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Anaheim Ducks — Ottawa Senators | Unibet NL O6.5 @2.00 (row 59) | Pinnacle U6.5 @2.17 (row 62) | Yes | +4.08% | \`BLOCKED_SOURCE_EVIDENCE\` pending quote time and settlement verification |
| 2 | Edmonton Oilers — New York Rangers | 1xBet O6.5 @2.17 (row 42) | BetOnline.ag U6.5 @1.99 (row 48) | Yes **in sheet** | +3.81% | \`BLOCKED_SOURCE_EVIDENCE\`; 1xBet's primary rules default to regular 60 minutes unless explicitly marked otherwise |

Primary 1xBet rules: https://1xbet.com/en/information/rules/8 , section 8.30. Aggregated match listings can show 1xBet at **6.0**, not the sheet's 6.5: https://betwatch.io/odds/nhl/edmonton-oilers-vs-new-york-rangers-2026-11-01 . This discrepancy is an investigation flag, **not proof** of a simultaneous price or provider error.

A theoretical total margin from copied values is \`(1 / (1/O + 1/U) - 1)*100\`, before commissions. It cannot be promoted to an executable opportunity without authoritative per-quote metadata.

### Evidence acquisition order

1. Resolve the official NHL event ID, provider event IDs and target book market IDs from source payloads, then record validated mappings.
2. Capture both named books' same-markets with complete offset-aware source observed and capture timestamps, along with raw evidence hash; record actual quote status and availability.
3. Confirm exact full-game settlement inclusion: regulation, overtime, shootout-deciding goal.
4. Compare only exact line and line role; check market depth and commission where applicable.
5. Run the scanner. It cannot leave \`SHADOW\` even if all gates pass. A separate validated model and human-in-the-loop decision core is required for betting signals.

### Backward compatibility

The legacy \`doctore_parse_pinnacle_table\` accepts a **caller-supplied** \`captured_at\` covering the whole copied table, and has sport-specific default settlement rules; it is not trustworthy for cross-book hockey scans and must not be used to assert executable NHL quotes. The new read-only scanner is a separate MCP entrypoint. No migration or silent reinterpretation of old snapshots.
