from __future__ import annotations

from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "doctore_mcp"


class McpModuleBoundaryTests(unittest.TestCase):
    def test_required_modules_exist(self) -> None:
        for name in ("tools.py", "decision_adapter.py", "ledger.py", "settlement.py", "schemas.py"):
            self.assertTrue((MCP_ROOT / name).is_file(), msg=name)

    def test_server_is_only_bootstrap_and_compatibility_exports(self) -> None:
        path = MCP_ROOT / "server.py"
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(lines), 60)
        tree = ast.parse("\n".join(lines))
        function_defs = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual([], function_defs)

    def test_mcp_does_not_import_private_no_vig(self) -> None:
        for path in MCP_ROOT.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("_no_vig", source, msg=str(path))

    def test_decision_core_uses_public_market_probability_api(self) -> None:
        source = (ROOT / "src" / "bet_decision_core.py").read_text(encoding="utf-8")
        self.assertIn("from market_probability import calculate_market_probabilities", source)
        self.assertNotIn("def _no_vig", source)

    def test_parser_requires_explicit_capture_time(self) -> None:
        source = (MCP_ROOT / "schemas.py").read_text(encoding="utf-8")
        self.assertIn("captured_at: str = Field(...", source)


if __name__ == "__main__":
    unittest.main()
