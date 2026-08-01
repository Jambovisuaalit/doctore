#!/usr/bin/env python3
"""Compatibility entrypoint for the current 10-tool MCP Inspector smoke suite."""
from __future__ import annotations

from run_inspector_smoke_v2 import main


if __name__ == "__main__":
    raise SystemExit(main())
