"""User-facing exceptions for the public API and CLI.

:exc:`RepographDBLockedError` — raised when Kuzu cannot open ``graph.db``
because another process holds the writer lock (single-writer model). See
``docs/ACCURACY_CONTRACT.md`` (concurrency).

:exc:`RepographNotFoundError` — raised when :func:`~repograph.settings.get_repo_root`
cannot find a ``.repograph`` directory walking up from the given path.
"""


class RepographNotFoundError(FileNotFoundError):
    """Raised when no ``.repograph`` directory is found walking up the directory tree.

    Run ``repograph init`` first to create the index in the desired root.
    """

    def __init__(self, start: str) -> None:
        self.start = start
        msg = (
            f"No .repograph directory found walking up from: {start}\n"
            "Run 'repograph init' first to initialize the index."
        )
        super().__init__(msg)


class RepographDBLockedError(RuntimeError):
    """Raised when the Kuzu database file is locked by another process.

    RepoGraph uses a single-writer model; only one indexer or writer may
    open ``graph.db`` at a time. Close other tools (menu, MCP, second CLI)
    or wait for them to finish.
    """

    def __init__(self, db_path: str, original: Exception | None = None) -> None:
        self.db_path = db_path
        self.original = original
        msg = (
            f"Could not open database (file may be locked): {db_path}\n"
            "Another process may be using this index — close other RepoGraph "
            "sessions, MCP servers, or wait for sync to finish, then retry."
        )
        super().__init__(msg)
