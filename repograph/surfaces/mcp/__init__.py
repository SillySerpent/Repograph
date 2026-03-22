"""MCP server surface for RepoGraph.

Exposes a curated set of read-only FastMCP tools over the service layer.
Start the server from the CLI with ``repograph mcp`` or programmatically::

    from repograph.surfaces.mcp.server import create_server
    from repograph.services import RepoGraphService

    service = RepoGraphService("/path/to/repo")
    mcp = create_server(service)
    mcp.run()
"""
