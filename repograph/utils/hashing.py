"""File and artifact hashing for staleness tracking."""
from __future__ import annotations

import hashlib
import os


def hash_file_content(content: bytes) -> str:
    """Return SHA-256 hex digest of file content bytes."""
    return hashlib.sha256(content).hexdigest()


def hash_file(abs_path: str) -> str:
    """Hash a file on disk. Returns empty string if file cannot be read."""
    try:
        with open(abs_path, "rb") as f:
            content = f.read()
        return hash_file_content(content)
    except (OSError, PermissionError):
        return ""


def hash_string(text: str) -> str:
    """SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_source_slice(source: str, line_start: int, line_end: int) -> str:
    """Hash only the lines [line_start, line_end] (1-indexed, inclusive)."""
    lines = source.splitlines()
    # Convert to 0-indexed
    start = max(0, line_start - 1)
    end = min(len(lines), line_end)
    slice_text = "\n".join(lines[start:end])
    return hash_string(slice_text)


def hash_dict_values(d: dict[str, str]) -> str:
    """Hash a dict of {key: hash_value} pairs in deterministic order."""
    combined = "|".join(f"{k}={v}" for k, v in sorted(d.items()))
    return hash_string(combined)
