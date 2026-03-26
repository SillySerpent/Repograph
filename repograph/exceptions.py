"""User-facing exceptions for the public API and CLI.

Currently :exc:`RepographDBLockedError` — raised when Kuzu cannot open ``graph.db``
because another process holds the writer lock (single-writer model). See
``docs/ACCURACY_CONTRACT.md`` (concurrency).
"""


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
