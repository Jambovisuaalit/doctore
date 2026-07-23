# Personal research workspace

This branch is the private, human-in-the-loop research workspace for Doctore.

## Scope

It combines:

- Agent Skills and deterministic validators;
- the leakage-safe XGB regression-to-probability pipeline;
- the canonical model-output adapter;
- local research scripts and data adapters;
- an append-only human review log.

It does **not** place bets automatically, expose a public API, or provide multi-user functionality.

## Decision boundary

```text
local data snapshot
  -> data and model validation
  -> model probability and calibration evidence
  -> EV / edge / risk analysis
  -> review packet
  -> explicit human decision
  -> append-only review log
```

The model probability is immutable during review. A reviewer may approve, reject, wait, request refreshed data, or reduce the proposed stake. Increasing stake beyond the system proposal is blocked by the bundled review logger.

## Directory map

```text
research/
├── config/
├── notebooks/
├── scripts/
├── local_adapters/
└── human_review/
```

## Basic workflow

1. Produce or import a timestamped market snapshot.
2. Produce a versioned model output.
3. Create a review packet:

```bash
python research/scripts/create_review_packet.py \
  --market-snapshot path/to/market.json \
  --model-output path/to/model-output.json \
  --output artifacts/review-packets/example.json
```

4. Review the full analysis manually.
5. Append the decision:

```bash
python research/human_review/append_review.py \
  --review path/to/review.json \
  --log private/reviews.jsonl
```

## Data policy

Do not commit licensed odds feeds, personal bankroll history, private review logs, model artifacts, or raw datasets. Commit only schemas, adapters, synthetic examples, and reproducible code.

## Branch policy

- `main`: stable research foundation.
- `personal-research`: private exploratory workflow and human review tooling.
- No automatic merge is required for daily personal research.
- Promote changes to `main` only after deliberate review and repeatable tests.
