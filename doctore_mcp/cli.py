"""Explicit local configuration without importing the runtime before validation."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Doctore personal stdio MCP server")
    parser.add_argument("--repo", default=os.environ.get("DOCTORE_REPO_PATH") or str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--bet-log", default=os.environ.get("DOCTORE_BET_LOG"), help="Private CSV ledger path (required; no sample fallback)")
    parser.add_argument("--mode", choices=("research", "production"), default="research", help="Operator startup mode; never read from client payload/environment")
    parser.add_argument("--authority-root", help="Absolute private operator authority directory for production")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print-config", action="store_true", help="Print a client mcpServers configuration without starting the server")
    mode.add_argument("--check", action="store_true", help="Validate startup and list registered capabilities without writing a ledger")
    args = parser.parse_args(argv)
    if not args.bet_log:
        parser.error("--bet-log or DOCTORE_BET_LOG is required")
    repo = Path(args.repo).expanduser().resolve()
    ledger = Path(args.bet_log).expanduser().resolve()
    for required in ("src/bet_decision_core.py", "src/model_output_adapter.py", "contracts/model-output.schema.json", "doctore_mcp/server.py"):
        if not (repo / required).is_file():
            parser.error(f"incomplete Doctore checkout: missing {required}")
    # Refuse to accidentally run imported code from another checkout.
    if repo != Path(__file__).resolve().parents[1]:
        parser.error("--repo must identify the checkout containing this launcher")
    if ledger.exists() and not ledger.is_file():
        parser.error("bet log must be a file path")
    if args.mode == "production" and not args.authority_root:
        parser.error("production requires --authority-root")
    authority_args = ["--mode", args.mode]
    if args.authority_root:
        authority_args += ["--authority-root", str(Path(args.authority_root).expanduser().resolve())]
    if args.print_config:
        print(json.dumps({"mcpServers": {"doctore": {
            "command": sys.executable,
            "args": [str(repo / "doctore_mcp" / "launch.py"), "--repo", str(repo), "--bet-log", str(ledger), *authority_args],
        }}}, indent=2))
        return 0
    os.environ["DOCTORE_REPO_PATH"] = str(repo)
    os.environ["DOCTORE_BET_LOG"] = str(ledger)
    from .risk_authority import configure
    try:
        configure(args.mode, args.authority_root)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    from .server import mcp
    if args.check:
        async def inspect():
            return {
                "transport": "stdio",
                "tools": [tool.name for tool in await mcp.list_tools()],
                "resources": [str(resource.uri) for resource in await mcp.list_resources()],
                "prompts": [prompt.name for prompt in await mcp.list_prompts()],
            }
        print(json.dumps(asyncio.run(inspect()), indent=2))
        return 0
    mcp.run(transport="stdio")
    return 0
