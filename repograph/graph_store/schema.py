"""KuzuDB schema DDL strings.

All CREATE TABLE statements for RepoGraph's node and edge tables.
"""

SCHEMA_VERSION = "1.7"

# ---------------------------------------------------------------------------
# Node table DDL
# ---------------------------------------------------------------------------

CREATE_FILE = """
CREATE NODE TABLE IF NOT EXISTS File (
    id         STRING,
    path       STRING,
    abs_path   STRING,
    name       STRING,
    extension  STRING,
    language   STRING,
    size_bytes INT64,
    line_count INT64,
    source_hash STRING,
    is_test    BOOLEAN,
    is_config  BOOLEAN,
    indexed_at STRING,
    layer      STRING,
    PRIMARY KEY (id)
)
"""

CREATE_FOLDER = """
CREATE NODE TABLE IF NOT EXISTS Folder (
    id   STRING,
    path STRING,
    name STRING,
    depth INT64,
    PRIMARY KEY (id)
)
"""

CREATE_FUNCTION = """
CREATE NODE TABLE IF NOT EXISTS Function (
    id                  STRING,
    name                STRING,
    qualified_name      STRING,
    file_path           STRING,
    line_start          INT64,
    line_end            INT64,
    signature           STRING,
    docstring           STRING,
    is_method           BOOLEAN,
    is_async            BOOLEAN,
    is_exported         BOOLEAN,
    is_entry_point      BOOLEAN,
    entry_score         DOUBLE,
    is_dead             BOOLEAN,
    dead_code_tier      STRING,
    dead_code_reason    STRING,
    dead_context        STRING,
    community_id        STRING,
    source_hash         STRING,
    decorators          STRING,
    param_names         STRING,
    return_type         STRING,
    is_closure_returned BOOLEAN,
    is_script_global    BOOLEAN,
    is_module_caller    BOOLEAN,
    is_test             BOOLEAN,
    entry_score_base       DOUBLE,
    entry_score_multipliers STRING,
    entry_callee_count     INT64,
    entry_caller_count     INT64,
    runtime_observed          BOOLEAN,
    runtime_observed_calls    INT64,
    runtime_observed_at       STRING,
    runtime_observed_for_hash STRING,
    layer      STRING,
    role       STRING,
    http_method STRING,
    route_path  STRING,
    PRIMARY KEY (id)
)
"""

# Duplicate symbol groups — populated by Phase 11b
CREATE_DUPLICATE_SYMBOL = """
CREATE NODE TABLE IF NOT EXISTS DuplicateSymbol (
    id               STRING,
    name             STRING,
    kind             STRING,
    occurrence_count INT64,
    file_paths       STRING,
    severity         STRING,
    reason           STRING,
    is_superseded    BOOLEAN,
    canonical_path   STRING,
    superseded_paths STRING,
    PRIMARY KEY (id)
)
"""

# Doc-vs-code warnings — populated by Phase 14
CREATE_DOC_WARNING = """
CREATE NODE TABLE IF NOT EXISTS DocWarning (
    id               STRING,
    doc_path         STRING,
    line_number      INT64,
    symbol_text      STRING,
    warning_type     STRING,
    severity         STRING,
    context_snippet  STRING,
    PRIMARY KEY (id)
)
"""

CREATE_CLASS = """
CREATE NODE TABLE IF NOT EXISTS Class (
    id                  STRING,
    name                STRING,
    qualified_name      STRING,
    file_path           STRING,
    line_start          INT64,
    line_end            INT64,
    docstring           STRING,
    base_names          STRING,
    is_exported         BOOLEAN,
    source_hash         STRING,
    community_id        STRING,
    is_type_referenced  BOOLEAN,
    PRIMARY KEY (id)
)
"""

CREATE_VARIABLE = """
CREATE NODE TABLE IF NOT EXISTS Variable (
    id            STRING,
    name          STRING,
    function_id   STRING,
    file_path     STRING,
    line_number   INT64,
    inferred_type STRING,
    is_parameter  BOOLEAN,
    is_return     BOOLEAN,
    value_repr    STRING,
    PRIMARY KEY (id)
)
"""

CREATE_IMPORT = """
CREATE NODE TABLE IF NOT EXISTS Import (
    id               STRING,
    file_path        STRING,
    raw_statement    STRING,
    module_path      STRING,
    resolved_path    STRING,
    imported_names   STRING,
    is_wildcard      BOOLEAN,
    line_number      INT64,
    PRIMARY KEY (id)
)
"""

CREATE_PATHWAY = """
CREATE NODE TABLE IF NOT EXISTS Pathway (
    id               STRING,
    name             STRING,
    display_name     STRING,
    description      STRING,
    entry_file       STRING,
    entry_function   STRING,
    terminal_type    STRING,
    file_count       INT64,
    step_count       INT64,
    source           STRING,
    confidence       DOUBLE,
    importance_score DOUBLE,
    variable_threads STRING,
    context_doc      STRING,
    context_hash     STRING,
    generated_at     STRING,
    PRIMARY KEY (id)
)
"""

CREATE_COMMUNITY = """
CREATE NODE TABLE IF NOT EXISTS Community (
    id           STRING,
    label        STRING,
    cohesion     DOUBLE,
    member_count INT64,
    PRIMARY KEY (id)
)
"""

