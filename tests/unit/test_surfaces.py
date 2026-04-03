"""Tests for the surfaces package (repograph.surfaces).

Covers:
- All three surfaces are importable from their canonical locations
- repograph.surfaces.api.RepoGraph is the same class used in service delegation
- repograph.surfaces.mcp.server.create_server is importable
- repograph.surfaces.mcp.nl_query.NLQueryEngine is importable
- repograph.surfaces.cli app is importable with all expected commands
- Config methods (get_config, set_config, list_config, reset_config) on RepoGraph
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import smoke tests — all surfaces canonical locations
# ---------------------------------------------------------------------------

class TestSurfacesImports:
    def test_surfaces_package_importable(self):
        import repograph.surfaces  # noqa: F401

    def test_api_importable(self):
        from repograph.surfaces.api import RepoGraph
        assert RepoGraph is not None

    def test_mcp_server_importable(self):
        from repograph.surfaces.mcp.server import create_server
        assert callable(create_server)

    def test_mcp_nl_query_importable(self):
        from repograph.surfaces.mcp.nl_query import NLQueryEngine
        assert NLQueryEngine is not None

    def test_cli_app_importable(self):
        from repograph.surfaces.cli import app
        assert app is not None

    def test_cli_commands_importable(self):
        from repograph.surfaces.cli.commands import (
            sync, query, report, analysis, trace, config, export, mcp_cmd, admin,
        )

    def test_cli_output_importable(self):
        from repograph.surfaces.cli.output import _print_stats
        assert callable(_print_stats)


# ---------------------------------------------------------------------------
# RepoGraph class structure
# ---------------------------------------------------------------------------

class TestRepoGraphClass:
    def test_repr_contains_repo(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        assert str(tmp_path) in repr(rg)

    def test_getattr_delegates_to_service(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        # Service attributes should be accessible via delegation
        assert hasattr(rg, "repo_path")

    def test_context_manager_protocol(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        with RepoGraph(str(tmp_path)) as rg:
            assert rg is not None

    def test_has_config_methods(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        assert callable(rg.get_config)
        assert callable(rg.set_config)
        assert callable(rg.describe_config)
        assert callable(rg.unset_config)
        assert callable(rg.list_config)
        assert callable(rg.reset_config)


# ---------------------------------------------------------------------------
# RepoGraph config methods (settings integration)
# ---------------------------------------------------------------------------

class TestRepoGraphConfigMethods:
    def setup_method(self):
        """Each test gets a fresh tmp directory."""

    def test_list_config_returns_dict(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        cfg = rg.list_config()
        assert isinstance(cfg, dict)
        assert "include_git" in cfg
        assert "auto_dynamic_analysis" in cfg

    def test_get_config_returns_default(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        assert rg.get_config("include_git") is True

    def test_set_config_persists(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        import json
        (tmp_path / ".repograph").mkdir()
        rg = RepoGraph(str(tmp_path))
        rg.set_config("include_git", False)
        # Re-open and check it persisted
        rg2 = RepoGraph(str(tmp_path))
        assert rg2.get_config("include_git") is False

    def test_set_config_unknown_key_raises(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        (tmp_path / ".repograph").mkdir()
        rg = RepoGraph(str(tmp_path))
        with pytest.raises(KeyError):
            rg.set_config("no_such_setting", "value")

    def test_reset_config_restores_defaults(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        (tmp_path / ".repograph").mkdir()
        rg = RepoGraph(str(tmp_path))
        rg.set_config("include_git", False)
        rg.reset_config()
        assert rg.get_config("include_git") is True

    def test_set_config_exclude_dirs_list(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        (tmp_path / ".repograph").mkdir()
        rg = RepoGraph(str(tmp_path))
        rg.set_config("exclude_dirs", ["vendor", "node_modules"])
        result = rg.get_config("exclude_dirs")
        assert "vendor" in result

    def test_describe_config_returns_metadata(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        rg = RepoGraph(str(tmp_path))
        info = rg.describe_config("include_git")
        assert isinstance(info, dict)
        assert info["key"] == "include_git"
        assert "default" in info
        assert "takes_effect" in info

    def test_unset_config_restores_default(self, tmp_path):
        from repograph.surfaces.api import RepoGraph
        (tmp_path / ".repograph").mkdir()
        rg = RepoGraph(str(tmp_path))
        rg.set_config("include_git", False)
        rg.unset_config("include_git")
        assert rg.get_config("include_git") is True


# ---------------------------------------------------------------------------
# CLI app — command presence checks
# ---------------------------------------------------------------------------

def _cli_command_names() -> list[str]:
    """Return all registered command names, resolving None to callback.__name__."""
    from repograph.surfaces.cli import app
    names = []
    for c in app.registered_commands:
        if c.name is not None:
            names.append(c.name)
        elif c.callback is not None:
            names.append(c.callback.__name__)
    return names


class TestCliCommands:
    def test_sync_command_registered(self):
        assert "sync" in _cli_command_names()

    def test_init_command_registered(self):
        assert "init" in _cli_command_names()

    def test_report_command_registered(self):
        assert "report" in _cli_command_names()

    def test_config_subgroup_registered(self):
        """config subgroup (for settings) must exist alongside config-registry."""
        from repograph.surfaces.cli import app
        group_names = [g.name for g in app.registered_groups]
        assert "config" in group_names

    def test_config_registry_command_registered(self):
        """Old 'config' command must be renamed to 'config-registry'."""
        names = _cli_command_names()
        assert "config-registry" in names
        # config as a direct command must NOT exist — it's now a subgroup
        assert "config" not in names


# ---------------------------------------------------------------------------
# MCP server — tool registration smoke test
# ---------------------------------------------------------------------------

class TestMcpServer:
    @pytest.mark.requires_mcp
    def test_create_server_registers_tools(self, tmp_path):
        from repograph.surfaces.mcp.server import create_server
        from repograph.services import RepoGraphService
        service = RepoGraphService(str(tmp_path))
        mcp = create_server(service)
        # FastMCP instance should have tools registered
        assert mcp is not None

    def test_create_server_raises_without_mcp_package(self, tmp_path, monkeypatch):
        """create_server must raise ImportError with a helpful message."""
        import sys
        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
        from repograph.surfaces.mcp.server import create_server
        # mcp import is lazy (inside create_server) — call it to trigger the error
        with pytest.raises(ImportError, match="mcp package"):
            create_server(None)  # type: ignore[arg-type]
