"""Materialize and verify the canonical repository session-v1 MCP baseline.

The committed Base64 archive is preserved byte-for-byte. P0 verification found
three deterministic corruption artifacts in the decoded repository payload that
prevented Python from parsing it. We therefore verify the archived payload first,
apply only the three documented byte repairs, and then verify the repaired source
used by the golden differential suite.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import base64
import hashlib

BASELINE_DIR = Path(__file__).resolve().parent
PART_GLOB = "server.py.b64.part*"
CANONICAL_BASE64_SHA256 = "4d69e0f2d8656b8538d2669692bc1be7c4cdd5a0ba7010274c9c1957262660e9"
ARCHIVED_DECODED_SOURCE_SHA256 = "2fdebce572f359df841ff55a4d67c2a59848f6264dd5e27ab15f8a081d570bfb"
REPAIRED_SOURCE_SHA256 = "571b130b6a6d81066a45511722948efd6908095011356055884d9226e75aede7"
# Compatibility alias consumed by the historical differential test contract.
SOURCE_SHA256 = REPAIRED_SOURCE_SHA256

LEGACY_RECORDED_SOURCE_SHA256 = "305bba59be07a45f7c1225ec774dc0136f383be8abaa9348092875d4f2139395"
LEGACY_RECORDED_BASE64_SHA256 = "78cda8f40f414f6769dc6b88db50fcd465782921bb69898eb6afd96df4b9de32"

_REPAIRS: tuple[tuple[bytes, bytes], ...] = (
    (
        b'\n       try:\n            await ctx.report_progress(0.6, "Lasketaan edge ja Kelly-panos...")\n        except ValueError:',
        b'\n        try:\n            await ctx.report_progress(0.6, "Lasketaan edge ja Kelly-panos...")\n        except ValueError:',
    ),
    (
        b'\n  rams.model_output.get("brier_score"),',
        b'',
    ),
    (
        b'# ----------------------------------------------------------------------------\n-\n# 7. Portfolio-status',
        b'# ----------------------------------------------------------------------------\n# 7. Portfolio-status',
    ),
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archived_source_bytes() -> bytes:
    """Return the decoded committed archive after exact integrity checks."""
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
    if decoded_hash != ARCHIVED_DECODED_SOURCE_SHA256:
        raise RuntimeError(
            "baseline archived decoded SHA-256 mismatch: "
            f"expected={ARCHIVED_DECODED_SOURCE_SHA256} actual={decoded_hash}"
        )
    return decoded


def source_bytes() -> bytes:
    """Return the minimally repaired, executable baseline for differential tests."""
    source = archived_source_bytes()
    for old, new in _REPAIRS:
        occurrences = source.count(old)
        if occurrences != 1:
            raise RuntimeError(
                "baseline repair precondition failed: "
                f"expected exactly one occurrence, found {occurrences} for {old!r}"
            )
        source = source.replace(old, new, 1)

    repaired_hash = _sha256(source)
    if repaired_hash != REPAIRED_SOURCE_SHA256:
        raise RuntimeError(
            "baseline repaired source SHA-256 mismatch: "
            f"expected={REPAIRED_SOURCE_SHA256} actual={repaired_hash}"
        )
    return source


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
        "verified repaired repository session-v1 baseline "
        f"archive_decoded_sha256={ARCHIVED_DECODED_SOURCE_SHA256} "
        f"repaired_sha256={REPAIRED_SOURCE_SHA256} "
        f"canonical_base64_sha256={CANONICAL_BASE64_SHA256} "
        f"bytes={len(source)} repairs={len(_REPAIRS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
