from typing import Annotated

from mcp import types
from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("weather")

PREFIX = "Adds two numbers. "
NOTE = PREFIX + "Always returns an int."


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
    """
    return ""


@mcp.tool(name="add_numbers", description=NOTE)
def add(a: Annotated[int, Field(description="first number")], b: int) -> int:
    return a + b


@mcp.tool
def bare(x: str) -> str:
    """Bare decorator form."""
    return x


@mcp.tool(description=f"Dynamic {PREFIX} with {unknown_var}")
def dynamic() -> None:
    pass


@server.call_tool()
async def call_tool(name, arguments):
    """Not a tool definition."""


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch",
            description="\n".join(["Fetches a URL", "from the internet."]),
            inputSchema={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to fetch"}},
            },
        )
    ]
