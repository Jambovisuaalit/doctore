#!/usr/bin/env python3
"""Run the shared smoke cases through the official Python MCP stdio client.

No npm, sports-data API calls or persistent user state is needed. Tennis network
access is explicitly disabled, matching the Inspector CI environment.
"""
from __future__ import annotations

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import run_inspector_smoke_v2 as suite


async def call(base, method, tool, params):
    env = dict(os.environ)
    for index, value in enumerate(base):
        if value == "-e":
            key, content = base[index + 1].split("=", 1)
            env[key] = content
    server = StdioServerParameters(command=base[-2], args=[base[-1]], env=env)
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            if method == "tools/list":
                return (await session.list_tools()).model_dump_json()
            result = await session.call_tool(tool, {"params": params})
            if result.isError:
                raise RuntimeError(f"{tool}: {result.model_dump_json()}")
            return result.model_dump_json()


def run(base, *, method, tool=None, params=None):
    output = asyncio.run(call(base, method, tool, params))
    print(f"PASS stdio {tool or method}", flush=True)
    return output


if __name__ == "__main__":
    suite._run = run
    raise SystemExit(suite.main())
