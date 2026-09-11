"""Runtime configuration and deterministic utility helpers for Doctore MCP."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import sys

DOCTORE_REPO_PATH = os.environ.get("DOCTORE_REPO_PATH", "").strip()
DOCTORE_BET_LOG_RAW = os.environ.get("DOCTORE_BET_LOG", "").strip()
if not DOCTORE_REPO_PATH:
    raise RuntimeError("DOCTORE_REPO_PATH is required and must point to the doctore repository root")
if not DOCTORE_BET_LOG_RAW:
    raise RuntimeError("DOCTORE_BET_LOG is required; no sample-log fallback is permitted")

REPO = Path(DOCTORE_REPO_PATH).expanduser().resolve()
SRC = REPO / "src"
if not (SRC / "bet_decision_core.py").exists():
    raise RuntimeError(f"canonical decision core not found: {SRC / 'bet_decision_core.py'}")
if not (SRC / "model_output_adapter.py").exists():
    raise RuntimeError(f"model output adapter not found: {SRC / 'model_output_adapter.py'}")

for path in (SRC, REPO):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

BET_LOG_PATH = Path(DOCTORE_BET_LOG_RAW).expanduser().resolve()
CLOSING_SNAPSHOT_PATH = Path(
    os.environ.get(
        "DOCTORE_CLOSING_SNAPSHOT_LOG",
        str(BET_LOG_PATH.with_suffix(BET_LOG_PATH.suffix + ".closing.jsonl")),
    )
).expanduser().resolve()
MAX_SNAPSHOT_AGE_MINUTES = float(os.environ.get("DOCTORE_MAX_SNAPSHOT_AGE_MIN", "5"))
MODEL_ARTIFACT_ROOT = Path(
    os.environ.get("DOCTORE_MODEL_ARTIFACT_ROOT", str(REPO / "artifacts"))
).expanduser().resolve()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def minutes_since(value: str) -> float:
    return (datetime.now(timezone.utc) - parse_time(value).astimezone(timezone.utc)).total_seconds() / 60


def content_sha256(value: Any) -> str:
    """Hash a structured value after deterministic JSON canonicalization."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Return the conventional SHA-256 digest of the file's raw bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    allowed_roots = [MODEL_ARTIFACT_ROOT, (REPO / "examples").resolve()]
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise ValueError(
            "prediction_path must be inside DOCTORE_MODEL_ARTIFACT_ROOT or repository examples"
        )
    return path