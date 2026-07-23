# Blocking rules

Return `BLOCKED` when any critical condition applies:

- Event is started, finished, postponed, or ambiguously identified for a pregame request.
- Price has no timestamp or exceeds the configured age limit.
- Outcome set is incomplete or combines different books, lines, periods, or settlement rules.
- Odds are invalid or selection identity is ambiguous.
- Model probability, model version, target market, or prediction timestamp is missing.
- Model target does not match the executable market.
- A critical sport assumption changed after prediction and no refreshed model exists.
- Portfolio exposure is unavailable or stale when a stake is requested.

Return `WATCH` only when the candidate is currently non-executable but a precise refresh condition exists, such as a confirmed lineup, starter, roof status, or minimum price.
