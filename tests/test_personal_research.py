from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKET_SCRIPT = ROOT / "research" / "scripts" / "create_review_packet.py"
ADAPTER_SCRIPT = ROOT / "research" / "local_adapters" / "csv_market_snapshot.py"
REVIEW_SCRIPT = ROOT / "research" / "human_review" / "append_review.py"
MODEL_OUTPUT = ROOT / "examples" / "sample-model-output.json"


def market_snapshot() -> dict:
    return {
        "event_id": "MLB-EXAMPLE-001",
        "event": {
            "event_id": "MLB-EXAMPLE-001",
            "sport": "MLB",
            "competition": "MLB",
            "event_start_at": "2026-07-23T20:10:00Z",
            "status": "scheduled",
            "participants": ["Example Away", "Example Home"],
            "venue": None,
            "source": "synthetic-test",
            "retrieved_at": "2026-07-23T18:00:00Z",
        },
        "market": {
            "market_id": "MLB-EXAMPLE-001-ML-AWAY",
            "book": "Pinnacle",
            "market_type": "moneyline",
            "period": "full_game",
            "line": None,
            "selection": "Example Away",
            "odds_decimal": 2.10,
            "snapshot_at": "2026-07-23T18:00:00Z",
            "outcomes": [
                {"selection": "Example Away", "odds_decimal": 2.10},
                {"selection": "Example Home", "odds_decimal": 1.75},
            ],
        },
    }


class PersonalResearchTests(unittest.TestCase):
    def test_review_packet_requires_human_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            market_path = temp / "market.json"
            output_path = temp / "packet.json"
            market_path.write_text(json.dumps(market_snapshot()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKET_SCRIPT),
                    "--market-snapshot",
                    str(market_path),
                    "--model-output",
                    str(MODEL_OUTPUT),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            packet = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(packet["gate"], "HUMAN_REVIEW_REQUIRED")
            self.assertEqual(packet["human_review"]["status"], "pending")
            self.assertFalse(packet["human_review"]["automatic_execution"])
            self.assertEqual(len(packet["packet_sha256"]), 64)

    def test_csv_adapter_creates_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            csv_path = temp / "market.csv"
            output_path = temp / "market.json"
            fieldnames = [
                "event_id", "sport", "competition", "event_start_at", "status",
                "participant_1", "participant_2", "venue", "source", "retrieved_at",
                "market_id", "book", "market_type", "period", "line", "selection",
                "odds_decimal", "snapshot_at", "outcome_1_selection",
                "outcome_1_odds_decimal", "outcome_2_selection", "outcome_2_odds_decimal",
            ]
            row = {
                "event_id": "NBA-EXAMPLE-001",
                "sport": "NBA",
                "competition": "NBA",
                "event_start_at": "2026-07-23T20:00:00Z",
                "status": "scheduled",
                "participant_1": "Away",
                "participant_2": "Home",
                "venue": "",
                "source": "synthetic-test",
                "retrieved_at": "2026-07-23T18:00:00Z",
                "market_id": "NBA-EXAMPLE-001-TOTAL",
                "book": "Pinnacle",
                "market_type": "total",
                "period": "full_game",
                "line": "224.5",
                "selection": "over",
                "odds_decimal": "1.95",
                "snapshot_at": "2026-07-23T18:00:00Z",
                "outcome_1_selection": "over",
                "outcome_1_odds_decimal": "1.95",
                "outcome_2_selection": "under",
                "outcome_2_odds_decimal": "1.95",
            }
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(row)
            result = subprocess.run(
                [sys.executable, str(ADAPTER_SCRIPT), "--csv", str(csv_path), "--output", str(output_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["market"]["line"], 224.5)
            self.assertEqual(payload["event"]["participants"], ["Away", "Home"])

    def test_review_log_is_hash_chained_and_blocks_stake_increase(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            log_path = temp / "reviews.jsonl"
            base = {
                "review_id": "review-001",
                "packet_sha256": "0" * 64,
                "prediction_id": "prediction-001",
                "model_version": "model-v1",
                "reviewed_at": "2026-07-23T18:30:00Z",
                "system_decision": "BET",
                "human_decision": "approved",
                "model_probability_changed": False,
                "proposed_stake": 100.0,
                "approved_stake": 50.0,
                "reason": "Reduced after manual risk review.",
            }
            first_path = temp / "first.json"
            first_path.write_text(json.dumps(base), encoding="utf-8")
            first = subprocess.run(
                [sys.executable, str(REVIEW_SCRIPT), "--review", str(first_path), "--log", str(log_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)

            second_payload = dict(base)
            second_payload.update({
                "review_id": "review-002",
                "prediction_id": "prediction-002",
                "human_decision": "rejected",
                "approved_stake": 0.0,
                "reason": "Rejected after lineup change.",
            })
            second_path = temp / "second.json"
            second_path.write_text(json.dumps(second_payload), encoding="utf-8")
            second = subprocess.run(
                [sys.executable, str(REVIEW_SCRIPT), "--review", str(second_path), "--log", str(log_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[1]["previous_record_sha256"], records[0]["record_sha256"])

            invalid = dict(base)
            invalid.update({"review_id": "review-003", "approved_stake": 125.0})
            invalid_path = temp / "invalid.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
            blocked = subprocess.run(
                [sys.executable, str(REVIEW_SCRIPT), "--review", str(invalid_path), "--log", str(log_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("may not exceed", blocked.stderr)


if __name__ == "__main__":
    unittest.main()
