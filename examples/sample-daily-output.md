# Sample Doctore Daily Output

The values below are fictional and demonstrate formatting only.

```text
DOCTORE MARKET SCAN
Decision timestamp: 2026-07-23T09:15:00+03:00
Sports scanned: MLB, TENNIS
Events scanned: 14
Markets scanned: 42
Valid model candidates: 3
Bankroll: 50,000 EUR
Open exposure before decisions: 1,000 EUR / 2.0%
Minimum EV: 3.0%
Minimum market edge: 1.5 percentage points

BET #1 — TIER B

Event: Example Away vs Example Home
Sport / competition: MLB
Start: 2026-07-23T20:10:00+03:00
Market: Full-game moneyline
Selection: Example Away
Book: Pinnacle
Executable odds: 2.10
Price snapshot: 2026-07-23T09:13:40+03:00

MODEL
Model: doctore-mlb-xgb v1.8.2
Model generated: 2026-07-23T09:10:00+03:00
Calibration: validated / isotonic
Model probability: 51.0%
Sizing probability: 49.8%

MARKET
No-vig probability: 48.5%
Break-even probability: 47.6%
Market margin: 2.8%
Edge vs no-vig market: +2.5 pp
EV at current price: +7.1%
Minimum qualifying price: 2.02

RISK
Full Kelly from sizing probability: 4.1%
Kelly fraction used: 25% of full Kelly
Final stake: 500 EUR
Units: 1.0u
Bankroll percentage: 1.0%
Binding cap: unit rounding down
Correlation group: MLB-EXAMPLE-GAME-001

VALIDATION
Data quality: VALID
Critical confirmations: both starters confirmed, projected lineups compatible, weather current
Context risks: bullpen availability may change near start
Anti-bias flags: none

ONE-LINE CASE
The calibrated model prices Example Away at 51.0% versus a 48.5% no-vig market baseline, producing +7.1% EV at 2.10.

EXECUTION RULE
Bet only at 2.02 or better and only while both listed starters remain confirmed.

WATCH #1
Event: Example Player A vs Example Player B
Market / selection: Match winner — Player B
Current odds: 2.00
Model probability: 51.0%
Current EV: +2.0%
Required price: 2.02
Blocking condition: price below 3% EV threshold
Recheck trigger: executable odds reach 2.02 or better

PASS — Example Home total over 4.5
Current odds: 1.87
Model probability: 54.0%
EV: +1.0%
Primary reason: below minimum EV threshold

BLOCKED — Example NBA player points over
Missing or conflicting critical input: player minutes restriction
Why calculation is unsafe: the prop model assumed 34 minutes but current status is unresolved
Required resolution: updated active status and minutes projection

SCAN SUMMARY
Bets approved: 1
Total stake: 500 EUR / 1.0u
Open exposure after decisions: 3.0%
Daily turnover after decisions: 4.0%
Passes: 1
Watch candidates: 1
Blocked candidates: 1
Highest-priority refresh: MLB bullpen and confirmed lineups within 90 minutes of first pitch
```

## Compact WhatsApp version

```text
DOCTORE PICK
MLB — Example Away vs Example Home
Bet: Example Away ML
Odds: 2.10 @ Pinnacle
Stake: 1.0u (500 EUR)
Model P: 51.0%
No-vig P: 48.5%
EV: +7.1%
Confidence: 78/100
Rule: 2.02+ and both listed starters confirmed
Reason: Calibrated model edge is +2.5 pp versus the no-vig market with +7.1% EV at the current price.
```