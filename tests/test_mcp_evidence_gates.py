"""Independent unit checks for timestamp and registry evidence gates."""
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from doctore_mcp.evidence_gates import classify_quote, verify_registry


class EvidenceGateTests(unittest.TestCase):
    def test_market_state(self):
        self.assertEqual(classify_quote("2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z"), "PREMATCH")
        self.assertEqual(classify_quote("2026-11-02T11:00:00Z", "2026-11-02T11:00:00Z"), "POST_START_UNKNOWN")
        self.assertEqual(classify_quote("2026-11-02T11:01:00Z", "2026-11-02T11:00:00Z", live_verified=True), "IN_PLAY")
        with self.assertRaises(ValueError):
            classify_quote("2026-11-02T10:00:00", "2026-11-02T11:00:00Z")

    def test_registry_blocks_missing_artifacts(self):
        prediction = {"event_id": "event-1", "model": {"model_version": "v1",
            "feature_cutoff_at": "2026-11-02T09:00:00Z",
            "prediction_generated_at": "2026-11-02T10:00:00Z"},
            "market": {"settlement_rules": "standard", "commence_time": "2026-11-02T11:00:00Z"}}
        manifest = {"event_id": "event-1", "model_version": "v1",
            "calibrator_version": "c1", "market_rules": "standard"}
        oos = dict(manifest, OOS_validation_status="PASS")
        errors = verify_registry(manifest, {"calibrator_version": "c1"}, oos, prediction)
        self.assertIn("MODEL_ARTIFACT_UNVERIFIED", errors)
        self.assertIn("CALIBRATOR_ARTIFACT_UNVERIFIED", errors)

    def test_registry_matching_artifacts(self):
        with TemporaryDirectory() as tmp:
            model, cal = Path(tmp) / "model.bin", Path(tmp) / "cal.bin"
            model.write_bytes(b"model"); cal.write_bytes(b"calibration")
            manifest = {"event_id": "e", "model_version": "v1", "calibrator_version": "c1",
                "market_rules": "standard",
                "model_artifact_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "calibration_artifact_sha256": hashlib.sha256(cal.read_bytes()).hexdigest()}
            oos = {k: manifest[k] for k in ("event_id", "model_version", "calibrator_version", "market_rules")}
            oos["OOS_validation_status"] = "PASS"
            prediction = {"event_id": "e", "model": {"model_version": "v1",
                "feature_cutoff_at": "2026-11-02T09:00:00Z",
                "prediction_generated_at": "2026-11-02T10:00:00Z"},
                "market": {"settlement_rules": "standard", "commence_time": "2026-11-02T11:00:00Z"}}
            self.assertEqual(verify_registry(manifest, {"calibrator_version": "c1"}, oos, prediction,
                model_path=model, calibrator_path=cal), [])
            oos["OOS_validation_status"] = "FAIL"
            self.assertIn("OOS_NOT_PASS", verify_registry(manifest, {"calibrator_version": "c1"}, oos, prediction,
                model_path=model, calibrator_path=cal))


if __name__ == "__main__":
    unittest.main()
