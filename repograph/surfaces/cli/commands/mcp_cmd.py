"""MCP server command."""
from __future__ import annotations

import typer

from repograph.surfaces.cli.app import app, console, _get_service


# ---------------------------------------------------------------------------
# repograph mcp
# ---------------------------------------------------------------------------

@app.command()
def mcp(
    path: str | None = typer.Argument(None),
    port: int | None = typer.Option(None, "--port", help="HTTP port (default: stdio)"),
):
    """Start the MCP server."""
    from repograph.surfaces.mcp.server import create_server

    root, rg = _get_service(path)
    server = create_server(rg._service, port=port)

    if port is not None:
        console.print(f"[green]Starting MCP server on port {port}[/]")
        server.run(transport="streamable-http")
    else:
        typer.echo("Starting MCP server (stdio transport)", err=True)
        server.run()
