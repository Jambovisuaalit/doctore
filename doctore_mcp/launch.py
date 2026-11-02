"""Absolute-path launcher for clients whose working directory is arbitrary."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doctore_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
