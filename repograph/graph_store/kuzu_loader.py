"""Load the KuzuDB Python binding with a clear install hint.

The optional dependency is declared in ``pyproject.toml``. IDEs should use the
RepoGraph project venv (``repograph/.venv``) so analysis resolves this import.
"""
from __future__ import annotations


def load_kuzu():  # returns module
    try:
        import kuzu  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "RepoGraph requires the 'kuzu' package. From the repograph directory run:\n"
            "  pip install -e '.[community]'\n"
            "or: pip install 'kuzu>=0.7'"
        ) from e
    return kuzu


kuzu = load_kuzu()
