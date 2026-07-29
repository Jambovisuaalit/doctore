"""Deterministic governance registries and provenance checks for Doctore."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
import platform
import subprocess
import sys

from .runtime import REPO, content_sha256, resolve_artifact_path

ARTIFACT_REGISTRY_PATH = Path(
    os.environ.get("DOCTORE_ARTIFACT_REGISTRY", str(REPO / "governance" / "artifact-registry.json"))
).expanduser().resolve()
MODEL_MANIFEST_REGISTRY_PATH = Path(
    os.environ.get("DOCTORE_MODEL_MANIFEST_REGISTRY", str(REPO / "governance" / "model-manifest-registry.json"))
).expanduser().resolve()
ALLOWED_DOMAIN_MATRIX_PATH = Path(
    os.environ.get("DOCTORE_ALLOWED_DOMAIN_MATRIX", str(REPO / "governance" / "allowed-domain-matrix.json"))
).expanduser().resolve()
DECISION_BUNDLE_LOG_PATH = Path(
    os.environ.get("DOCTORE_DECISION_BUNDLE_LOG", "").strip()
    or str(Path(os.environ["DOCTORE_BET_LOG"]).expanduser().resolve().with_suffix(".decision-bundles.jsonl"))
).expanduser().resolve()


@dataclass(frozen=True)
class GovernanceResult:
    ok: bool
    reason_codes: list[str]
    governance: dict[str, Any]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def runtime_provenance() -> dict[str, Any]:
    return {
        "schema_version": "doctore.runtime-provenance.v1",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "repo_path": str(REPO),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git_value("status", "--porcelain")),
    }


def validate_market_governance(
    *,
    prediction_path: str,
    sport: str,
    competition: str,
    target_market: str,
    market_snapshot: dict[str, Any],
) -> GovernanceResult:
    reasons: list[str] = []
    governance: dict[str, Any] = {
        "schema_version": "doctore.governance-result.v1",
        "runtime_provenance": runtime_provenance(),
    }

    for path, code in (
        (ARTIFACT_REGISTRY_PATH, "ARTIFACT_REGISTRY_MISSING"),
        (MODEL_MANIFEST_REGISTRY_PATH, "MODEL_MANIFEST_REGISTRY_MISSING"),
        (ALLOWED_DOMAIN_MATRIX_PATH, "ALLOWED_DOMAIN_MATRIX_MISSING"),
    ):
        if not path.exists():
            reasons.append(code)

    if reasons:
        return GovernanceResult(False, reasons, governance)

    try:
        artifact_path = resolve_artifact_path(prediction_path)
        artifact_sha = content_sha256(artifact_path.read_bytes().hex())
        artifacts = _load_json(ARTIFACT_REGISTRY_PATH).get("artifacts", [])
        artifact_entry = next(
            (
                item for item in artifacts
                if item.get("path") == str(artifact_path)
                or item.get("artifact_sha256") == artifact_sha
            ),
            None,
        )
        if artifact_entry is None:
            reasons.append("ARTIFACT_NOT_REGISTERED")
            return GovernanceResult(False, reasons, governance)
        governance["artifact"] = artifact_entry
        if artifact_entry.get("status") != "APPROVED":
            reasons.append("ARTIFACT_NOT_APPROVED")

        manifests = _load_json(MODEL_MANIFEST_REGISTRY_PATH).get("manifests", [])
        manifest_id = artifact_entry.get("manifest_id")
        manifest = next((item for item in manifests if item.get("manifest_id") == manifest_id), None)
        if manifest is None:
            reasons.append("MODEL_MANIFEST_NOT_REGISTERED")
            return GovernanceResult(False, reasons, governance)
        governance["model_manifest"] = manifest

        expected_schema_hash = manifest.get("schema_hash")
        if not expected_schema_hash:
            reasons.append("SCHEMA_HASH_MISSING")
        else:
            governance["schema_hash"] = expected_schema_hash

        calibration_version = manifest.get("calibration_version")
        if not calibration_version:
            reasons.append("CALIBRATION_VERSION_MISSING")
        else:
            governance["calibration_version"] = calibration_version

        domain_matrix = _load_json(ALLOWED_DOMAIN_MATRIX_PATH).get("domains", [])
        market_type = market_snapshot.get("market_type")
        period = market_snapshot.get("period")
        settlement_rules = market_snapshot.get("settlement_rules")
        allowed = any(
            item.get("enabled") is True
            and item.get("sport") == sport
            and item.get("competition") in {competition, "*"}
            and item.get("target_market") == target_market
            and item.get("market_type") == market_type
            and item.get("period") == period
            and item.get("settlement_rules") == settlement_rules
            for item in domain_matrix
        )
        governance["domain"] = {
            "sport": sport,
            "competition": competition,
            "target_market": target_market,
            "market_type": market_type,
            "period": period,
            "settlement_rules": settlement_rules,
            "allowed": allowed,
        }
        if not allowed:
            reasons.append("DOMAIN_NOT_ALLOWED")

        manifest_domains = manifest.get("allowed_domains", [])
        if manifest_domains and not any(
            item.get("sport") == sport
            and item.get("competition") in {competition, "*"}
            and item.get("target_market") == target_market
            for item in manifest_domains
        ):
            reasons.append("MODEL_MANIFEST_DOMAIN_MISMATCH")

        expected_artifact_hash = artifact_entry.get("artifact_sha256")
        if expected_artifact_hash and expected_artifact_hash != artifact_sha:
            reasons.append("ARTIFACT_HASH_MISMATCH")
        governance["artifact_actual_sha256"] = artifact_sha

    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append("GOVERNANCE_REGISTRY_INVALID")
        governance["error"] = str(exc)

    return GovernanceResult(not reasons, reasons, governance)


def build_decision_bundle(
    *,
    run_id: str,
    decision_input: dict[str, Any],
    decision_output: dict[str, Any],
    governance: dict[str, Any],
    approval: dict[str, Any] | None,
    log_result: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "doctore.immutable-decision-bundle.v1",
        "run_id": run_id,
        "decision_input": decision_input,
        "decision_output": decision_output,
        "governance": governance,
        "approval": approval,
        "log_result": log_result,
    }
    payload["bundle_sha256"] = content_sha256(payload)
    return payload


def append_decision_bundle(bundle: dict[str, Any]) -> None:
    DECISION_BUNDLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if DECISION_BUNDLE_LOG_PATH.exists():
        for line in DECISION_BUNDLE_LOG_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            existing = json.loads(line)
            if existing.get("bundle_sha256") == bundle["bundle_sha256"]:
                return
    with DECISION_BUNDLE_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")
        handle.flush()
        os.fsync(handle.fileno())
