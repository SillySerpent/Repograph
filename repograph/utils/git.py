"""GitPython wrappers for repo introspection."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Iterator


def get_repo(repo_root: str):
    """Return a GitPython Repo object or None if not a git repo."""
    try:
        import git
        return git.Repo(repo_root, search_parent_directories=True)
    except Exception:
        return None


def is_git_repo(repo_root: str) -> bool:
    return get_repo(repo_root) is not None


def iter_commits(repo_root: str, days: int = 180) -> Iterator:
    """Yield commits from the past N days."""
    repo = get_repo(repo_root)
    if repo is None:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        for commit in repo.iter_commits():
            try:
                committed_dt = commit.committed_datetime
                if committed_dt.tzinfo is None:
                    committed_dt = committed_dt.replace(tzinfo=timezone.utc)
                if committed_dt < cutoff:
                    break
                yield commit
            except Exception:
                continue
    except Exception:
        return


def get_last_commit_hash(repo_root: str) -> str | None:
    repo = get_repo(repo_root)
    if not repo:
        return None
    try:
        return repo.head.commit.hexsha
    except Exception:
        return None
