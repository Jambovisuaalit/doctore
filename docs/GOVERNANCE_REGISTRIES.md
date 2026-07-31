# Doctore governance registries

This layer adds governance only. It does not change model probabilities, no-vig, EV, Kelly, staking or canonical decision logic.

## Files

- `governance/artifact-registry.json`
- `governance/model-manifest-registry.json`
- `governance/allowed-domain-matrix.json`
- runtime append-only decision bundle log from `DOCTORE_DECISION_BUNDLE_LOG`

## Artifact registry entry

```json
{
  "artifact_id": "mlb-catboost-v5-final",
  "path": "/absolute/allowed/artifact/path/prediction.json",
  "artifact_sha256": "<sha256>",
  "manifest_id": "mlb-catboost-v5-manifest",
  "status": "APPROVED"
}
```

## Model manifest registry entry

```json
{
  "manifest_id": "mlb-catboost-v5-manifest",
  "model_name": "mlb_catboost_v5",
  "model_version": "5.0.0",
  "schema_hash": "<training-feature-schema-hash>",
  "calibration_version": "residual-cdf-v1",
  "allowed_domains": [
    {
      "sport": "mlb",
      "competition": "MLB",
      "target_market": "moneyline"
    }
  ]
}
```

## Allowed domain matrix entry

```json
{
  "sport": "mlb",
  "competition": "MLB",
  "target_market": "moneyline",
  "market_type": "moneyline",
  "period": "full_game",
  "settlement_rules": "standard",
  "enabled": true
}
```

Empty registries are fail-closed. Every slate market is rejected until its artifact, manifest and exact domain are explicitly registered and approved.

## Runtime provenance

Each slate result records Python version, platform, executable path, repository path, Git commit, branch and dirty-worktree state.

## Immutable decision bundle

Every canonical decision creates a content-addressed `doctore.immutable-decision-bundle.v1` object containing:

- run ID
- exact canonical decision input
- exact canonical decision output
- registry and provenance evidence
- human approval, when present
- logging result, when present
- SHA-256 content hash

Bundles are appended to JSONL and never rewritten by the orchestrator.

## Environment overrides

- `DOCTORE_ARTIFACT_REGISTRY`
- `DOCTORE_MODEL_MANIFEST_REGISTRY`
- `DOCTORE_ALLOWED_DOMAIN_MATRIX`
- `DOCTORE_DECISION_BUNDLE_LOG`
