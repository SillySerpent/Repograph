"""Tests for index exclude config and pathway curator paths."""
from __future__ import annotations

import textwrap

import yaml

from repograph.config import (
    INDEX_CONFIG_FILENAME,
    load_extra_exclude_dirs,
    repograph_dir,
)
from repograph.plugins.static_analyzers.pathways.curator import PathwayCurator


def test_load_extra_exclude_dirs_empty_when_no_config(tmp_path) -> None:
    assert load_extra_exclude_dirs(str(tmp_path)) == set()


def test_default_excludes_vendored_repograph(tmp_path) -> None:
    (tmp_path / "repograph").mkdir()
    (tmp_path / "repograph" / "pyproject.toml").write_text(
        '[project]\nname = "repograph"\n', encoding="utf-8"
    )
    assert load_extra_exclude_dirs(str(tmp_path)) == {"repograph"}


def test_default_excludes_disabled_via_yaml(tmp_path) -> None:
    (tmp_path / "repograph").mkdir()
    (tmp_path / "repograph" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    rg = tmp_path / ".repograph"
    rg.mkdir()
    cfg = rg / INDEX_CONFIG_FILENAME
    cfg.write_text(
        yaml.safe_dump({"disable_auto_excludes": True}),
        encoding="utf-8",
    )
    assert load_extra_exclude_dirs(str(tmp_path)) == set()


def test_merges_dot_repograph_and_root_yaml(tmp_path) -> None:
    rg = tmp_path / ".repograph"
    rg.mkdir()
    (rg / INDEX_CONFIG_FILENAME).write_text(
        yaml.safe_dump({"exclude_dirs": ["a"]}),
        encoding="utf-8",
    )
    (tmp_path / INDEX_CONFIG_FILENAME).write_text(
        yaml.safe_dump({"exclude_dirs": ["b"]}),
        encoding="utf-8",
    )
    assert load_extra_exclude_dirs(str(tmp_path)) == {"a", "b"}


def test_pathway_curator_prefers_dot_repograph(tmp_path) -> None:
    rg = tmp_path / ".repograph"
    rg.mkdir()
    (rg / "pathways.yml").write_text(
        textwrap.dedent(
            """
            pathways:
              - name: only_here
                entry:
                  file: "x.py"
                  function: "f"
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "pathways.yml").write_text(
        textwrap.dedent(
            """
            pathways:
              - name: legacy
                entry:
                  file: "y.py"
                  function: "g"
            """
        ),
        encoding="utf-8",
    )
    c = PathwayCurator(str(tmp_path))
    assert c.get("only_here") is not None
    assert c.get("legacy") is None
