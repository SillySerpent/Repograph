from __future__ import annotations

from pathlib import Path

from repograph.plugins.exporters.modules.plugin import _extract_module_summary


def test_extract_module_summary_reads_init_docstring(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    init_py = pkg / "__init__.py"
    init_py.write_text(
        '"""Package summary. Extra details that should not matter."""\n',
        encoding="utf-8",
    )

    summary = _extract_module_summary(
        "pkg",
        [{"path": "pkg/__init__.py", "abs_path": str(init_py)}],
    )
    assert summary == "Package summary."


def test_extract_module_summary_falls_back_to_module_docstring_in_dominant_file(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mod = pkg / "service.py"
    mod.write_text(
        '"""Service layer for package operations. More detail later."""\n'
        "def helper():\n    return 1\n",
        encoding="utf-8",
    )

    summary = _extract_module_summary(
        "pkg",
        [{"path": "pkg/service.py", "abs_path": str(mod)}],
    )
    assert summary == "Service layer for package operations."


def test_extract_module_summary_falls_back_to_class_docstring(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mod = pkg / "models.py"
    mod.write_text(
        "class Settings:\n"
        '    """Coordinates runtime settings for the package."""\n'
        "    pass\n",
        encoding="utf-8",
    )

    summary = _extract_module_summary(
        "pkg",
        [{"path": "pkg/models.py", "abs_path": str(mod)}],
    )
    assert summary == "Coordinates runtime settings for the package."


def test_extract_module_summary_uses_heuristic_when_no_doc_evidence(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mod = pkg / "service.py"
    mod.write_text("def helper():\n    return 1\n", encoding="utf-8")

    summary = _extract_module_summary(
        "pkg",
        [{"path": "pkg/service.py", "abs_path": str(mod)}],
        total_functions=1,
        class_count=0,
        category="production",
    )

    assert summary == "Production module with 1 file containing 1 function."


def test_extract_module_summary_heuristic_can_include_classes_and_issues(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mod = pkg / "core.py"
    mod.write_text("class Service:\n    pass\n", encoding="utf-8")

    summary = _extract_module_summary(
        "pkg",
        [{"path": "pkg/core.py", "abs_path": str(mod)}],
        key_classes=["Service", "Repository", "Cache"],
        total_functions=7,
        class_count=3,
        dead_count=1,
        duplicate_count=2,
        category="tooling",
    )

    assert summary.startswith("Tooling module with 1 file containing 7 functions and 3 classes.")
    assert "Key classes: Service, Repository..." in summary
    assert "Includes 1 dead-code signal and 2 duplicate signals." in summary


def test_extract_module_summary_for_strayratz_app_module_is_not_blank(strayratz_fixture_dir: str) -> None:
    app_dir = Path(strayratz_fixture_dir) / "app"
    prod_files = [
        {"path": "app/__init__.py", "abs_path": str(app_dir / "__init__.py")},
        {"path": "app/routes.py", "abs_path": str(app_dir / "routes.py")},
        {"path": "app/forms.py", "abs_path": str(app_dir / "forms.py")},
        {"path": "app/models.py", "abs_path": str(app_dir / "models.py")},
    ]

    summary = _extract_module_summary(
        "app",
        prod_files,
        key_classes=["User", "Survey", "NewsletterSubscriber"],
        total_functions=12,
        class_count=8,
        category="production",
    )

    assert summary
    assert "Production module" in summary or "Flask" in summary or "Hydra Fuel" in summary
