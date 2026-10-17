"""Thin wrapper over the MCP SDK client used by the agent, the gateway and the test runner."""

import json

from mcp import Client

from . import settings


class ToolError(Exception):
    pass


def _structured(result) -> dict:
    if result.is_error:
        text = " ".join(getattr(block, "text", "") for block in result.content)
        raise ToolError(text or "tool call failed")
    if isinstance(result.structured_content, dict):
        data = result.structured_content
        return data.get("result", data) if set(data) == {"result"} else data
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    return {}


async def call_tool(name: str, arguments: dict, url: str | None = None, timeout: float = 10) -> dict:
    async with Client(url or settings.TOOLS_URL, read_timeout_seconds=timeout) as client:
        return _structured(await client.call_tool(name, arguments))


async def describe(url: str | None = None) -> dict:
    """Negotiated protocol version and the live tool schemas, for the manifest."""
    async with Client(url or settings.TOOLS_URL) as client:
        tools = await client.list_tools()
        server = client.server_info
        return {
            "protocol_version": client.protocol_version,
            "server": {"name": server.name, "version": server.version} if server else None,
            "tools": {t.name: {"description": t.description, "input_schema": t.input_schema} for t in tools.tools},
        }
