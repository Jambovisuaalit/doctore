from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DOCTORE_REPO_PATH", str(ROOT))
os.environ.setdefault(
    "DOCTORE_BET_LOG",
    str(Path(tempfile.gettempdir()) / "doctore-governance-hashing-test.csv"),
)

from doctore_mcp import governance  # noqa: E402
from doctore_mcp.runtime import content_sha256, file_sha256  # noqa: E402


class GovernanceArtifactHashingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_paths = (
            governance.ARTIFACT_REGISTRY_PATH,
            governance.MODEL_MANIFEST_REGISTRY_PATH,
            governance.ALLOWED_DOMAIN_MATRIX_PATH,
        )
        self.temp = tempfile.TemporaryDirectory(prefix="doctore-governance-hash-")
        self.temp_path = Path(self.temp.name)
        governance.ARTIFACT_REGISTRY_PATH = self.temp_path / "artifact-registry.json"
        governance.MODEL_MANIFEST_REGISTRY_PATH = self.temp_path / "model-manifest-registry.json"
        governance.ALLOWED_DOMAIN_MATRIX_PATH = self.temp_path / "allowed-domain-matrix.json"
        self.artifact = (ROOT / "examples" / "sample-model-output.json").resolve()
        self.market = {
            "market_type": "moneyline",
            "period": "full_game",
            "settlement_rules": "action_including_extra_innings",
        }

    def tearDown(self) -> None:
        (
            governance.ARTIFACT_REGISTRY_PATH,
            governance.MODEL_MANIFEST_REGISTRY_PATH,
            governance.ALLOWED_DOMAIN_MATRIX_PATH,
        ) = self.original_paths
        self.temp.cleanup()

    def _write_registries(self, artifact_sha256: str) -> None:
        governance.ARTIFACT_REGISTRY_PATH.write_text(
            json.dumps({
                "schema_version": "doctore.artifact-registry.v1",
                "artifacts": [{
                    "artifact_id": "sample-model-output",
                    "path": str(self.artifact),
                    "artifact_sha256": artifact_sha256,
                    "manifest_id": "sample-manifest",
                    "status": "APPROVED",
                }],
            }),
            encoding="utf-8",
        )
        governance.MODEL_MANIFEST_REGISTRY_PATH.write_text(
            json.dumps({
                "schema_version": "doctore.model-manifest-registry.v1",
                "manifests": [{
                    "manifest_id": "sample-manifest",
                    "model_name": "sample-model",
                    "model_version": "1.0.0",
                    "schema_hash": "feature-schema-v1",
                    "calibration_version": "calibration-v1",
                    "allowed_domains": [{
                        "sport": "MLB",
                        "competition": "MLB",
                        "target_market": "full_game_moneyline",
                    }],
                }],
            }),
            encoding="utf-8",
        )
        governance.ALLOWED_DOMAIN_MATRIX_PATH.write_text(
            json.dumps({
                "schema_version": "doctore.allowed-domain-matrix.v1",
                "domains": [{
                    "sport": "MLB",
                    "competition": "MLB",
                    "target_market": "full_game_moneyline",
                    "market_type": "moneyline",
                    "period": "full_game",
                    "settlement_rules": "action_including_extra_innings",
                    "enabled": True,
                }],
            }),
            encoding="utf-8",
        )

    def _validate(self):
        return governance.validate_market_governance(
            prediction_path=str(self.artifact),
            sport="MLB",
            competition="MLB",
            target_market="full_game_moneyline",
            market_snapshot=self.market,
        )

    def test_file_sha256_matches_conventional_raw_byte_digest(self) -> None:
        raw = self.artifact.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        self.assertEqual(expected, file_sha256(self.artifact))
        self.assertNotEqual(expected, content_sha256(raw.hex()))

    def test_governance_accepts_registry_with_raw_file_sha256(self) -> None:
        expected = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self._write_registries(expected)
        result = self._validate()
        self.assertTrue(result.ok, msg=result.reason_codes)
        self.assertEqual([], result.reason_codes)
        self.assertEqual(expected, result.governance["artifact_actual_sha256"])

    def test_legacy_hex_json_hash_is_rejected(self) -> None:
        legacy_hash = content_sha256(self.artifact.read_bytes().hex())
        self._write_registries(legacy_hash)
        result = self._validate()
        self.assertFalse(result.ok)
        self.assertIn("ARTIFACT_HASH_MISMATCH", result.reason_codes)
        self.assertEqual(file_sha256(self.artifact), result.governance["artifact_actual_sha256"])


if __name__ == "__main__":
    unittest.main()
