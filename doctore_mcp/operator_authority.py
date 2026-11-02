"""Operator-only signer/publisher; never registered as an MCP tool.

Run via python -m doctore_mcp.operator_authority. The same ledger lock serializes
policy rotation, evidence publication and approval reservation commits.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile


def publish(root: Path, kind: str, payload: dict):
    from . import risk_authority as authority
    from .ledger import log_lock
    if kind not in {"policy", "evidence"}:
        raise ValueError("unsupported authority document")
    info = root.lstat()
    import stat
    if not root.is_absolute() or not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("D3_AUTHORITY_ROOT_PERMISSIONS")
    now = datetime.now(timezone.utc)
    from .runtime import parse_time
    if not parse_time(payload["valid_from"]) <= now < parse_time(payload["expires_at"]):
        raise ValueError("D3_AUTHORITY_EXPIRED")
    with log_lock():
        if kind == "policy":
            authority._validate_policy(payload)
        key = authority._read_private(root / "authority.key")
        if len(key) != 32:
            raise ValueError("D3_AUTHORITY_INVALID_KEY")
        signature = hmac.new(key, authority._canonical({"kind": kind, "payload": payload}), hashlib.sha256).hexdigest()
        data = authority._canonical({"payload": payload, "signature": signature})
        fd, temporary = tempfile.mkstemp(prefix=kind + ".", dir=root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, root / (kind + ".json"))
            directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-root", required=True)
    parser.add_argument("--bet-log", required=True)
    parser.add_argument("--kind", required=True, choices=("policy", "evidence"))
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    os.environ["DOCTORE_REPO_PATH"] = str(Path(__file__).resolve().parents[1])
    os.environ["DOCTORE_BET_LOG"] = str(Path(args.bet_log).expanduser().resolve())
    publish(Path(args.authority_root).expanduser(), args.kind, json.loads(Path(args.payload).read_text()))
    print("Published authenticated authority document under the shared ledger lock")


if __name__ == "__main__":
    main()
