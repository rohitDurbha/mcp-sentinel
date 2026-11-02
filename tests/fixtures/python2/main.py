from mcp.server.fastmcp import FastMCP

mcp = FastMCP("x")


async def find_exceptions(path: str) -> str:
    """Find exceptions in a file."""


def store(x):
    """Store info."""


class S(FastMCP):
    def setup(self):
        self.tool(store, name="qdrant-store", description=self.settings.desc)


mcp.tool()(find_exceptions)
mcp.add_tool(store, name="store2")
