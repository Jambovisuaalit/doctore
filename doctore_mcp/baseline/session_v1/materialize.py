"""Materialize and verify the exact original session-v1 MCP server source."""
from __future__ import annotations

from pathlib import Path
import argparse
import base64
import hashlib

BASELINE_DIR = Path(__file__).resolve().parent
PART_GLOB = "server.py.b64.part*"
SOURCE_SHA256 = "305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395"
BASE64_SHA256 = "78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32"


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

    # Base64 is semantically whitespace-insensitive. Repository writes and archive
    # transports may preserve or normalize wrapping/newline bytes differently, so
    # accept the locked archive hash in either its raw stored representation or its
    # canonical whitespace-free representation. The decoded source SHA remains the
    # final exact-byte integrity gate and is never relaxed.
    encoded_raw = b"".join(part.read_bytes() for part in parts)
    encoded_canonical = b"".join(encoded_raw.split())
    raw_hash = _sha256(encoded_raw)
    canonical_hash = _sha256(encoded_canonical)

    if BASE64_SHA256 not in {raw_hash, canonical_hash}:
        raise RuntimeError(
            "baseline base64 archive SHA-256 mismatch: "
            f"expected={BASE64_SHA256} raw={raw_hash} canonical={canonical_hash}"
        )

    decoded = base64.b64decode(encoded_canonical, validate=True)
    decoded_hash = _sha256(decoded)
    if decoded_hash != SOURCE_SHA256:
        raise RuntimeError(
            "baseline source SHA-256 mismatch: "
            f"expected={SOURCE_SHA256} actual={decoded_hash}"
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
    print(f"verified session-v1 server.py sha256={SOURCE_SHA256} bytes={len(source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
