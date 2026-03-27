"""Core domain models for RepoGraph — pure dataclasses, no I/O.

Includes graph node shapes, parse-time structures such as ``CallSite`` (raw callee
expression text plus caller context), and edge records used by the pipeline and store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Canonical ID helpers
# ---------------------------------------------------------------------------

@dataclass
class NodeID:
    """Canonical ID format: {label}:{relative_path}:{qualified_name}"""
    label: str
    path: str
    symbol: str = ""

    def to_str(self) -> str:
        parts = [self.label, self.path]
        if self.symbol:
            parts.append(self.symbol)
        return ":".join(parts)

    @staticmethod
    def make_file_id(path: str) -> str:
        return f"file:{path}"

    @staticmethod
    def make_folder_id(path: str) -> str:
        return f"folder:{path}"

    @staticmethod
    def make_function_id(file_path: str, qualified_name: str) -> str:
        return f"function:{file_path}:{qualified_name}"

    @staticmethod
    def make_class_id(file_path: str, qualified_name: str) -> str:
        return f"class:{file_path}:{qualified_name}"

    @staticmethod
    def make_variable_id(file_path: str, function_id: str, name: str) -> str:
        return f"variable:{file_path}:{function_id}:{name}"

    @staticmethod
    def make_import_id(file_path: str, module_path: str, line: int) -> str:
        return f"import:{file_path}:{module_path}:{line}"


# ---------------------------------------------------------------------------
# File-level records
# ---------------------------------------------------------------------------

@dataclass
class FileRecord:
    """Raw metadata about a discovered file (before parsing)."""
    path: str           # relative to repo root
    abs_path: str
    name: str
    extension: str
    language: str
    size_bytes: int
    line_count: int
    source_hash: str    # sha256 of file content
    is_test: bool
    is_config: bool
    mtime: float        # os.path.getmtime
    is_vendored: bool = False   # True when file is inside a vendored OSS library dir


@dataclass
class FileNode:
    """Parsed file entity stored in graph."""
    id: str
    path: str
    abs_path: str
    name: str
    extension: str
    language: str
    size_bytes: int
    line_count: int
    source_hash: str
    is_test: bool
    is_config: bool
    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FolderNode:
    id: str
    path: str
    name: str
    depth: int


# ---------------------------------------------------------------------------
# Symbol nodes
# ---------------------------------------------------------------------------

@dataclass
class FunctionNode:
    id: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: str | None
    is_method: bool
    is_async: bool
    is_exported: bool
    decorators: list[str]
    param_names: list[str]
    return_type: str | None
    source_hash: str
    is_dead: bool = False
    is_entry_point: bool = False
    entry_score: float = 0.0
    community_id: str | None = None
    # Set by Python parser: function is the return value of its enclosing function
    is_closure_returned: bool = False
    # Set by JS parser: module-scope function in a non-ESM file (script-tag context)
    is_script_global: bool = False
    # Synthetic sentinel: represents module-level execution scope (not a real callable)
    is_module_caller: bool = False
    # True when the function lives in a test-classified file (mirrors File.is_test).
    is_test: bool = False
    # Dead code context — set by Phase 11 for functions with is_dead=True:
    #   "dead_everywhere"     — zero callers of any kind (truly unused)
    #   "dead_in_production"  — only callers are in tests/ or scripts/ directories
    #   ""                    — not dead, or context not yet determined
    dead_context: str = ""
    # HTTP route metadata — set by Python parser (F2) when a route decorator is detected.
    # Populated only for Flask/FastAPI-style route handler functions.
    route_path: str = ""
    http_method: str = ""
    # Python: ``from M import sym`` / ``import M`` inside function body (Phase 4).
    inline_imports: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Duplicate symbol detection results (Phase 11b)
# ---------------------------------------------------------------------------

@dataclass
class DuplicateSymbolGroup:
    """A group of functions/classes sharing the same name across multiple files."""
    id: str
    name: str
    kind: str                  # "function" | "class"
    occurrence_count: int
    file_paths: list[str]
    severity: str              # "high" | "medium" | "low"
    reason: str                # e.g. "same_qualified_name_identical_body",
                               # "same_qualified_name_different_body",
                               # "same_name_and_signature_multi_file", …
    is_superseded: bool        # True when dead copies exist alongside live ones
    canonical_path: str = ""   # Best guess at the authoritative copy's file path
    superseded_paths: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.superseded_paths is None:
            self.superseded_paths = []

    def as_dict(self) -> dict:
        """Serialize for plugin hooks and JSON (matches graph store reader shape)."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "occurrence_count": self.occurrence_count,
            "file_paths": list(self.file_paths),
            "severity": self.severity,
            "reason": self.reason,
            "is_superseded": self.is_superseded,
            "canonical_path": self.canonical_path or "",
            "superseded_paths": list(self.superseded_paths or []),
        }


# ---------------------------------------------------------------------------
# Doc-vs-code warning (Phase 14)
# ---------------------------------------------------------------------------

@dataclass
class DocSymbolWarning:
    """A backtick-quoted symbol in a doc that no longer maps to a live symbol."""
    id: str
    doc_path: str
    line_number: int
    symbol_text: str
    warning_type: str          # "stale_reference" | "moved_reference" | "unknown_reference"
    severity: str              # "high" | "medium" | "low"
    context_snippet: str


@dataclass
class ClassNode:
    id: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    docstring: str | None
    base_names: list[str]      # raw base class name strings from source
    is_exported: bool
    source_hash: str
    community_id: str | None = None


