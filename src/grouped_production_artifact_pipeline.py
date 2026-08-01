"""Immutable production runner using timestamp-grouped walk-forward evaluation."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from bet_decision_core import evaluate_bet_decision
from doctore_probability import WalkForwardConfig, write_immutable_json
from doctore_probability_grouped import fit_probability_pipeline_grouped
from model_output_adapter import to_model_output_contract
from production_artifact_pipeline import (
    ROOT,
    _ordered_live_features,
    _read_json,
    _read_training_csv,
    _selected_and_opposing_odds,
    _sha256_file,
    _validate_domain,
    _validate_point_in_time,
    _validate_schema,
    _write_sidecar,
    validate_locked_dataset,
)


def run_grouped_production_pipeline(
    *,
    csv_path: str | Path,
    dataset_manifest_path: str | Path,
    live_features_path: str | Path,
    market_snapshot_path: str | Path,
    portfolio_state_path: str | Path,
    risk_policy_path: str | Path,
    mlb_context_path: str | Path,
    output_dir: str | Path,
    model_name: str,
    model_version: str,
    prediction_generated_at: str,
    evaluated_at: str,
    config: WalkForwardConfig,
    xgb_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError(f"immutable output directory already exists: {destination}")

    manifest = _read_json(dataset_manifest_path)
    if manifest.get("sort_order") != "timestamp_nondecreasing_grouped":
        raise ValueError("grouped runner requires timestamp_nondecreasing_grouped manifest")
    live = _read_json(live_features_path)
    market = _read_json(market_snapshot_path)
    portfolio = _read_json(portfolio_state_path)
    policy = _read_json(risk_policy_path)
    context = _read_json(mlb_context_path)

    _validate_schema(market, ROOT / "contracts" / "market-snapshot.schema.json", "market")
    _validate_schema(portfolio, ROOT / "contracts" / "portfolio-state.schema.json", "portfolio")
    _validate_schema(policy, ROOT / "contracts" / "risk-policy.schema.json", "policy")
    _validate_domain(manifest, market)
    dataset_evidence = validate_locked_dataset(manifest=manifest, csv_path=csv_path)

    x, target, lines, over_odds, under_odds, timestamps, _ = _read_training_csv(
        csv_path,
        expected_columns=manifest["columns"],
        feature_columns=manifest["feature_columns"],
        target_column=manifest["target_column"],
        line_column=manifest["line_column"],
        over_odds_column=manifest["over_odds_column"],
        under_odds_column=manifest["under_odds_column"],
        timestamp_column=manifest["timestamp_column"],
    )
    feature_values = _ordered_live_features(live, manifest, market)
    selected_odds, opposing_odds = _selected_and_opposing_odds(market)

    fitted = fit_probability_pipeline_grouped(
        x,
        target,
        lines,
        over_odds,
        under_odds,
        timestamps,
        model_name=model_name,
        model_version=model_version,
        feature_schema_version=manifest["feature_schema_version"],
        config=config,
        xgb_params=xgb_params,
    )

    feature_cutoff_at = str(live.get("feature_cutoff_at"))
    _validate_point_in_time(
        training_cutoff_at=fitted.training_cutoff_at,
        feature_cutoff_at=feature_cutoff_at,
        market_captured_at=market["captured_at"],
        prediction_generated_at=prediction_generated_at,
        evaluated_at=evaluated_at,
        event_start_at=market["event_start_at"],
    )

    rich = fitted.predict_exact_line(
        feature_values,
        event_id=market["event_id"],
        sport=market["sport"],
        market_type=market["market_type"],
        period=market["period"],
        selection=market["selection"],
        market_line=float(market["line"]),
        selection_odds_decimal=selected_odds,
        opposing_odds_decimal=opposing_odds,
        market_snapshot_at=market["captured_at"],
        feature_cutoff_at=feature_cutoff_at,
        prediction_generated_at=prediction_generated_at,
        book=market["book"],
        extra_metadata={
            "dataset_id": manifest["dataset_id"],
            "dataset_version": manifest["dataset_version"],
            "dataset_sha256": dataset_evidence["dataset_sha256"],
            "target_definition": manifest["target_definition"],
            "walk_forward_grouping": "timestamp_equal_rows_atomic",
        },
    )
    canonical = to_model_output_contract(
        rich,
        market_id=market["market_id"],
        competition=market["competition"],
        target_market=market["target_market"],
        settlement_rules=market["settlement_rules"],
    )
    canonical["training_data_version"] = manifest["dataset_version"]
    _validate_schema(canonical, ROOT / "contracts" / "model-output.schema.json", "model_output")

    decision = evaluate_bet_decision(
        model_output=canonical,
        market_snapshot=market,
        portfolio_state=portfolio,
        risk_policy=policy,
        evaluated_at=evaluated_at,
        sport_context=context,
    )

    destination.mkdir(parents=True)
    model_path = destination / "xgb-model.json"
    if not hasattr(fitted.model, "save_model"):
        raise TypeError("fitted estimator does not support immutable model serialization")
    fitted.model.save_model(model_path)  # type: ignore[attr-defined]
    model_path.chmod(0o444)
    model_file_sha = _sha256_file(model_path)

    artifact_hashes = {
        "xgb-model.json": model_file_sha,
        "residual-distribution.json": write_immutable_json(
            destination / "residual-distribution.json",
            {
                "model_version": fitted.model_version,
                "residual_distribution_version": fitted.residual_distribution_version,
                "artifact_sha256": fitted.residual_artifact_sha256,
                "method": "timestamp_grouped_expanding_walk_forward_oos",
                "residuals": list(fitted.residuals),
            },
        ),
        "platt-calibrator.json": write_immutable_json(
            destination / "platt-calibrator.json", asdict(fitted.calibrator)
        ),
        "validation-report.json": write_immutable_json(
            destination / "validation-report.json",
            {
                "model_name": fitted.model_name,
                "model_version": fitted.model_version,
                "model_artifact_sha256": fitted.model_artifact_sha256,
                "feature_schema_version": fitted.feature_schema_version,
                "calibration_status": fitted.calibration_status,
                "validation_period_start": fitted.validation_period_start,
                "validation_period_end": fitted.validation_period_end,
                "metrics": asdict(fitted.validation_metrics),
                "config": asdict(fitted.config),
                "walk_forward_grouping": "timestamp_equal_rows_atomic",
                "training_dataset": dict(manifest),
            },
        ),
        "rich-prediction.json": write_immutable_json(destination / "rich-prediction.json", rich),
        "canonical-model-output.json": write_immutable_json(
            destination / "canonical-model-output.json", canonical
        ),
        "decision-output.json": write_immutable_json(destination / "decision-output.json", decision),
    }
    _write_sidecar(
        destination / "canonical-model-output.sha256",
        artifact_hashes["canonical-model-output.json"],
    )

    run_manifest = {
        "schema_version": "doctore.production-artifact-run.v1",
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["dataset_version"],
        "dataset_sha256": dataset_evidence["dataset_sha256"],
        "model_name": model_name,
        "model_version": model_version,
        "calibration_status": fitted.calibration_status,
        "event_id": market["event_id"],
        "market_id": market["market_id"],
        "line": market["line"],
        "selection": market["selection"],
        "prediction_generated_at": prediction_generated_at,
        "evaluated_at": evaluated_at,
        "decision": decision["decision"],
        "reason_codes": decision["reason_codes"],
        "artifact_sha256": artifact_hashes,
        "walk_forward_grouping": "timestamp_equal_rows_atomic",
        "write_policy": "create-only-no-overwrite",
    }
    artifact_hashes["run-manifest.json"] = write_immutable_json(
        destination / "run-manifest.json", run_manifest
    )
    return run_manifest | {"artifact_sha256": artifact_hashes}
