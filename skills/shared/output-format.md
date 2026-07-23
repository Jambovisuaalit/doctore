# Doctore Standard Output Format

Use this format for every market scan and candidate decision. Do not omit failed gates.

## Daily scan header

```text
DOCTORE MARKET SCAN
Decision timestamp: [ISO-8601]
Sports scanned: [list]
Events scanned: [N]
Markets scanned: [N]
Valid model candidates: [N]
Bankroll: [amount]
Open exposure before decisions: [amount and percentage]
Minimum EV: [percentage]
Minimum market edge: [percentage points]
```

## Actionable bet

```text
BET #[number] — [TIER A | TIER B | TIER C]

Event: [away/player A] vs [home/player B]
Sport / competition: [sport / competition]
Start: [ISO-8601 and local time]
Market: [market, period, line]
Selection: [selection]
Book: [book]
Executable odds: [decimal]
Price snapshot: [ISO-8601]

MODEL
Model: [name and version]
Model generated: [ISO-8601]
Calibration: [status and method]
Model probability: [percentage]
Sizing probability: [percentage]

MARKET
No-vig probability: [percentage]
Break-even probability: [percentage]
Market margin: [percentage]
Edge vs no-vig market: [percentage points]
EV at current price: [percentage]
Minimum qualifying price: [decimal]

RISK
Full Kelly: [percentage of bankroll]
Kelly fraction used: [percentage of full Kelly]
Final stake: [EUR]
Units: [u]
Bankroll percentage: [percentage]
Binding cap: [none or cap]
Correlation group: [identifier]

VALIDATION
Data quality: VALID | DEGRADED
Critical confirmations: [list]
Context risks: [list]
Anti-bias flags: [none or list]

ONE-LINE CASE
[One concise sentence explaining the verified quantitative reason for the bet.]

EXECUTION RULE
Bet only at [minimum price] or better and only while [critical assumptions] remain valid.
```

## Watch candidate

```text
WATCH #[number]
Event: [event]
Market / selection: [market and selection]
Current odds: [decimal]
Model probability: [percentage]
Current EV: [percentage]
Required price: [decimal]
Blocking condition: [price, lineup, starter, data refresh, limit, or timing]
Recheck trigger: [specific measurable trigger]
```

## Pass candidate

```text
PASS — [event and market]
Current odds: [decimal]
Model probability: [percentage]
EV: [percentage]
Primary reason: [below threshold, negative Kelly, poor price, correlation cap, or risk limit]
```

## Blocked candidate

```text
BLOCKED — [event and market]
Missing or conflicting critical input: [field]
Why calculation is unsafe: [reason]
Required resolution: [specific data or confirmation]
```

## End-of-scan summary

```text
SCAN SUMMARY
Bets approved: [N]
Total stake: [amount and units]
Open exposure after decisions: [percentage]
Daily turnover after decisions: [percentage]
Passes: [N]
Watch candidates: [N]
Blocked candidates: [N]
Highest-priority refresh: [item]
```

If no bet qualifies, use exactly:

```text
No qualifying Doctore edge — pass.
```

## Compact WhatsApp format

Use only after the full audit exists.

```text
DOCTORE PICK
[Sport] — [Event]
Bet: [Selection and market]
Odds: [decimal] @ [book]
Stake: [units] ([EUR])
Model P: [percentage]
No-vig P: [percentage]
EV: [percentage]
Confidence: [1–100 derived from evidence quality, not stake]
Rule: [minimum odds and critical validity condition]
Reason: [one sentence]
```

Do not publish confidence without model version, price timestamp, and EV in the underlying record.