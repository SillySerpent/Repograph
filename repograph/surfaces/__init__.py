"""Public surfaces for RepoGraph: CLI, Python API, and MCP server.

Import from these modules for stable interfaces:

    from repograph.surfaces.api import RepoGraph          # Python API
    from repograph.surfaces.cli import app                # Typer CLI app
    from repograph.surfaces.mcp.server import create_server  # MCP server
"""
from repograph.surfaces.api import RepoGraph  # noqa: F401
