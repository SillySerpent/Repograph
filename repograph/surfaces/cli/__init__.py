"""CLI surface — all commands assembled via Typer."""
from repograph.surfaces.cli.app import app  # noqa: F401

# Import command modules to trigger @app.command() registration
from repograph.surfaces.cli.commands import (  # noqa: F401
    sync, query, report, summary_cmd, modules_cmd, pathway_cmd, analysis, trace, config, export, mcp_cmd, admin,
)
