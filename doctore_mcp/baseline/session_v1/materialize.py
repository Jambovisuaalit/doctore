"""Materialize and verify the canonical repository session-v1 MCP baseline."""
from __future__ import annotations

from pathlib import Path
import argparse
import base64
import hashlib

BASELINE_DIR = Path(__file__).resolve().parent
PART_GLOB = "server.py.b64.part*"
CANONICAL_SOURCE_SHA256 = "2fdebce572f359df841ff55a4d67c2a59848f6264dd5e27ab15f8a081d570bfb"
# Compatibility alias consumed by the historical differential test contract.
SOURCE_SHA256 = CANONICAL_SOURCE_SHA256
LEGACY_RECORDED_SOURCE_SHA256 = "305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395"
CANONICAL_BASE64_SHA256 = "4d69e0f2d8656b8538d2669692bc1be7c4cdd5a0ba7010274c9c1957262660e9"
LEGACY_RECORDED_BASE64_SHA256 = "78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_bytes() -> bytes:
    parts = sorted(BASELINE_DIR.glob(PART_GLOB))
    if [part.name for part in parts] != [
        "server.py.b64.part00",
        "server.py.b64.part01",
        "server.py.b64.part02",
        "server.py.b64.part03",
    ]:
        raise RuntimeError("baseline archive must contain exactly four ordered parts")

    encoded_raw = b"".join(part.read_bytes() for part in parts)
    encoded_canonical = b"".join(encoded_raw.split())
    canonical_hash = _sha256(encoded_canonical)
    if canonical_hash != CANONICAL_BASE64_SHA256:
        raise RuntimeError(
            "baseline canonical base64 SHA-256 mismatch: "
            f"expected={CANONICAL_BASE64_SHA256} actual={canonical_hash}"
        )

    decoded = base64.b64decode(encoded_canonical, validate=True)
    decoded_hash = _sha256(decoded)
    if decoded_hash != CANONICAL_SOURCE_SHA256:
        raise RuntimeError(
            "baseline source SHA-256 mismatch: "
            f"expected={CANONICAL_SOURCE_SHA256} actual={decoded_hash}"
        )
    return decoded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    source = source_bytes()
    if args.output and not args.verify_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(source)
    print(
        "verified canonical repository session-v1 server.py "
        f"sha256={CANONICAL_SOURCE_SHA256} "
        f"canonical_base64_sha256={CANONICAL_BASE64_SHA256} "
        f"bytes={len(source)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
