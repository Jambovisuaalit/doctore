from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "model-probability" / "scripts" / "validate_model_output.py"
SAMPLE = ROOT / "examples" / "sample-model-output.json"


class SampleModelOutputTests(unittest.TestCase):
    def test_repository_sample_is_validated(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(SAMPLE)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout, msg=result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(output["decision"], "VALIDATED")
        self.assertEqual(output["errors"], [])


if __name__ == "__main__":
    unittest.main()
