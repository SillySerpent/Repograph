"""Shared constants for RepoGraph settings and path layout."""
from __future__ import annotations

REPOGRAPH_DIR = ".repograph"
INDEX_CONFIG_FILENAME = "repograph.index.yaml"
SETTINGS_FILENAME = "settings.json"
DB_FILENAME = "graph.db"
SETTINGS_DOCUMENT_VERSION = 2

DEFAULT_CONTEXT_TOKENS = 2000
DEFAULT_GIT_DAYS = 180
DEFAULT_ENTRY_POINT_LIMIT = 20
DEFAULT_MIN_COMMUNITY_SIZE = 3
DEFAULT_MODULE_EXPANSION_THRESHOLD = 15
ERROR_TRUNCATION_CHARS = 4000
AGENT_GUIDE_MAX_FILE_READ_BYTES = 3000
PREFETCH_CHUNK_SIZE = 48

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sh": "shell",
    ".bash": "shell",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".md": "markdown",
    ".markdown": "markdown",
}
