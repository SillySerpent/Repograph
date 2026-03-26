"""Standard trace record schema for RepoGraph dynamic analysis.

Every tracer plugin MUST write JSONL files (one JSON object per line) where
each line conforms to one of the record types below.

Format identifier: ``"jsonl_call_trace"``  (declare in TracerPlugin.manifest.trace_format)

Record types
------------

call
    A function was called.

    {
      "kind":    "call",
      "ts":      1234567890.123,        # float, Unix time
      "fn":      "module.ClassName.method",  # dotted qualified name
      "file":    "src/foo.py",          # repo-relative path
      "line":    42,                    # int, call site line number
      "caller":  "module.other_fn",     # dotted qualified name of caller
      "args":    {}                     # optional: serialisable arg snapshot
    }

return
    A function returned (optional — tracers may omit for performance).

    {
      "kind":    "return",
      "ts":      1234567890.456,
      "fn":      "module.ClassName.method",
      "file":    "src/foo.py",
      "line":    42,
      "retval":  null                   # optional: serialisable return value
    }

error
    A function raised an exception.

    {
      "kind":    "error",
      "ts":      1234567890.789,
      "fn":      "module.ClassName.method",
      "file":    "src/foo.py",
      "line":    42,
      "exc":     "ValueError: bad input"
    }

session
    Metadata header written at the start of a trace session (optional).

    {
      "kind":       "session",
      "ts":         1234567890.0,
      "tracer":     "repograph.systrace",
      "version":    "1.0",
      "repo_root":  "/abs/path/to/repo",
      "python":     "3.12.0"
    }

Design rules
~~~~~~~~~~~~
- Files MUST be JSONL (newline-delimited JSON, UTF-8, no BOM).
- Each line MUST be a valid JSON object ending with ``\\n``.
- Unknown fields are ignored by consumers — tracers may add context.
- ``fn`` and ``caller`` use Python dotted-qualified-name convention.
- ``file`` is repo-relative (no leading slash).
- Trace files MUST be written to ``<repograph_dir>/runtime/``.
- File names MUST end with ``.jsonl``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

TRACE_FORMAT = "jsonl_call_trace"
TRACE_FILE_SUFFIX = ".jsonl"
TRACE_SUBDIR = "runtime"


def trace_dir(repograph_dir: str | Path) -> Path:
    """Return the canonical trace directory path."""
    return Path(repograph_dir) / TRACE_SUBDIR


def make_call_record(
    fn: str,
    file: str,
    line: int,
    caller: str = "",
    args: dict | None = None,
) -> dict[str, Any]:
    return {
        "kind": "call",
        "ts": time.time(),
        "fn": fn,
        "file": file,
        "line": line,
        "caller": caller,
        **({"args": args} if args else {}),
    }


def make_session_record(
    repo_root: str,
    tracer: str = "repograph.systrace",
    version: str = "1.0",
) -> dict[str, Any]:
    import sys
    return {
        "kind": "session",
        "ts": time.time(),
        "tracer": tracer,
        "version": version,
        "repo_root": str(repo_root),
        "python": sys.version.split()[0],
    }


def iter_records(trace_file: Path):
    """Yield parsed records from a JSONL trace file, skipping bad lines."""
    try:
        for line in trace_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    except OSError:
        return


def collect_trace_files(repograph_dir: str | Path) -> list[Path]:
    """Return all .jsonl files in the trace directory."""
    d = trace_dir(repograph_dir)
    if not d.exists():
        return []
    return sorted(d.glob(f"*{TRACE_FILE_SUFFIX}"))
