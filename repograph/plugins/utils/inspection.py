from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Optional

from repograph.core.models import FileRecord, ParsedFile
from repograph.plugins.parsers import ensure_default_parsers_registered, parse_file as _parse_file


def parse_file(file_record: FileRecord) -> ParsedFile:
    ensure_default_parsers_registered()
    return _parse_file(file_record)

_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def build_file_record(repo_path: Path, rel_path: str, *, text: Optional[str] = None) -> FileRecord | None:
    ext = Path(rel_path).suffix.lower()
    language = _LANGUAGE_BY_EXT.get(ext)
    if language is None:
        return None
    abs_path = (repo_path / rel_path).resolve()
    if text is None:
        try:
            text = abs_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    return FileRecord(
        path=rel_path,
        abs_path=str(abs_path),
        name=Path(rel_path).name,
        extension=ext,
        language=language,
        size_bytes=len(text.encode("utf-8", errors="ignore")),
        line_count=len(text.splitlines()),
        source_hash=sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
        is_test=_is_test_path(rel_path),
        is_config=False,
        mtime=abs_path.stat().st_mtime if abs_path.exists() else 0.0,
    )


def parse_file_with_plugins(repo_path: Path, rel_path: str, *, text: Optional[str] = None) -> ParsedFile | None:
    file_record = build_file_record(repo_path, rel_path, text=text)
    if file_record is None:
        return None
    return parse_file(file_record)


def _is_test_path(rel_path: str) -> bool:
    lower = rel_path.lower()
    parts = set(Path(lower).parts)
    return (
        "tests" in parts
        or lower.endswith("_test.py")
        or lower.endswith(".test.ts")
        or lower.endswith(".spec.ts")
        or lower.endswith(".test.js")
        or lower.endswith(".spec.js")
    )
