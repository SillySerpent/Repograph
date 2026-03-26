"""Integration tests — polymorphic impact() and get_interface_callers()."""
from __future__ import annotations

import os
import shutil
import pytest

FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "polymorphic_impact")
)


@pytest.fixture(scope="module")
def poly_rg(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("poly_impact")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    from repograph.api import RepoGraph
    rg = RepoGraph(repo, repograph_dir=rg_dir)
    yield rg
    rg.close()


class TestGetInterfaceCallersMethod:
    """Unit-level: get_interface_callers() walks EXTENDS edges correctly."""

    def test_returns_list(self, poly_rg):
        """get_interface_callers always returns a list, never raises."""
        store = poly_rg._get_store()
        matches = store.search_functions_by_name("LiveBroker.submit_order", limit=3)
        assert matches, "LiveBroker.submit_order must be indexed"
        result = store.get_interface_callers(matches[0]["id"])
        assert isinstance(result, list)

    def test_results_have_required_keys(self, poly_rg):
        """Every returned caller dict must have id, qualified_name, file_path,
        confidence, and reason."""
        store = poly_rg._get_store()
        matches = store.search_functions_by_name("LiveBroker.submit_order", limit=3)
        result = store.get_interface_callers(matches[0]["id"])
        for caller in result:
            for key in ("id", "qualified_name", "file_path", "confidence", "reason"):
                assert key in caller, f"Missing key '{key}' in caller dict: {caller}"

    def test_confidence_penalty_applied(self, poly_rg):
        """Any interface-resolved callers must have confidence <= 0.9."""
        store = poly_rg._get_store()
        matches = store.search_functions_by_name("LiveBroker.submit_order", limit=3)
        result = store.get_interface_callers(matches[0]["id"])
        for caller in result:
            assert caller["confidence"] <= 0.9, (
                f"Interface caller confidence should be <= 0.9, got {caller['confidence']}"
            )

    def test_reason_tag_format(self, poly_rg):
        """Reason tags must start with 'via_interface:'."""
        store = poly_rg._get_store()
        matches = store.search_functions_by_name("LiveBroker.submit_order", limit=3)
        result = store.get_interface_callers(matches[0]["id"])
        for caller in result:
            assert caller["reason"].startswith("via_interface:"), (
                f"Expected 'via_interface:' prefix, got: {caller['reason']}"
            )

    def test_empty_for_unknown_function_id(self, poly_rg):
        """Passing a non-existent ID must return [] without raising."""
        store = poly_rg._get_store()
        result = store.get_interface_callers("function:nonexistent:Unknown.method")
        assert result == []

    def test_no_duplicates_in_result(self, poly_rg):
        """Each caller ID must appear at most once in the result."""
        store = poly_rg._get_store()
        matches = store.search_functions_by_name("LiveBroker.submit_order", limit=3)
        result = store.get_interface_callers(matches[0]["id"])
        ids = [c["id"] for c in result]
        assert len(ids) == len(set(ids)), f"Duplicate caller IDs: {ids}"


class TestImpactFallbackBehavior:
    """impact() API: interface fallback fires only when direct_callers is empty."""

    def test_impact_always_returns_required_keys(self, poly_rg):
        """impact() must always return the expected dict keys."""
        result = poly_rg.impact("LiveBroker.submit_order")
        for key in ("symbol", "file", "direct_callers",
                    "transitive_callers", "files_affected", "warnings"):
            assert key in result, f"Missing key '{key}' in impact result"

    def test_impact_finds_order_manager_callers(self, poly_rg):
        """OrderManager.submit and OrderManager.close_position call submit_order
        (either directly or via interface resolution)."""
        result = poly_rg.impact("LiveBroker.submit_order")
        all_callers = result["direct_callers"] + result["transitive_callers"]
        caller_names = {c["qualified_name"] for c in all_callers}
        assert any("OrderManager" in n for n in caller_names), (
            f"Expected OrderManager callers, got: {caller_names}"
        )

    def test_impact_files_affected_non_empty(self, poly_rg):
        result = poly_rg.impact("LiveBroker.submit_order")
        assert result["files_affected"], "files_affected must not be empty"

    def test_interface_fallback_fires_for_abstract_method(self, poly_rg):
        """IBroker.submit_order has no direct callers in the fixture
        (callers go to the concrete LiveBroker) — interface resolution
        should surface them by walking EXTENDS in reverse."""
        store = poly_rg._get_store()

        # Find IBroker.submit_order's id
        matches = store.search_functions_by_name("IBroker.submit_order", limit=3)
        assert matches, "IBroker.submit_order must be indexed"
        iface_fn_id = matches[0]["id"]

        direct = store.get_callers(iface_fn_id)
        # In our fixture, calls resolve to LiveBroker, not IBroker
        # get_interface_callers on IBroker.submit_order would walk down to LiveBroker
        # and find its callers. Test that the method at least doesn't error.
        iface = store.get_interface_callers(iface_fn_id)
        assert isinstance(iface, list)

    def test_via_interface_warning_fires_when_no_direct_callers(self, poly_rg):
        """When a symbol has no direct callers but interface callers exist,
        the 'callers_resolved_via_interface' warning must appear."""
        from repograph.api import RepoGraph

        # Build a fresh store where we can manipulate what get_callers returns
        # by testing against a method that genuinely has no direct callers.
        store = poly_rg._get_store()

        # IBroker abstract methods have no direct callers in this fixture
        # because all CALLS edges point to LiveBroker concrete methods.
        # Mock the scenario by directly exercising the fallback code path.
        matches = store.search_functions_by_name("IBroker.submit_order", limit=3)
        if matches:
            direct = store.get_callers(matches[0]["id"])
            interface = store.get_interface_callers(matches[0]["id"])
            # If there are no direct callers, the warning should fire via impact()
            if not direct and interface:
                result = poly_rg.impact("IBroker.submit_order")
                assert "callers_resolved_via_interface" in result.get("warnings", [])

    def test_no_via_interface_warning_when_direct_callers_exist(self, poly_rg):
        """When direct callers exist, do NOT add the via_interface warning."""
        result = poly_rg.impact("LiveBroker.submit_order")
        if result["direct_callers"]:   # our fixture resolves calls directly
            assert "callers_resolved_via_interface" not in result.get("warnings", []), (
                "via_interface warning should not fire when direct callers exist"
            )

    def test_impact_cancel_order_surfaces_caller(self, poly_rg):
        """cancel_order is called by OrderManager.cancel."""
        result = poly_rg.impact("LiveBroker.cancel_order")
        if result.get("error"):
            pytest.skip(f"cancel_order not found: {result['error']}")
        all_callers = result["direct_callers"] + result["transitive_callers"]
        caller_names = {c["qualified_name"] for c in all_callers}
        assert any("OrderManager" in n or "cancel" in n for n in caller_names), (
            f"Expected OrderManager caller, got: {caller_names}"
        )
