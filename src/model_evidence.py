"""Offline, paired OOS evidence. Statistical qualification is not production approval."""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = "doctore.model-evidence.v1"
MIN_EVENTS = 500
MIN_DAYS = 30
BOOTSTRAPS = 2000
SEED = 73191
FIELDS = {"event_id", "event_start_at", "prediction_at", "training_cutoff_at",
          "calibration_cutoff_at", "odds_captured_at", "probability", "decimal_odds",
          "opposing_odds", "outcome"}


def timestamp(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("timezone-aware timestamps required")
    from datetime import timezone
    return t.astimezone(timezone.utc)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_evidence(csv_path, metadata):
    """One exact binary, no-push market domain; no model fitting or rule tuning."""
    required = {"model_name", "model_version", "model_artifact_sha256", "dataset_sha256",
                "source_kind", "holdout_start_at", "development_end_at", "domain"}
    if not required <= metadata.keys():
        raise ValueError("missing metadata: " + ", ".join(sorted(required - metadata.keys())))
    domain_keys = {"sport", "competition", "market_type", "target_market", "period", "line", "settlement_rules"}
    if not isinstance(metadata["domain"], dict) or set(metadata["domain"]) != domain_keys:
        raise ValueError("exact domain required")
    line = metadata["domain"]["line"]
    if line is not None and (not isinstance(line, (int, float)) or not math.isfinite(line)
                             or abs(line % 1 - 0.5) > 1e-12):
        raise ValueError("initial evidence gate supports only no-line or half-line binary markets")
    if any(not metadata[key] for key in ("model_name", "model_version")):
        raise ValueError("nonempty model identity required")
    for key in ("model_artifact_sha256", "dataset_sha256"):
        value = metadata[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid " + key)
    holdout = timestamp(metadata["holdout_start_at"])
    development = timestamp(metadata["development_end_at"])
    if development >= holdout:
        raise ValueError("development must end before the holdout starts")
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not FIELDS <= set(reader.fieldnames or []):
            raise ValueError("missing OOS CSV fields")
        rows = list(reader)
    if not rows:
        raise ValueError("empty OOS dataset")
    seen, groups, probabilities, markets, outcomes = set(), [], [], [], []
    previous = None
    for row in rows:
        event = row["event_id"].strip()
        if not event or event in seen:
            raise ValueError("one observation per distinct event required")
        seen.add(event)
        start, prediction, train, calibration, odds_at = [timestamp(row[k]) for k in
            ("event_start_at", "prediction_at", "training_cutoff_at", "calibration_cutoff_at", "odds_captured_at")]
        if not (max(train, calibration) < prediction < start and odds_at <= prediction
                and prediction >= holdout and train <= development and calibration <= development):
            raise ValueError("point-in-time or frozen holdout violation: " + event)
        if previous is not None and prediction < previous:
            raise ValueError("predictions must be chronological")
        previous = prediction
        p, odds, opposite, y = [float(row[k]) for k in ("probability", "decimal_odds", "opposing_odds", "outcome")]
        if not all(math.isfinite(x) for x in (p, odds, opposite, y)) or not (0 < p < 1 and odds > 1 and opposite > 1 and y in (0, 1)):
            raise ValueError("requires finite binary no-push outcomes, interior probabilities and decimal odds")
        if (prediction - odds_at).total_seconds() > 300:
            raise ValueError("historical price older than five minutes")
        groups.append(start.date().isoformat())
        probabilities.append(p)
        markets.append((1 / odds) / (1 / odds + 1 / opposite))
        outcomes.append(y)
    p, m, y = map(np.asarray, (probabilities, markets, outcomes))
    brier_delta = (m - y) ** 2 - (p - y) ** 2
    logloss = lambda q: -(y * np.log(q) + (1 - y) * np.log1p(-q))
    log_delta = logloss(m) - logloss(p)
    days = sorted(set(groups))
    # Resample whole UTC event-days, retaining within-day dependence and pairing.
    day_sums = np.array([[sum(brier_delta[i] for i, g in enumerate(groups) if g == day),
                          sum(log_delta[i] for i, g in enumerate(groups) if g == day),
                          groups.count(day)] for day in days])
    rng = np.random.default_rng(SEED)
    draws = day_sums[rng.integers(0, len(days), size=(BOOTSTRAPS, len(days)))].sum(axis=1)
    bounds = np.quantile(draws[:, :2] / draws[:, 2, None], [0.025, 0.975], axis=0)
    reasons = []
    if metadata["source_kind"] != "observed":
        reasons.append("OBSERVED_SOURCE_REQUIRED")
    if len(rows) < MIN_EVENTS:
        reasons.append("INSUFFICIENT_EVENTS")
    if len(days) < MIN_DAYS:
        reasons.append("INSUFFICIENT_DAY_BLOCKS")
    if not bounds[0, 0] > 0:
        reasons.append("BRIER_ADVANTAGE_UNPROVEN")
    if not bounds[0, 1] > 0:
        reasons.append("LOGLOSS_ADVANTAGE_UNPROVEN")
    ece = 0.0
    for lower in np.arange(0, 1, 0.1):
        mask = (p >= lower) & (p < lower + 0.1)
        if mask.any():
            ece += float(mask.mean() * abs(p[mask].mean() - y[mask].mean()))
    return {
        "schema_version": SCHEMA,
        "status": "STATISTICAL_PASS" if not reasons else "BLOCKED",
        "reason_codes": reasons,
        "production_approved": False,
        "metadata": metadata,
        "oos_csv_sha256": digest(csv_path),
        "sample_size": len(rows), "day_blocks": len(days),
        "method": {"name": "paired_utc_event_day_bootstrap", "resamples": BOOTSTRAPS, "seed": SEED,
                   "confidence": 0.95, "minimum_events": MIN_EVENTS, "minimum_days": MIN_DAYS},
        "brier": {"model": float(np.mean((p-y)**2)), "market": float(np.mean((m-y)**2)),
                  "advantage": float(brier_delta.mean()), "advantage_ci": bounds[:, 0].tolist()},
        "log_loss": {"model": float(logloss(p).mean()), "market": float(logloss(m).mean()),
                     "advantage": float(log_delta.mean()), "advantage_ci": bounds[:, 1].tolist()},
        "ece_10_bins": ece,
        "limitations": ["Source and frozen-holdout declarations require independent review.",
                        "No execution, profitability or future performance claim.",
                        "Day bootstrap does not remove dependence between days or multiple-testing bias."]}


def verify_report(report_path, expected_hash, manifest, market):
    """Require a hash-bound, recomputable report and explicit independent review."""
    if digest(report_path) != expected_hash:
        raise ValueError("evidence report hash mismatch")
    report = json.loads(Path(report_path).read_text())
    csv_path = Path(manifest["evidence_csv_path"])
    if build_evidence(csv_path, report["metadata"]) != report:
        raise ValueError("evidence report does not reproduce from OOS rows")
    if report["status"] != "STATISTICAL_PASS":
        raise ValueError("statistical evidence has not passed")
    metadata = report["metadata"]
    for key in ("model_name", "model_version", "model_artifact_sha256"):
        if metadata[key] != manifest.get(key):
            raise ValueError("evidence model identity mismatch: " + key)
    expected_domain = {k: market.get(k) for k in metadata["domain"]}
    if metadata["domain"] != expected_domain:
        raise ValueError("evidence exact domain mismatch")
    review = manifest.get("evidence_review", {})
    if (review.get("decision") != "APPROVED" or review.get("report_sha256") != expected_hash
            or not str(review.get("reviewer", "")).strip()):
        raise ValueError("independent evidence review required")
    return report
