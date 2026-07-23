# Doctore Anti-Bias Checklist

Run this checklist after the quantitative edge calculation and before final execution. Bias review may reject or reduce a candidate. It may not create edge.

## 1. Forced-action check

- Am I trying to produce a bet because the user asked for one?
- Would the answer still be `BET` if today's slate were smaller or yesterday had been profitable?
- Does the candidate clear the configured thresholds without rounding or exceptions?

Failure action: `PASS`.

## 2. Recency check

- Is recent performance already represented in the model?
- Am I overweighting the last game, series, start, set, or headline?
- Is the sample large enough to distinguish form from noise?

Failure action: retain model probability; remove unsupported narrative or return `WATCH` if model inputs may be stale.

## 3. Result-chasing check

- Is stake size influenced by recent wins or losses?
- Is the user attempting to recover a drawdown faster?
- Has unit size changed outside the approved bankroll policy?

Failure action: set stake according to the configured risk model or `BLOCKED` for unauthorized escalation.

## 4. Favorite and star bias

- Am I treating a famous team or player as safer regardless of price?
- Am I confusing high win probability with positive EV?
- Is the market already charging a premium for popularity?

Failure action: use the exact price and EV only.

## 5. Underdog-value fallacy

- Am I assuming a high price automatically means value?
- Does the model probability actually clear the break-even requirement?
- Is the model calibrated in this low-probability range?

Failure action: `PASS` or stricter uncalibrated sizing.

## 6. Market-authority bias

- Am I copying the no-vig market probability and calling it Doctore's prediction?
- Am I assuming Pinnacle or market consensus cannot be wrong?
- Is the model meaningfully independent from the evaluated price?

Failure action: separate market baseline from model output and disclose market-feature dependence.

## 7. Contrarian trap

- Am I fading the public merely because a side is popular?
- Is public-money data reliable, timestamped, and relevant?
- Does the model support the contrarian position independently?

Failure action: ignore public splits unless they affect a documented model or execution rule.

## 8. Line-movement storytelling

- Am I assigning a cause to movement without evidence?
- Could movement reflect limits, news, liquidity, or ordinary repricing?
- Is the current price still +EV after the movement?

Failure action: report movement as observation, not causal proof.

## 9. Confirmation bias

- Were sources searched only for evidence supporting the candidate?
- Were both participants' injury, lineup, and context checked?
- Were contradictory sources retained and resolved?

Failure action: expand verification or return `BLOCKED`.

## 10. Precision illusion

- Does the reported probability imply more certainty than the validation supports?
- Is the model new, out of domain, or poorly calibrated?
- Are EV and Kelly rounded in a way that exaggerates the edge?

Failure action: show uncertainty, shrink sizing probability, and reduce risk tier.

## 11. Correlation blindness

- Are multiple bets driven by the same event, team, player, starter, weather, or injury assumption?
- Is the combined downside larger than the per-bet view suggests?
- Has the correlation group been capped?

Failure action: aggregate positions and reduce or block sizing.

## 12. Data freshness anchoring

- Am I anchored to an earlier better price?
- Is the displayed price still executable?
- Has model-relevant information changed since prediction generation?

Failure action: refresh and recalculate. Never recommend a stale number.

## Required output

```text
ANTI-BIAS AUDIT
Forced action: PASS | FLAG
Recency: PASS | FLAG
Result chasing: PASS | FLAG
Favorite/star bias: PASS | FLAG
Underdog-value fallacy: PASS | FLAG
Market-authority bias: PASS | FLAG
Contrarian trap: PASS | FLAG
Line-movement storytelling: PASS | FLAG
Confirmation bias: PASS | FLAG
Precision illusion: PASS | FLAG
Correlation blindness: PASS | FLAG
Freshness anchoring: PASS | FLAG
Flags affecting decision: [list]
Action: CONTINUE | REDUCE | WATCH | PASS | BLOCKED
```