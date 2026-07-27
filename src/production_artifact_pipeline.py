"""Fail-closed training-to-decision pipeline for Doctore model artifacts."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker

from bet_decision_core import evaluate_bet_decision
from doctore_probability import WalkForwardConfig, fit_probability_pipeline, write_immutable_json
from model_output_adapter import to_model_output_contract

ROOT = Path(__file__).resolve().parents[1]


class PipelineInputError(ValueError):
    """Raised when provenance, domain or point-in-time inputs are invalid."""


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineInputError(f"{path} must contain a JSON object")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise PipelineInputError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PipelineInputError(f"{name} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PipelineInputError(f"{name} must include a timezone")
    return parsed


def _schema_validator(path: str | Path) -> Draft202012Validator:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(payload: Mapping[str, Any], schema_path: str | Path, name: str) -> None:
    errors = sorted(
        _schema_validator(schema_path).iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        messages = [
            f"{name}.{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
            for error in errors
        ]
        raise PipelineInputError("; ".join(messages))


def _read_training_csv(
    path: str | Path,
    *,
    expected_columns: Sequence[str],
    feature_columns: Sequence[str],
    target_column: str,
    line_column: str,
    over_odds_column: str,
    under_odds_column: str,
    timestamp_column: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], int]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        if columns != list(expected_columns):
            raise PipelineInputError(
                "training CSV columns differ from locked manifest: "
                f"expected={list(expected_columns)!r}, actual={columns!r}"
            )
        rows = list(reader)
    if not rows:
        raise PipelineInputError("training CSV contains no data rows")

    required = set(feature_columns) | {
        target_column,
        line_column,
        over_odds_column,
        under_odds_column,
        timestamp_column,
    }
    missing = required - set(columns)
    if missing:
        raise PipelineInputError(f"training CSV is missing required columns: {sorted(missing)}")

    try:
        x = np.asarray(
            [[float(row[column]) for column in feature_columns] for row in rows],
            dtype=float,
        )
        target = np.asarray([float(row[target_column]) for row in rows], dtype=float)
        lines = np.asarray([float(row[line_column]) for row in rows], dtype=float)
        over_odds = np.asarray([float(row[over_odds_column]) for row in rows], dtype=float)
        under_odds = np.asarray([float(row[under_odds_column]) for row in rows], dtype=float)
    except (TypeError, ValueError, KeyError) as exc:
        raise PipelineInputError("training CSV contains non-numeric or missing model values") from exc
    timestamps = [row[timestamp_column] for row in rows]
    return x, target, lines, over_odds, under_odds, timestamps, len(rows)


def validate_locked_dataset(
    *, manifest: Mapping[str, Any], csv_path: str | Path
) -> dict[str, Any]:
    """Validate schema, content hash, row count and exact header order."""
    _validate_schema(
        manifest,
        ROOT / "contracts" / "training-dataset-manifest.schema.json",
        "training_manifest",
    )
    actual_hash = _sha256_file(csv_path)
    if actual_hash.lower() != str(manifest["dataset_sha256"]).lower():
        raise PipelineInputError(
            "training dataset SHA-256 mismatch: "
            f"manifest={manifest['dataset_sha256']}, actual={actual_hash}"
        )

    _, _, _, _, _, _, row_count = _read_training_csv(
        csv_path,
        expected_columns=manifest["columns"],
        feature_columns=manifest["feature_columns"],
        target_column=manifest["target_column"],
        line_column=manifest["line_column"],
        over_odds_column=manifest["over_odds_column"],
        under_odds_column=manifest["under_odds_column"],
        timestamp_column=manifest["timestamp_column"],
    )
    if row_count != manifest["row_count"]:
        raise PipelineInputError(
            f"training row count mismatch: manifest={manifest['row_count']}, actual={row_count}"
        )
    return {"dataset_sha256": actual_hash, "row_count": row_count}


def _validate_domain(manifest: Mapping[str, Any], market: Mapping[str, Any]) -> None:
    for key in (
        "sport",
        "competition",
        "market_type",
        "target_market",
        "period",
        "settlement_rules",
    ):
        if manifest.get(key) != market.get(key):
            raise PipelineInputError(
                f"training/market domain mismatch for {key}: "
                f"training={manifest.get(key)!r}, market={market.get(key)!r}"
            )
    if market.get("sport") != "MLB":
        raise PipelineInputError("this production runner is currently restricted to MLB")
    if market.get("market_type") != "total":
        raise PipelineInputError("this production runner currently supports full-game totals only")
    if not isinstance(market.get("line"), (int, float)) or isinstance(market.get("line"), bool):
        raise PipelineInputError("market line must be numeric")
    if market.get("selection") not in {"over", "under"}:
        raise PipelineInputError("market selection must be normalized to lowercase over or under")


def _selected_and_opposing_odds(market: Mapping[str, Any]) -> tuple[float, float]:
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        raise PipelineInputError("MLB total market must contain exactly two outcomes")
    selection = market["selection"]
    selected = [item for item in outcomes if isinstance(item, dict) and item.get("selection") == selection]
    opposing = [item for item in outcomes if isinstance(item, dict) and item.get("selection") != selection]
    if len(selected) != 1 or len(opposing) != 1:
        raise PipelineInputError("market outcomes do not identify one selected and one opposing side")
    selected_odds = float(selected[0]["decimal_odds"])
    opposing_odds = float(opposing[0]["decimal_odds"])
    if selected_odds != float(market["decimal_odds"]):
        raise PipelineInputError("selected outcome odds differ from market decimal_odds")
    return selected_odds, opposing_odds


def _ordered_live_features(
    live: Mapping[str, Any], manifest: Mapping[str, Any], market: Mapping[str, Any]
) -> list[float]:
    if live.get("schema_version") != "doctore.live-features.v1":
        raise PipelineInputError("live feature payload schema_version must be doctore.live-features.v1")
    if live.get("event_id") != market.get("event_id"):
        raise PipelineInputError("live feature event_id does not match market event_id")
    if live.get("feature_schema_version") != manifest.get("feature_schema_version"):
        raise PipelineInputError("live feature schema version does not match training manifest")
    features = live.get("features")
    if not isinstance(features, dict):
        raise PipelineInputError("live features must be an object")
    expected = list(manifest["feature_columns"])
    if set(features) != set(expected):
        raise PipelineInputError(
            "live feature keys differ from locked feature schema: "
            f"missing={sorted(set(expected) - set(features))}, "
            f"extra={sorted(set(features) - set(expected))}"
        )
    try:
        values = [float(features[column]) for column in expected]
    except (TypeError, ValueError) as exc:
        raise PipelineInputError("live feature values must be numeric") from exc
    if not np.all(np.isfinite(values)):
        raise PipelineInputError("live feature values must be finite")
    return values


def _validate_point_in_time(
    *,
    training_cutoff_at: str,
    feature_cutoff_at: str,
    market_captured_at: str,
    prediction_generated_at: str,
    evaluated_at: str,
    event_start_at: str,
) -> None:
    training = _timestamp(training_cutoff_at, "training_cutoff_at")
    feature = _timestamp(feature_cutoff_at, "feature_cutoff_at")
    captured = _timestamp(market_captured_at, "market.captured_at")
    generated = _timestamp(prediction_generated_at, "prediction_generated_at")
    evaluated = _timestamp(evaluated_at, "evaluated_at")
    start = _timestamp(event_start_at, "market.event_start_at")
    if not training < feature:
        raise PipelineInputError("training_cutoff_at must be earlier than feature_cutoff_at")
    if feature > captured:
        raise PipelineInputError("feature_cutoff_at cannot be later than market captured_at")
    if captured > generated:
        raise PipelineInputError("market captured_at cannot be later than prediction_generated_at")
    if generated > evaluated:
        raise PipelineInputError("prediction_generated_at cannot be later than evaluated_at")
    if evaluated >= start:
        raise PipelineInputError("decision must be evaluated before event start")


def _write_sidecar(path: Path, digest: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(digest + "\n")
    path.chmod(0o444)


def run_production_pipeline(
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
    """Run dataset lock validation through canonical decision output."""
    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError(f"immutable output directory already exists: {destination}")

    manifest = _read_json(dataset_manifest_path)
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

    fitted = fit_probability_pipeline(
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
    _validate_schema(
        canonical,
        ROOT / "contracts" / "model-output.schema.json",
        "model_output",
    )

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
                "method": "expanding_walk_forward_oos",
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
                "training_dataset": dict(manifest),
            },
        ),
        "rich-prediction.json": write_immutable_json(
            destination / "rich-prediction.json", rich
        ),
        "canonical-model-output.json": write_immutable_json(
            destination / "canonical-model-output.json", canonical
        ),
        "decision-output.json": write_immutable_json(
            destination / "decision-output.json", decision
        ),
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
        "write_policy": "create-only-no-overwrite",
    }
    artifact_hashes["run-manifest.json"] = write_immutable_json(
        destination / "run-manifest.json", run_manifest
    )
    return run_manifest | {"artifact_sha256": artifact_hashes}
