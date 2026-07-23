# Status semantics

| Status | Meaning | Downstream action |
|---|---|---|
| VALID | All required data and assumptions are current and coherent. | Continue to market and model validation. |
| WATCH | A resolvable condition is pending; no stake yet. | State exact trigger and recheck rule. |
| BLOCKED | Calculation would rely on missing, stale, contradictory, or mismatched data. | Stop. Do not estimate. |

`PASS` is not a data-quality status. It is an economic or risk decision made after valid calculations.