CREATE_PROCESS = """
CREATE NODE TABLE IF NOT EXISTS Process (
    id         STRING,
    entry_id   STRING,
    step_count INT64,
    confidence DOUBLE,
    PRIMARY KEY (id)
)
"""

# ---------------------------------------------------------------------------
# Relationship table DDL
# ---------------------------------------------------------------------------

CREATE_REL_CONTAINS = """
CREATE REL TABLE IF NOT EXISTS CONTAINS (
    FROM Folder TO File
)
"""

CREATE_REL_IN_FOLDER = """
CREATE REL TABLE IF NOT EXISTS IN_FOLDER (
    FROM File TO Folder
)
"""

CREATE_REL_IMPORTS = """
CREATE REL TABLE IF NOT EXISTS IMPORTS (
    FROM File TO File,
    specific_symbols STRING,
    is_wildcard BOOLEAN,
    line_number INT64,
    confidence DOUBLE
)
"""

CREATE_REL_CALLS = """
CREATE REL TABLE IF NOT EXISTS CALLS (
    FROM Function TO Function,
    call_site_line INT64,
    extra_site_lines STRING,
    argument_names STRING,
    confidence     DOUBLE,
    reason         STRING
)
"""

CREATE_REL_FLOWS_INTO = """
CREATE REL TABLE IF NOT EXISTS FLOWS_INTO (
    FROM Variable TO Variable,
    via_argument   STRING,
    call_site_line INT64,
    confidence     DOUBLE
)
"""

CREATE_REL_DEFINES = """
CREATE REL TABLE IF NOT EXISTS DEFINES (
    FROM File TO Function
)
"""

CREATE_REL_DEFINES_CLASS = """
CREATE REL TABLE IF NOT EXISTS DEFINES_CLASS (
    FROM File TO Class
)
"""

CREATE_REL_HAS_METHOD = """
CREATE REL TABLE IF NOT EXISTS HAS_METHOD (
    FROM Class TO Function
)
"""

CREATE_REL_EXTENDS = """
CREATE REL TABLE IF NOT EXISTS EXTENDS (
    FROM Class TO Class,
    confidence DOUBLE
)
"""

CREATE_REL_IMPLEMENTS = """
CREATE REL TABLE IF NOT EXISTS IMPLEMENTS (
    FROM Class TO Class,
    confidence DOUBLE
)
"""

CREATE_REL_MEMBER_OF = """
CREATE REL TABLE IF NOT EXISTS MEMBER_OF (
    FROM Function TO Community
)
"""

CREATE_REL_CLASS_IN = """
CREATE REL TABLE IF NOT EXISTS CLASS_IN (
    FROM Class TO Community
)
"""

CREATE_REL_STEP_IN_PATHWAY = """
CREATE REL TABLE IF NOT EXISTS STEP_IN_PATHWAY (
    FROM Function TO Pathway,
    step_order INT64,
    role       STRING
)
"""

CREATE_REL_VAR_IN_PATHWAY = """
CREATE REL TABLE IF NOT EXISTS VAR_IN_PATHWAY (
    FROM Variable TO Pathway,
    thread_name STRING,
    thread_step INT64
)
"""

CREATE_REL_STEP_IN_PROCESS = """
CREATE REL TABLE IF NOT EXISTS STEP_IN_PROCESS (
    FROM Function TO Process,
    step_order INT64
)
"""

CREATE_REL_COUPLED_WITH = """
CREATE REL TABLE IF NOT EXISTS COUPLED_WITH (
    FROM File TO File,
    change_count INT64,
    strength     DOUBLE
)
"""

CREATE_REL_MAKES_HTTP_CALL = """
CREATE REL TABLE IF NOT EXISTS MAKES_HTTP_CALL (
    FROM Function TO Function,
    http_method  STRING,
    url_pattern  STRING,
    confidence   DOUBLE,
    reason       STRING
)
"""

# ---------------------------------------------------------------------------
# Ordered list for initialization
# ---------------------------------------------------------------------------

ALL_NODE_TABLES = [
    CREATE_FILE,
    CREATE_FOLDER,
    CREATE_FUNCTION,
    CREATE_CLASS,
    CREATE_VARIABLE,
    CREATE_IMPORT,
    CREATE_PATHWAY,
    CREATE_COMMUNITY,
    CREATE_PROCESS,
    CREATE_DUPLICATE_SYMBOL,
    CREATE_DOC_WARNING,
]

ALL_REL_TABLES = [
    CREATE_REL_CONTAINS,
    CREATE_REL_IN_FOLDER,
    CREATE_REL_IMPORTS,
    CREATE_REL_CALLS,
    CREATE_REL_FLOWS_INTO,
    CREATE_REL_DEFINES,
    CREATE_REL_DEFINES_CLASS,
    CREATE_REL_HAS_METHOD,
    CREATE_REL_EXTENDS,
    CREATE_REL_IMPLEMENTS,
    CREATE_REL_MEMBER_OF,
    CREATE_REL_CLASS_IN,
    CREATE_REL_STEP_IN_PATHWAY,
    CREATE_REL_VAR_IN_PATHWAY,
    CREATE_REL_STEP_IN_PROCESS,
    CREATE_REL_COUPLED_WITH,
    CREATE_REL_MAKES_HTTP_CALL,
]