@dataclass
class VariableNode:
    id: str
    name: str
    function_id: str    # scope: which function this lives in
    file_path: str
    line_number: int
    inferred_type: str | None
    is_parameter: bool
    is_return: bool
    value_repr: str | None   # compact repr of assigned value if literal


@dataclass
class ImportNode:
    id: str
    file_path: str
    raw_statement: str
    module_path: str            # as written in source
    resolved_path: str | None  # resolved file path in repo
    imported_names: list[str]
    is_wildcard: bool
    line_number: int
    # Alias map: local_alias -> original_name
    # Populated for "from M import X as Y" and "import M as N".
    # e.g. "from repograph.plugins.static_analyzers.pathways.scorer import score_function as _score_fn"
    #      → aliases={"_score_fn": "score_function"}
    aliases: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Raw extraction types (pre-resolution)
# ---------------------------------------------------------------------------

@dataclass
class CallSite:
    """Unresolved call site extracted during parse phase."""
    caller_function_id: str
    callee_text: str            # raw callee expression text: "foo", "obj.foo", "module.foo"
    call_site_line: int
    argument_exprs: list[str]   # raw argument expressions as strings
    keyword_args: dict[str, str]  # kwarg_name -> expr_str
    file_path: str


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

@dataclass
class ImportEdge:
    from_file_id: str
    to_file_id: str
    specific_symbols: list[str]
    is_wildcard: bool
    line_number: int
    confidence: float


@dataclass
class CallEdge:
    from_function_id: str
    to_function_id: str
    call_site_line: int
    argument_names: list[str]   # argument names (not values) passed
    confidence: float
    reason: str  # "direct_call" | "method_call" | "dynamic" | "decorator"


@dataclass
class FlowsIntoEdge:
    from_variable_id: str
    to_variable_id: str
    via_argument: str           # parameter name in callee
    call_site_line: int
    confidence: float


@dataclass
class ExtendsEdge:
    from_class_id: str
    to_class_id: str
    confidence: float


@dataclass
class ImplementsEdge:
    from_class_id: str
    to_class_id: str
    confidence: float


@dataclass
class CoupledWithEdge:
    from_file_id: str
    to_file_id: str
    change_count: int
    strength: float


# ---------------------------------------------------------------------------
# Pathway types (first-class entities)
# ---------------------------------------------------------------------------

@dataclass
class PathwayStep:
    order: int
    function_id: str
    function_name: str
    file_path: str
    line_start: int
    role: str   # "entry" | "handler" | "service" | "adapter" | "terminal" | "cross_lang_http"
    calls_next: list[str]   # function_ids
    confidence: float = 1.0
    decorators: list[str] = field(default_factory=list)
    # Cross-language HTTP traversal metadata (set when step is reached via MAKES_HTTP_CALL)
    cross_lang_step: bool = False
    http_method: str = ""


@dataclass
class VariableThread:
    name: str          # e.g., "user_id", "request", "payload"
    steps: list[tuple[int, str, str]]  # (step_order, function_id, variable_id)


@dataclass
class PathwayDoc:
    id: str
    name: str
    display_name: str
    description: str
    entry_file: str
    entry_function: str
    terminal_type: str
    steps: list[PathwayStep]
    variable_threads: list[VariableThread]
    participating_files: list[str]
    confidence: float
    source: str   # "auto_detected" | "curated" | "hybrid"
    context_doc: str    # preformatted text ready for AI injection
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # importance_score measures relevance (step depth × file spread × entry weight).
    # Intentionally separate from confidence (which measures analysis reliability).
    importance_score: float = 0.0


# ---------------------------------------------------------------------------
# Community + Process
# ---------------------------------------------------------------------------

@dataclass
class CommunityNode:
    id: str
    label: str
    cohesion: float
    member_count: int


@dataclass
class ProcessNode:
    id: str
    entry_id: str       # function_id of entry point
    step_count: int
    confidence: float


# ---------------------------------------------------------------------------
# Artifact staleness
# ---------------------------------------------------------------------------

@dataclass
class ArtifactMeta:
    """Staleness tracking for every generated artifact."""
    artifact_id: str
    artifact_type: str   # "pathway_doc" | "mirror_json" | "mirror_md" | "context_doc"
    source_hashes: dict[str, str]  # {file_path: hash} — inputs this was derived from
    generated_at: datetime
    is_stale: bool = False
    stale_reason: str | None = None


@dataclass
class StaleResult:
    is_stale: bool
    stale_reason: str | None = None


# ---------------------------------------------------------------------------
# Parsed file result (aggregate output of one parser run)
# ---------------------------------------------------------------------------

@dataclass
class ParsedFile:
    """Everything extracted from a single source file."""
    file_record: FileRecord
    functions: list[FunctionNode] = field(default_factory=list)
    classes: list[ClassNode] = field(default_factory=list)
    imports: list[ImportNode] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    variables: list[VariableNode] = field(default_factory=list)
    framework_hints: list[str] = field(default_factory=list)
    plugin_artifacts: dict[str, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Diff / incremental
# ---------------------------------------------------------------------------

@dataclass
class DiffResult:
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    changed: set[str] = field(default_factory=set)


@dataclass
class AffectedSet:
    reparse: set[str] = field(default_factory=set)
    recheck_calls: set[str] = field(default_factory=set)
    remove: set[str] = field(default_factory=set)
    all_affected: set[str] = field(default_factory=set)
