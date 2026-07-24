"""Personal stdio MCP server for the canonical Doctore decision pipeline."""
from __future__ import annotations

if __package__:
    from .tools import mcp
else:  # direct `python doctore_mcp/server.py`
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from doctore_mcp.tools import mcp


if __name__ == "__main__":
    mcp.run()
