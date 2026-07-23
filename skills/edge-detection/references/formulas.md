# Edge formulas

For decimal odds `d`, model probability `p`, and market no-vig probability `m`:

```text
break_even_probability = 1 / d
EV = p * d - 1
edge_vs_break_even_pp = p - 1/d
edge_vs_market_pp = p - m
break_even_odds = 1 / p
minimum_odds_at_EV_threshold = (1 + minimum_EV) / p
full_kelly = (p*d - 1) / (d - 1)
```

Do not calculate Kelly from `p - m`. Kelly depends on the actual payout and the model probability.
