"""Tests for repograph.config — get_repo_root and _read_index_yaml (Block B6/A4)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from repograph.config import get_repo_root
from repograph.exceptions import RepographNotFoundError


# ---------------------------------------------------------------------------
# get_repo_root
# ---------------------------------------------------------------------------


def test_get_repo_root_found_in_cwd(tmp_path: Path):
    """Found in the given directory directly."""
    rg_dir = tmp_path / ".repograph"
    rg_dir.mkdir()
    result = get_repo_root(str(tmp_path))
    assert result == str(tmp_path)


def test_get_repo_root_found_in_parent(tmp_path: Path):
    """Walks up and finds .repograph in a parent directory."""
    rg_dir = tmp_path / ".repograph"
    rg_dir.mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    result = get_repo_root(str(nested))
    assert result == str(tmp_path)


def test_get_repo_root_not_found_raises(tmp_path: Path):
    """Raises RepographNotFoundError when no .repograph dir anywhere."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    with pytest.raises(RepographNotFoundError) as exc_info:
        get_repo_root(str(empty))
    assert str(empty) in str(exc_info.value)


def test_get_repo_root_default_cwd(monkeypatch, tmp_path: Path):
    """No path argument uses os.getcwd()."""
    rg_dir = tmp_path / ".repograph"
    rg_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    result = get_repo_root()
    assert result == str(tmp_path)


def test_get_repo_root_symlink_resolution(tmp_path: Path):
    """Symlink to directory containing .repograph is resolved correctly."""
    real = tmp_path / "real"
    real.mkdir()
    (real / ".repograph").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    result = get_repo_root(str(link))
    assert Path(result).resolve() == real.resolve()


# ---------------------------------------------------------------------------
# _read_index_yaml
# ---------------------------------------------------------------------------


def test_read_index_yaml_valid(tmp_path: Path):
    from repograph.config import _read_index_yaml

    yaml_file = tmp_path / "repograph.index.yaml"
    yaml_file.write_text("exclude_dirs:\n  - vendor\n  - node_modules\n", encoding="utf-8")
    result = _read_index_yaml(str(yaml_file))
    assert result == {"exclude_dirs": ["vendor", "node_modules"]}


def test_read_index_yaml_malformed(tmp_path: Path, caplog):
    """Invalid YAML logs a warning and returns None."""
    import logging
    from repograph.config import _read_index_yaml

    yaml_file = tmp_path / "repograph.index.yaml"
    yaml_file.write_text("invalid: yaml: [unclosed", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="repograph.config"):
        result = _read_index_yaml(str(yaml_file))
    assert result is None
    assert any("index YAML" in r.message or "config" in r.message.lower() for r in caplog.records)


def test_read_index_yaml_missing_file(tmp_path: Path):
    """Non-existent file returns None without error."""
    from repograph.config import _read_index_yaml

    result = _read_index_yaml(str(tmp_path / "nonexistent.yaml"))
    assert result is None


def test_read_index_yaml_empty_file(tmp_path: Path):
    """Empty file returns empty dict (yaml.safe_load returns None → coerced to {})."""
    from repograph.config import _read_index_yaml

    yaml_file = tmp_path / "repograph.index.yaml"
    yaml_file.write_text("", encoding="utf-8")
    result = _read_index_yaml(str(yaml_file))
    assert result == {}
