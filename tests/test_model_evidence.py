"""Synthetic rows test the gate, never qualify a real production model."""
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from src.model_evidence import build_evidence, digest, verify_report, FIELDS


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / "oos.csv"
        self.start = datetime(2025, 1, 2, tzinfo=timezone.utc)
        self.metadata = dict(model_name="test", model_version="1", model_artifact_sha256="a"*64,
            dataset_sha256="b"*64, source_kind="synthetic", holdout_start_at=self.start.isoformat(),
            development_end_at=(self.start-timedelta(days=1)).isoformat(),
            domain=dict(sport="MLB", competition="MLB", market_type="total", target_market="full_game_total",
                        period="full_game", line=8.5, settlement_rules="test"))
        self.rows = []
        for i in range(600):
            prediction = self.start + timedelta(days=i//10, minutes=i%10)
            y = i % 2
            self.rows.append(dict(event_id=str(i), event_start_at=(prediction+timedelta(hours=2)).isoformat(),
                prediction_at=prediction.isoformat(), training_cutoff_at=self.metadata["development_end_at"],
                calibration_cutoff_at=self.metadata["development_end_at"], odds_captured_at=prediction.isoformat(),
                probability=0.8 if y else 0.2, decimal_odds=2, opposing_odds=2, outcome=y))
        self.write()

    def write(self):
        with self.csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(FIELDS))
            writer.writeheader()
            writer.writerows(self.rows)

    def test_synthetic_even_perfect_predictions_never_pass(self):
        result = build_evidence(self.csv, self.metadata)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("OBSERVED_SOURCE_REQUIRED", result["reason_codes"])
        self.assertFalse(result["production_approved"])

    def test_identical_to_market_is_not_evidence(self):
        self.metadata["source_kind"] = "observed"  # simulated source declaration
        for row in self.rows:
            row["probability"] = .5
        self.write()
        result = build_evidence(self.csv, self.metadata)
        self.assertIn("BRIER_ADVANTAGE_UNPROVEN", result["reason_codes"])
        self.assertIn("LOGLOSS_ADVANTAGE_UNPROVEN", result["reason_codes"])

    def test_frozen_holdout_leakage_and_duplicate_events_rejected(self):
        self.rows[1]["calibration_cutoff_at"] = self.rows[1]["prediction_at"]
        self.write()
        with self.assertRaisesRegex(ValueError, "holdout violation"):
            build_evidence(self.csv, self.metadata)
        self.rows[1]["calibration_cutoff_at"] = self.metadata["development_end_at"]
        self.rows[1]["event_id"] = self.rows[0]["event_id"]
        self.write()
        with self.assertRaisesRegex(ValueError, "distinct event"):
            build_evidence(self.csv, self.metadata)

    def test_nonfinite_and_stale_odds_rejected(self):
        self.rows[0]["probability"] = "nan"
        self.write()
        with self.assertRaises(ValueError):
            build_evidence(self.csv, self.metadata)
        self.rows[0]["probability"] = .2
        self.rows[0]["odds_captured_at"] = (self.start-timedelta(hours=1)).isoformat()
        self.write()
        with self.assertRaisesRegex(ValueError, "price older"):
            build_evidence(self.csv, self.metadata)

    def test_reproducible_report_needs_review_and_exact_identity(self):
        # Positive fixture checks mechanics, not actual source authenticity.
        self.metadata["source_kind"] = "observed"
        report = build_evidence(self.csv, self.metadata)
        self.assertEqual("STATISTICAL_PASS", report["status"])
        self.assertEqual(report, build_evidence(self.csv, self.metadata))
        path = Path(self.temp.name) / "report.json"
        path.write_text(json.dumps(report))
        sha = digest(path)
        manifest = dict(self.metadata, evidence_csv_path=str(self.csv))
        with self.assertRaisesRegex(ValueError, "review required"):
            verify_report(path, sha, manifest, self.metadata["domain"])
        manifest["evidence_review"] = dict(decision="APPROVED", reviewer="test-reviewer", report_sha256=sha)
        self.assertEqual(report, verify_report(path, sha, manifest, self.metadata["domain"]))
        with self.assertRaisesRegex(ValueError, "domain mismatch"):
            verify_report(path, sha, manifest, dict(self.metadata["domain"], line=9.5))
        self.rows[0]["probability"] = .3
        self.write()
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            verify_report(path, sha, manifest, self.metadata["domain"])

    def test_small_sample_and_single_day_block(self):
        self.rows = self.rows[:10]
        self.write()
        result = build_evidence(self.csv, self.metadata)
        self.assertIn("INSUFFICIENT_EVENTS", result["reason_codes"])
        self.assertIn("INSUFFICIENT_DAY_BLOCKS", result["reason_codes"])

    def test_small_average_gain_with_wide_interval_does_not_pass(self):
        self.metadata["source_kind"] = "observed"
        for i, row in enumerate(self.rows):
            row["probability"] = .51
            row["outcome"] = 1 if i // 10 < 31 else 0
        self.write()
        report = build_evidence(self.csv, self.metadata)
        self.assertGreater(report["brier"]["advantage"], 0)
        self.assertLess(report["brier"]["advantage_ci"][0], 0)
        self.assertEqual("BLOCKED", report["status"])

    def test_integer_line_requires_push_aware_evidence_workflow(self):
        self.metadata["domain"]["line"] = 8
        with self.assertRaisesRegex(ValueError, "half-line"):
            build_evidence(self.csv, self.metadata)
