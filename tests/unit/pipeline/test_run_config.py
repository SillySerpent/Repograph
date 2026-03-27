"""Tests for RunConfig.__post_init__ validation (Block A9)."""
from __future__ import annotations

import pytest

from repograph.pipeline.runner import RunConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config(tmp_path, **overrides):
    """Return a valid RunConfig rooted at tmp_path with optional field overrides."""
    defaults = dict(
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_config_no_error(tmp_path):
    """A well-formed RunConfig must not raise."""
    config = _valid_config(tmp_path)
    assert config.repo_root == str(tmp_path)


@pytest.mark.parametrize("value", [-1, -100])
def test_min_community_size_negative_raises(tmp_path, value):
    with pytest.raises(ValueError, match="min_community_size"):
        _valid_config(tmp_path, min_community_size=value)


def test_min_community_size_zero_is_valid(tmp_path):
    # 0 is a valid floor per the plan ("must be >= 0")
    config = _valid_config(tmp_path, min_community_size=0)
    assert config.min_community_size == 0


@pytest.mark.parametrize("value", [0, -1])
def test_module_expansion_threshold_below_one_raises(tmp_path, value):
    with pytest.raises(ValueError, match="module_expansion_threshold"):
        _valid_config(tmp_path, module_expansion_threshold=value)


def test_module_expansion_threshold_one_is_valid(tmp_path):
    config = _valid_config(tmp_path, module_expansion_threshold=1)
    assert config.module_expansion_threshold == 1


@pytest.mark.parametrize("value", [0, 1, 99])
def test_max_context_tokens_below_100_raises(tmp_path, value):
    with pytest.raises(ValueError, match="max_context_tokens"):
        _valid_config(tmp_path, max_context_tokens=value)


def test_max_context_tokens_100_is_valid(tmp_path):
    config = _valid_config(tmp_path, max_context_tokens=100)
    assert config.max_context_tokens == 100


def test_invalid_repo_root_raises(tmp_path):
    nonexistent = str(tmp_path / "does_not_exist")
    with pytest.raises(ValueError, match="repo_root"):
        RunConfig(
            repo_root=nonexistent,
            repograph_dir=str(tmp_path / ".repograph"),
        )


def test_multiple_invalid_fields_reports_all(tmp_path):
    """All validation errors should be reported in one exception."""
    with pytest.raises(ValueError) as exc_info:
        _valid_config(
            tmp_path,
            min_community_size=-1,
            module_expansion_threshold=0,
            max_context_tokens=50,
        )
    msg = str(exc_info.value)
    assert "min_community_size" in msg
    assert "module_expansion_threshold" in msg
    assert "max_context_tokens" in msg
