# Model evidence and production admission

Current production status: BLOCKED. No real trained model or locked historical
odds/feature dataset has been recovered in this checkout. Registries remain
empty. Existing synthetic examples and tests are not validation evidence.

The old probability-pipeline `validated` label means a configured sample and
lower average Brier/log loss. It does not establish uncertainty, executable
profit, independent review, or production approval. That computational label is
preserved for compatibility, never promoted automatically.

## Evidence required before registration

1. Choose one exact sport/competition/market/period/line/settlement domain.
2. Recover immutable, licensed pre-event features, prices and final outcomes;
   retain source files, raw-byte hashes, feature availability and acquisition times.
3. Finish development, select parameters/calibration once, freeze the model and
   reserve a later untouched holdout. Both training and calibration cutoffs must
   precede development end; no fitting or rule selection on the holdout.
4. Produce one chronological binary observation per event, with genuine OOS
   probabilities and comparable same-time opposing prices. No push exclusion
   after observing results: this first gate supports only binary no-line or
   half-line domains. Integer/quarter-line settlement needs its own workflow.
5. Run the offline evidence command. Defaults are a conservative initial policy:
   500 events, 30 distinct UTC event-days, 2,000 paired day bootstrap samples,
   fixed seed 73191, positive lower 95% interval bounds for both score advantages.
   These defaults are not a universal guarantee or an established user risk policy.
6. Review data authenticity, calibration/ECE, subgroup stability, cross-day
   dependence, all tried models/rules and economic feasibility independently.
   A report passing statistics has `production_approved=false` permanently.
7. Only after explicit human review, populate the private registry with immutable
   model, prediction, report and CSV references, exact domain and review evidence.

## Input and command

CSV columns:

`event_id,event_start_at,prediction_at,training_cutoff_at,calibration_cutoff_at,odds_captured_at,probability,decimal_odds,opposing_odds,outcome`

All times require a timezone. Outcome is 0 or 1 for the selected side; probabilities
must be strictly between 0 and 1. Snapshot odds must precede prediction by at most
five minutes. Predicted event starts after prediction. For a fair baseline, choose
and document a repeatable source and quote time before running the holdout.

Metadata JSON fields:

- `model_name`, `model_version`, `model_artifact_sha256` (raw trained-model bytes)
- `dataset_sha256` (locked training dataset; independently checked by reviewer)
- `source_kind`: `observed` for genuine historical records; synthetic never passes
- `holdout_start_at`, `development_end_at`
- `domain`: `sport`, `competition`, `market_type`, `target_market`, `period`, `line`, `settlement_rules`

```
python scripts/evaluate_model_evidence.py \
  --csv /private/artifacts/oos.csv \
  --metadata /private/artifacts/evidence-metadata.json \
  --output /private/artifacts/evidence-report.json
```

Output is create-only. Exit 0 means STATISTICAL_PASS, exit 2 means BLOCKED;
malformed inputs fail with no report. Raw OOS CSV hash binds the observations.
No artificial training rows, placeholder metrics or approved registry entries
are supplied by this change.

## Enforced slate governance gate

Existing slate governance now rejects manifests without `evidence_report_path`
and `evidence_report_sha256` with `MODEL_EVIDENCE_REQUIRED`. A legacy APPROVED
artifact label cannot bypass it. When evidence is present, require:

- `evidence_csv_path`, `model_artifact_path` under the permitted artifact root;
- `model_artifact_sha256` matching actual trained-model bytes;
- prediction model name/version/hash matching the manifest;
- report raw-byte hash and deterministic recomputation from OOS CSV;
- passing statistics and exact requested market domain;
- `evidence_review`: `decision=APPROVED`, nonempty `reviewer`, exact `report_sha256`.

Paths/hashes are local evidence controls, not cryptographic reviewer identity.
The reviewer must actually verify the declared source and holdout independence.
Do not fill those fields automatically. Changing source data invalidates the report.

This enforcement applies to `validate_market_governance` used by slate execution.
Standalone deterministic evaluation and direct research ledger calls retain their
research contracts; they do not certify models or represent production admission.
An app exposing those calls must enforce the same admission boundary separately.

## What this does not prove

Score advantage is not betting ROI. This gate neither selects a bet threshold
nor estimates a production stake. A later locked economic evaluation must include
actually available odds, execution constraints, costs, turnover, drawdown,
uncertainty, all attempted strategies and subsequent prospective paper tracking.
Block bootstrap preserves pairing and within-day dependence, but not all
cross-day dependence or selection bias. Review those before any real-money use.

## Recovery inspected on 2026-10-15

- Main and local ignored data/artifact directories: no datasets or trained weights.
- Historical `research/mlb-validation-2026-09-11` schedule acquisition run
  34571391058 succeeded; artifact inventory now empty. This was source acquisition,
  not model validation.
- Research/acquisition branches exist. Their existence alone is not data or edge
  evidence. No paid historical odds API, quota, retraining or external notification
  was triggered by this work.
