# Templates

## BET

```text
BET — [tier]
Event: [event]
Start: [ISO-8601]
Market / selection: [market] — [selection]
Book / odds: [book] @ [decimal]
Price timestamp: [ISO-8601]
Model: [name] [version] | P [x%]
Market no-vig P: [x%] | Break-even P: [x%]
EV: [+x%] | Edge: [+x pp] | Minimum price: [x.xx]
Stake: [currency] / [units] / [bankroll %]
Risk: [Kelly fraction, binding cap, correlation group]
Validation: [critical confirmations]
Rule: [minimum price and invalidation conditions]
Reason: [one quantitative sentence]
```

## WATCH

State current price, required price or missing confirmation, and exact recheck trigger.

## PASS

State the failed threshold or risk reason. Avoid narrative filler.

## BLOCKED

State the missing, stale, contradictory, or mismatched input and the exact resolution required.

## Compact WhatsApp

```text
DOCTORE PICK
[Sport] — [event]
Bet: [selection]
Odds: [x.xx] @ [book]
Stake: [units] ([currency])
Model P: [x%] | No-vig P: [x%]
EV: [+x%] | Edge: [+x pp]
Rule: [minimum odds and confirmations]
Reason: [one sentence]
```
