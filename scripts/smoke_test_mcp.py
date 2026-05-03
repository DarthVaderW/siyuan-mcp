from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "siyuan_research_mcp" / "server.py"


def codex_config_params(env: dict[str, str]) -> StdioServerParameters:
    if os.name == "nt":
        return StdioServerParameters(
            command=str(ROOT / "scripts" / "run_siyuan_mcp_uv.cmd"),
            args=[],
            env=env,
        )
    return StdioServerParameters(
        command="/bin/bash",
        args=[str(ROOT / "scripts" / "run_siyuan_mcp_uv.sh")],
        env=env,
    )


async def run(call_ping: bool, use_config_command: bool) -> int:
    env = os.environ.copy()
    env.setdefault("SIYUAN_BASE_URL", "http://127.0.0.1:6806")

    if use_config_command:
        params = codex_config_params(env)
    else:
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print(f"tools: {len(tool_names)}")
            for name in tool_names:
                print(f"- {name}")

            if call_ping:
                result = await session.call_tool("siyuan_ping", {})
                print("siyuan_ping:")
                for item in result.content:
                    print(getattr(item, "text", item))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ping", action="store_true", help="Also call siyuan_ping.")
    parser.add_argument(
        "--config-command",
        action="store_true",
        help="Launch through the platform-specific wrapper matching Codex config.",
    )
    parser.add_argument(
        "--expect-tool",
        action="append",
        default=[],
        help="Tool name that must be present. Can be passed multiple times.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_with_expectations(args)))


async def run_with_expectations(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    env.setdefault("SIYUAN_BASE_URL", "http://127.0.0.1:6806")

    if args.config_command:
        params = codex_config_params(env)
    else:
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            print(f"tools: {len(tool_names)}")
            for name in tool_names:
                print(f"- {name}")

            missing = sorted(set(args.expect_tool) - set(tool_names))
            if missing:
                print("missing expected tools:")
                for name in missing:
                    print(f"- {name}")
                return 1

            if args.ping:
                result = await session.call_tool("siyuan_ping", {})
                print("siyuan_ping:")
                for item in result.content:
                    print(getattr(item, "text", item))

    return 0


if __name__ == "__main__":
    main()
