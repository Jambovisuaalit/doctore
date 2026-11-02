# Explicit market quantities and independent S05 adjudication

A clean-context terminology adjudicator, who did not inspect implementation or
execution outputs, found primary-source support for both conventions. Betfair's
own [education article](https://www.betfair.com.au/hub/education/overrounds/) uses
the full market percentage; the original Betwise [mathematical guide, p.25](https://www.betwise.co.uk/publications/betfaiR.pdf)
uses the excess above one. Pinnacle [distinguishes 102% from its 2% margin](https://support.pinnacle.com/hc/en-us/articles/44854177573009-What-is-a-betting-margin).
Neither convention alone proves the other calculation wrong.

## API units

Let q_i=1/decimal_odds_i and B=sum(q_i) for a complete mutually exclusive market.
The edge-and-stake tool now exposes:

| Field | Quantity | Units |
|---|---|---|
| implied_probability_sum | B | fraction, e.g. 1.02381 = 102.381% |
| overround_excess | B-1 | fraction, e.g. .02381 = 2.381 percentage points above 100% |
| overround | legacy alias of B-1 | unchanged fraction; ambiguous name deprecated for new clients |

Canonical decision.market.overround retains the same legacy B-1 meaning.
No existing field changes magnitude or type. No-vig remains proportional q_i/B;
EV remains p_model*selected_odds-1. No model probability, Kelly rule, risk limit or
decision gate changes. Theoretical balanced hold 1-1/B is a different quantity
and none of these values promises realized profit.

Independent worked quantities:
- Odds 1.50/2.80: B=43/42; excess=1/42; proportional probabilities 28/43 and 15/43.
- Odds 2/2: B=1; excess=0; probabilities .5/.5.
- Odds 2.50/1.50: B=16/15; excess=1/15; probabilities 3/8 and 5/8.

## Immutable historical assessment

The original sealed S05 explicitly expects the full sum. Its literal FAIL on
91008b045f973e62ffb7b0a6ef7fee498d0a3a77 remains historical. Do not edit the task
file, rubric, old score or raw trace to create a PASS. The separate
[s05-adjudication-binding.json](s05-adjudication-binding.json) binds that exact
original numerical quantity to the new explicit field, preserving the original
no-vig, EV and tolerance checks. It is an adjudication, not execution evidence.

Original task seal: 495e2c1ae6ba3ad601d155e68d9fbec0d0bf00a4fc6d0b7b2a1218474bc61e94.
Independent determination seal: ec761fc82b1f94366f696f325594d27f8d23035a2a7ed2552b4fe63a506cceed.
New blind scenarios must be independently authored and sealed against the
explicit public contract before outputs are observed. This is not production GO.
