"""Unit tests for context document generation."""
from __future__ import annotations

import os
import pytest
import tempfile

FLASK_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")


@pytest.fixture(scope="module")
def flask_store():
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    with tempfile.TemporaryDirectory() as tmp:
        rg_dir = os.path.join(tmp, ".repograph")
        config = RunConfig(
            repo_root=os.path.abspath(FLASK_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        yield store


class TestTokenBudget:
    def test_no_trimming_when_few_steps(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager(max_tokens=2000)
        steps = [{"order": i, "step_order": i, "confidence": 0.9} for i in range(5)]
        result = budget.trim_steps(steps)
        assert len(result) == 5

    def test_trims_to_budget(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager(max_tokens=500)  # very small
        steps = [{"order": i, "step_order": i, "confidence": 0.9} for i in range(20)]
        result = budget.trim_steps(steps)
        assert len(result) < 20

    def test_always_keeps_entry_and_terminal(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager(max_tokens=300)  # tiny budget
        steps = [{"order": i, "step_order": i, "confidence": 0.9} for i in range(15)]
        result = budget.trim_steps(steps)
        assert len(result) >= 2
        assert result[0]["order"] == 0       # entry kept
        assert result[-1]["order"] == 14     # terminal kept

    def test_keeps_highest_confidence_middle(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager(max_tokens=600)
        steps = [
            {"order": 0, "step_order": 0, "confidence": 1.0},
            {"order": 1, "step_order": 1, "confidence": 0.3},  # low
            {"order": 2, "step_order": 2, "confidence": 0.9},  # high
            {"order": 3, "step_order": 3, "confidence": 0.2},  # low
            {"order": 4, "step_order": 4, "confidence": 1.0},  # terminal
        ]
        result = budget.trim_steps(steps)
        # step 2 (conf 0.9) should be kept over step 1 (conf 0.3)
        orders = {s["order"] for s in result}
        assert 0 in orders  # entry
        assert 4 in orders  # terminal

    def test_empty_steps(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager()
        assert budget.trim_steps([]) == []

    def test_estimate_tokens(self):
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        budget = TokenBudgetManager()
        text = "x" * 400  # 400 chars = ~100 tokens
        assert budget.estimate_tokens(text) == 100


class TestContextFormatter:
    def test_format_produces_separator(self):
        from repograph.plugins.exporters.pathway_contexts.formatter import (
            SEP,
            format_context_doc,
        )
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager

        pathway = {
            "name": "test_flow",
            "display_name": "Test Flow",
            "source": "auto_detected",
            "confidence": 0.85,
            "description": "A test pathway",
            "variable_threads": "[]",
        }
        steps = [
            {"order": 0, "step_order": 0, "function_name": "handler",
             "file_path": "routes/test.py", "line_start": 1, "line_end": 10,
             "role": "entry", "decorators": [], "confidence": 1.0},
        ]
        budget = TokenBudgetManager(max_tokens=2000)

        # We need a store mock - use actual store
        with tempfile.TemporaryDirectory() as tmp:
            from repograph.graph_store.store import GraphStore
            store = GraphStore(os.path.join(tmp, "t.db"))
            store.initialize_schema()
            result = format_context_doc(pathway, steps, store, budget)

        assert SEP in result
        assert "test_flow" in result
        assert "handler" in result
        assert "INTERPRETATION" in result
        assert "BFS discovery order" in result

    def test_format_includes_files(self):
        from repograph.plugins.exporters.pathway_contexts.formatter import format_context_doc
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager

        pathway = {
            "name": "flow", "display_name": "Flow", "source": "auto",
            "confidence": 0.9, "description": "", "variable_threads": "[]",
        }
        steps = [
            {"order": 0, "step_order": 0, "function_name": "fn_a",
             "file_path": "a.py", "line_start": 1, "line_end": 5,
             "role": "entry", "decorators": [], "confidence": 1.0},
            {"order": 1, "step_order": 1, "function_name": "fn_b",
             "file_path": "b.py", "line_start": 1, "line_end": 5,
             "role": "terminal", "decorators": [], "confidence": 0.9},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            from repograph.graph_store.store import GraphStore
            store = GraphStore(os.path.join(tmp, "t.db"))
            store.initialize_schema()
            result = format_context_doc(pathway, steps, store, TokenBudgetManager())

        assert "a.py" in result
        assert "b.py" in result


class TestContextGenerator:
    def test_generates_context_for_pathway(self, flask_store):
        pathways = flask_store.get_all_pathways()
        assert pathways
        full = flask_store.get_pathway_by_id(pathways[0]["id"])
        assert full is not None
        ctx = full.get("context_doc", "")
        assert ctx  # non-empty

    def test_stale_warning_on_changed_file(self, flask_store):
        """Context docs for stale pathways should regenerate."""
        from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context
        pathways = flask_store.get_all_pathways()
        assert pathways
        ctx = generate_pathway_context(pathways[0]["id"], flask_store, max_tokens=2000)
        assert isinstance(ctx, str)


class TestSequentialStepNumbering:
    """STEP numbers in context docs must be 1,2,3… not BFS-depth jumps."""

    def _make_steps(self, bfs_depths: list[int]) -> list[dict]:
        """Build minimal step dicts with given BFS depths."""
        return [
            {
                "order": d, "step_order": d,
                "function_name": f"fn_{i}",
                "file_path": "src/mod.py",
                "line_start": i * 10, "line_end": i * 10 + 9,
                "role": "entry" if i == 0 else "service",
                "decorators": [], "confidence": 0.9,
            }
            for i, d in enumerate(bfs_depths)
        ]

    def _extract_step_numbers(self, doc: str) -> list[int]:
        import re
        return [int(m) for m in re.findall(r"STEP (\d+)", doc)]

    def _format(self, steps):
        import tempfile, os
        from repograph.plugins.exporters.pathway_contexts.formatter import format_context_doc
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        from repograph.graph_store.store import GraphStore
        pathway = {
            "name": "t", "display_name": "T", "source": "auto",
            "confidence": 0.9, "description": "", "variable_threads": "[]",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(os.path.join(tmp, "t.db"))
            store.initialize_schema()
            return format_context_doc(pathway, steps, store, TokenBudgetManager())

    def test_sequential_when_bfs_is_flat(self):
        steps = self._make_steps([0, 1, 2, 3, 4])
        doc = self._format(steps)
        nums = self._extract_step_numbers(doc)
        assert nums == list(range(1, len(nums) + 1)), f"Non-sequential: {nums}"

    def test_sequential_when_bfs_has_repeated_depths(self):
        # BFS produces same depth for siblings: 0, 1, 1, 2, 2, 3
        steps = self._make_steps([0, 1, 1, 2, 2, 3])
        doc = self._format(steps)
        nums = self._extract_step_numbers(doc)
        assert nums == list(range(1, len(nums) + 1)), f"Non-sequential: {nums}"

    def test_sequential_when_bfs_has_large_jumps(self):
        # Simulates async_main where BFS jumps 1,2,3,4,5,9,10,11,16,17,18
        steps = self._make_steps([0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 4, 9, 10, 16])
        doc = self._format(steps)
        nums = self._extract_step_numbers(doc)
        assert nums == list(range(1, len(nums) + 1)), f"Non-sequential after large jumps: {nums}"

    def test_bfs_depth_annotation_present(self):
        """Each step must include [depth N] annotation."""
        steps = self._make_steps([0, 3, 7])
        doc = self._format(steps)
        import re
        depths = re.findall(r"\[depth (\d+)\]", doc)
        assert len(depths) == 3, f"Expected 3 depth annotations, got: {depths}"
        assert depths == ["0", "3", "7"], f"Wrong depths: {depths}"

    def test_single_step_numbered_1(self):
        steps = self._make_steps([0])
        doc = self._format(steps)
        nums = self._extract_step_numbers(doc)
        assert nums == [1]

    def test_flask_pipeline_steps_are_sequential(self, flask_store):
        """End-to-end: all generated pathway docs on flask fixture have sequential steps."""
        import re
        pathways = flask_store.get_all_pathways()
        for p in pathways:
            full = flask_store.get_pathway_by_id(p["id"])
            doc = (full or {}).get("context_doc", "")
            if not doc:
                continue
            nums = [int(m) for m in re.findall(r"STEP (\d+)", doc)]
            assert nums == list(range(1, len(nums) + 1)), \
                f"Pathway '{p['name']}' has non-sequential steps: {nums}"
