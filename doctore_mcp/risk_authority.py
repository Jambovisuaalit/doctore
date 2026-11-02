"""Operator-owned production risk authority. No MCP payload can configure it.

Production policy and exact input attestations are authenticated with a private
operator key. This is a local trust boundary, not a provider/account synchronizer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from types import SimpleNamespace
import hashlib
import hmac
import json
import math
import os
import stat

from .runtime import BET_LOG_PATH, content_sha256, parse_time

_MODE = "research"
_ROOT: Path | None = None


class AuthorityError(ValueError):
    """A stable, non-secret reason suitable for decision and approval audit."""


def mode() -> str:
    return _MODE


def _read_private(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise AuthorityError("D3_AUTHORITY_FILE_PERMISSIONS")
            data = handle.read(2_000_001)
            if len(data) > 2_000_000:
                raise AuthorityError("D3_AUTHORITY_FILE_TOO_LARGE")
            return data
    except OSError as exc:
        raise AuthorityError("D3_AUTHORITY_FILE_UNAVAILABLE") from exc


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise AuthorityError("D3_AUTHORITY_INVALID_JSON") from exc


def _document(kind: str, now: datetime) -> tuple[dict, str]:
    if _ROOT is None:
        raise AuthorityError("D3_AUTHORITY_NOT_CONFIGURED")
    key = _read_private(_ROOT / "authority.key")
    if len(key) != 32:
        raise AuthorityError("D3_AUTHORITY_INVALID_KEY")
    try:
        envelope = json.loads(_read_private(_ROOT / f"{kind}.json"))
        if set(envelope) != {"payload", "signature"}:
            raise ValueError()
        payload = envelope["payload"]
        expected = hmac.new(key, _canonical({"kind": kind, "payload": payload}), hashlib.sha256).hexdigest()
        if not isinstance(envelope["signature"], str) or not hmac.compare_digest(envelope["signature"], expected):
            raise AuthorityError("D3_AUTHORITY_SIGNATURE_INVALID")
        if not parse_time(payload["valid_from"]) <= now < parse_time(payload["expires_at"]):
            raise AuthorityError("D3_AUTHORITY_EXPIRED")
        return payload, content_sha256(payload)
    except AuthorityError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityError("D3_AUTHORITY_DOCUMENT_INVALID") from exc


def _finite(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise AuthorityError("D3_AUTHORITY_INVALID_LIMIT")
    return value


def _policy(now):
    from .schemas import schema_errors
    policy, digest = _document("policy", now)
    _validate_policy(policy)
    return policy, digest


def _validate_policy(policy):
    from .schemas import schema_errors
    required = {"schema_version", "policy_id", "policy_version", "valid_from", "expires_at", "currency", "ledger_path_sha256", "risk_policy", "limits", "providers"}
    if set(policy) != required or policy["schema_version"] != "doctore.production-authority.v1":
        raise AuthorityError("D3_POLICY_INVALID")
    if not all(isinstance(policy[x], str) and policy[x].strip() for x in ("policy_id", "policy_version", "currency")):
        raise AuthorityError("D3_POLICY_INVALID")
    if schema_errors("policy", policy["risk_policy"]):
        raise AuthorityError("D3_POLICY_INVALID")
    limits = policy["limits"]
    if set(limits) != {"max_bankroll", "max_stake_amount", "max_event_exposure_fraction", "max_market_exposure_fraction"}:
        raise AuthorityError("D3_POLICY_INVALID")
    for key, value in limits.items():
        _finite(value, positive=key == "max_bankroll")
        if key.endswith("fraction") and value > 1:
            raise AuthorityError("D3_POLICY_INVALID")
    if policy["ledger_path_sha256"] != hashlib.sha256(str(BET_LOG_PATH).encode()).hexdigest():
        raise AuthorityError("D3_LEDGER_BINDING_MISMATCH")
    if set(policy["providers"]) != {"market", "model", "portfolio", "context"} or any(
        not isinstance(values, list) or not values or any(not isinstance(x, str) or not x.strip() for x in values)
        for values in policy["providers"].values()
    ):
        raise AuthorityError("D3_POLICY_INVALID")
    if policy["risk_policy"]["block_unknown_correlation"] is not True or policy["risk_policy"]["allowed_calibration_statuses"] != ["validated"]:
        raise AuthorityError("D3_POLICY_UNSAFE_PRODUCTION_DEFAULT")
    dd = policy["risk_policy"]["drawdown"]
    if not dd["warning_fraction"] <= dd["review_fraction"] <= dd["pause_fraction"]:
        raise AuthorityError("D3_POLICY_INVALID")

def configure(execution_mode: str = "research", authority_root: str | None = None):
    """Operator startup API: CLI arguments only; never environment/payload mode."""
    global _MODE, _ROOT
    if execution_mode not in {"research", "production"}:
        raise AuthorityError("D3_MODE_INVALID")
    if execution_mode == "research":
        if authority_root:
            raise AuthorityError("D3_RESEARCH_AUTHORITY_CONFLICT")
        _MODE, _ROOT = "research", None
        return
    if not authority_root or os.name != "posix":
        raise AuthorityError("D3_PRODUCTION_AUTHORITY_REQUIRED")
    root = Path(authority_root).expanduser()
    info = root.lstat()
    if not root.is_absolute() or not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise AuthorityError("D3_AUTHORITY_ROOT_PERMISSIONS")
    from .runtime import MODEL_ARTIFACT_ROOT, REPO
    resolved = root.resolve()
    if any(resolved == exposed or exposed in resolved.parents for exposed in (MODEL_ARTIFACT_ROOT.resolve(), (REPO / "examples").resolve())):
        raise AuthorityError("D3_AUTHORITY_ROOT_EXPOSED")
    previous = (_MODE, _ROOT)
    _MODE, _ROOT = "production", root.resolve()
    try:
        _policy(datetime.now(timezone.utc))
    except Exception:
        _MODE, _ROOT = previous
        raise


def intersect_policy(server: dict, client: dict) -> dict:
    """Upper bounds intersect by min; qualification minima by max; booleans OR."""
    from .schemas import schema_errors
    if schema_errors("policy", client):
        raise AuthorityError("D3_CLIENT_POLICY_INVALID")
    result = deepcopy(server)
    for key in ("minimum_ev", "minimum_edge_probability_points", "minimum_stake"):
        result[key] = max(server[key], client[key])
    for group in ("caps", "kelly_fraction", "sizing_model_weight", "freshness_seconds", "drawdown"):
        for key in server[group]:
            result[group][key] = min(server[group][key], client[group][key])
    result["allowed_calibration_statuses"] = sorted(set(server["allowed_calibration_statuses"]) & set(client["allowed_calibration_statuses"]))
    if not result["allowed_calibration_statuses"]:
        raise AuthorityError("D3_CALIBRATION_POLICY_CONFLICT")
    result["block_unknown_correlation"] = server["block_unknown_correlation"] or client["block_unknown_correlation"]
    result["human_approval_required"] = True
    return result


def prepare(params, rows: list[dict], now: datetime):
    """Verify exact authenticated inputs before conservatively reserving ledger."""
    policy, policy_hash = _policy(now)
    evidence, evidence_hash = _document("evidence", now)
    if set(evidence) != {"schema_version", "valid_from", "expires_at", "complete", "coverage", "currency", "inputs", "external_event_exposure_amount", "external_market_exposure_amount", "closed_ledger_decisions"} or evidence["schema_version"] != "doctore.production-evidence.v1" or evidence["complete"] is not True or evidence["coverage"] != "external_only":
        raise AuthorityError("D3_EVIDENCE_INCOMPLETE")
    effective = intersect_policy(policy["risk_policy"], params.risk_policy)
    if evidence["currency"] != policy["currency"] or params.portfolio_state.get("currency") != policy["currency"]:
        raise AuthorityError("D3_CURRENCY_MISMATCH")
    if _finite(params.portfolio_state.get("bankroll"), positive=True) > policy["limits"]["max_bankroll"]:
        raise AuthorityError("D3_BANKROLL_LIMIT")
    actual = {"market": params.market_snapshot, "model": params.model_output, "portfolio": params.portfolio_state, "context": params.sport_context}
    if set(evidence["inputs"]) != set(actual):
        raise AuthorityError("D3_EVIDENCE_INCOMPLETE")
    for name, value in actual.items():
        item = evidence["inputs"][name]
        if not isinstance(item, dict) or set(item) != {"sha256", "provider", "observed_at"} or item["provider"] not in policy["providers"][name]:
            raise AuthorityError("D3_PROVIDER_UNVERIFIED")
        if item["sha256"] != hashlib.sha256(_canonical(value)).hexdigest():
            raise AuthorityError("D3_INPUT_ATTESTATION_MISMATCH")
        age = (now - parse_time(item["observed_at"])).total_seconds()
        freshness_key = {"market": "market_snapshot", "model": "model_output", "portfolio": "portfolio_state", "context": "mlb_context"}[name]
        if age < 0 or age > effective["freshness_seconds"][freshness_key]:
            raise AuthorityError("D3_SOURCE_STALE")
    for key in ("external_event_exposure_amount", "external_market_exposure_amount"):
        _finite(evidence[key])
    if any(row.get("placement_status") not in {"APPROVED", "PLACED"} or row.get("currency") != policy["currency"] for row in rows):
        raise AuthorityError("D3_LEDGER_INCOMPLETE")
    for row in rows:
        _finite(float(row.get("actual_stake") or row["approved_stake"]), positive=True)
        if not row.get("event_id") or not row.get("market_id"):
            raise AuthorityError("D3_LEDGER_IDENTITY_MISSING")
    closures = evidence["closed_ledger_decisions"]
    if not isinstance(closures, dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) != 64 for k, v in closures.items()):
        raise AuthorityError("D3_CLOSURE_EVIDENCE_INVALID")
    verified_rows = deepcopy(rows)
    for original, row in zip(rows, verified_rows):
        # User-reported settlement/placement is not source verification. Never let
        # a smaller claimed placement or an unverified void release reservations.
        if closures.get(row["decision_id"]) != content_sha256(original):
            row["result"] = ""
            row["placement_status"] = "APPROVED"
            row["placed_at"] = ""
            row["actual_stake"] = max(float(row["approved_stake"]), float(row.get("actual_stake") or 0))
    prepared = params.model_copy(deep=True)
    prepared.risk_policy = effective
    from .ledger import current_approval_evaluation
    prepared = current_approval_evaluation(SimpleNamespace(evaluation=prepared), verified_rows, now)
    open_rows = [row for row in verified_rows if not row.get("result")]
    liability = lambda row: float(row.get("actual_stake") or row["approved_stake"])
    event_exposure = evidence["external_event_exposure_amount"] + sum(liability(row) for row in open_rows if row["event_id"] == params.market_snapshot["event_id"])
    market_exposure = evidence["external_market_exposure_amount"] + sum(liability(row) for row in open_rows if row["market_id"] == params.market_snapshot["market_id"])
    bankroll = prepared.portfolio_state["bankroll"]
    extra_caps = {
        "production_absolute": policy["limits"]["max_stake_amount"],
        "production_event": max(0, bankroll * policy["limits"]["max_event_exposure_fraction"] - event_exposure),
        "production_market": max(0, bankroll * policy["limits"]["max_market_exposure_fraction"] - market_exposure),
    }
    authority = {"mode": "production", "policy_id": policy["policy_id"], "policy_version": policy["policy_version"], "policy_sha256": policy_hash, "evidence_sha256": evidence_hash, "effective_policy_sha256": content_sha256(effective), "applied_caps": extra_caps, "market_max_age_seconds": effective["freshness_seconds"]["market_snapshot"]}
    return prepared, authority


def finalize(decision: dict, authority: dict, minimum_stake: float, increment: float):
    if decision["decision"] == "BET":
        cap_name, cap = min(authority["applied_caps"].items(), key=lambda item: item[1])
        if cap < decision["staking"]["final_stake"]:
            stake = float((Decimal(str(cap)) / Decimal(str(increment))).to_integral_value(rounding=ROUND_FLOOR) * Decimal(str(increment)))
            bankroll = decision["staking"]["final_stake"] / decision["staking"]["stake_fraction"]
            decision["staking"].update(final_stake=stake, stake_fraction=stake / bankroll, binding_cap=cap_name)
            if stake <= 0 or stake < minimum_stake:
                decision["decision"] = "BLOCKED"
                decision["reason_codes"] = ["D3_EXPOSURE_LIMIT"]
                decision["staking"]["final_stake"] = 0.0
                decision["staking"]["stake_fraction"] = 0.0
    decision["audit"]["risk_authority"] = authority
    decision["decision_id"] = content_sha256({"canonical_decision": decision, "authority": authority})
    return decision
