"""Phase 1 — Walk: discover all source files in the repository."""
from __future__ import annotations

from repograph.settings import load_extra_exclude_dirs
from repograph.core.models import FileRecord
from repograph.utils.fs import walk_repo


def run(repo_root: str) -> list[FileRecord]:
    """
    Walk the repository root and return a list of FileRecord objects
    for every parseable source file, respecting .gitignore and
    ``repograph.index.yaml`` (see ``load_extra_exclude_dirs``) and built-in
    defaults (e.g. vendored ``repograph/``).
    """
    extra = load_extra_exclude_dirs(repo_root)
    return walk_repo(repo_root, extra_exclude_dirs=extra)
