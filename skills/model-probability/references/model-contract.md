# Model contract

Every actionable prediction must contain:

- stable event and market identifiers;
- target market and settlement definition;
- selection;
- raw and calibrated probability when available;
- model name and immutable version;
- prediction generation time and feature cutoff;
- training cutoff and validation window;
- feature schema version;
- calibration status and method;
- validation sample size and relevant metrics.

Block the candidate when the model target differs from the executable market, including full game versus first period, listed pitcher versus action, regulation versus overtime, or different prop lines.
