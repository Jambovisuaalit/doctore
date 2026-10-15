from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OffenseAcquisitionCliTests(unittest.TestCase):
    def test_cli_help_executes_real_parser(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "acquire_mlb_v4_offense_history.py"), "--help"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--season", result.stdout)
        self.assertIn("--output-dir", result.stdout)
        self.assertIn("--workers", result.stdout)

    def test_manifest_sha_source_uses_real_newline(self):
        source = (ROOT / "scripts" / "acquire_mlb_v4_offense_history.py").read_text(encoding="utf-8")
        self.assertIn('write_text(sha256_bytes(raw)+"\\n", encoding="utf-8")', source)
        self.assertNotIn('write_text(sha256_bytes(raw)+"\\\\n")', source)


if __name__ == "__main__":
    unittest.main()
