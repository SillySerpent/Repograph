# RepoGraph Pipeline Reference

The analysis pipeline transforms a raw repository into a queryable graph.
Each phase is a Python module in `repograph/pipeline/phases/` with a `run()`
entry point. Phases run in numeric order; optional phases can fail without
aborting the sync (unless `--strict` is set).

**Graph persistence:** all writes go through a single [`GraphStore`](../repograph/graph_store/store.py) (Kuzu) during the run — streaming MERGE/SET operations from phase modules (`store_writes_upserts.py`, `store_writes_rel.py`). Post-sync structural checks: `repograph.quality.run_sync_invariants`. See [`repograph/pipeline/README.md`](../repograph/pipeline/README.md) (Graph write path).

---

## Phase Map

```
p01 → p02 → p03 → p04 → p05 → p05b → p06 → p07 → p08
                                                      ↓
                              p13 ← p12 ← p11b ← p11 ← p10 ← p09
                               ↓
                              p14 → p15 → p16* → p17*
```

`*` = planned, not yet implemented (see improvement plan).

---

## Phase Details

### p01 · Walk
**Module:** `p01_walk.py`  
**Required:** yes  
**Input:** repo root path  
**Output:** `list[FileRecord]`

Walks the repository using `os.walk`, respects `.gitignore` (via `pathspec`),
applies `ALWAYS_EXCLUDE_DIRS` and `ALWAYS_EXCLUDE_EXTENSIONS`, and detects
vendored OSS packages. Each file is hashed for incremental diffing.

---

### p02 · Structure
**Module:** `p02_structure.py`  
**Required:** yes  
**Input:** `list[FileRecord]`, store  
**Output:** `File` and `Folder` nodes in graph

Writes `File` nodes and `Folder` hierarchy into the graph. Marks each file
with `is_test`, `is_config`, `is_vendored` flags.

---

### p03 · Parse
**Module:** `p03_parse.py`  
**Required:** yes  
**Input:** `list[FileRecord]`, store, `SymbolTable`  
**Output:** `list[ParsedFile]`; `Function`, `Class`, `Variable` nodes in graph

Runs tree-sitter parsers for Python, JavaScript, TypeScript, Shell, HTML,
and CSS. Extracts function signatures, class definitions, variable
assignments, decorators, docstrings, and line ranges.

---

### p04 · Import Resolution
**Module:** `p04_imports.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`, repo root  
**Output:** `IMPORTS` edges in graph

Resolves `import` and `require` statements to their target `File` nodes.
Adds all exported symbols to the `SymbolTable` for use by later phases.

---

### p05 · Call Resolution
**Module:** `p05_calls.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`  
**Output:** `CALLS` edges in graph with confidence scores

Resolves function call sites to their target `Function` nodes. Uses the
`SymbolTable` for direct resolution; falls back to fuzzy name matching
(confidence < 0.5) when the target cannot be resolved exactly.

---

### p05b · Callback / Registration Detection
**Module:** `p05b_callbacks.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`  
**Output:** additional `CALLS` edges for callback registrations

Detects patterns like `event_bus.subscribe(EventType.X, handler)`,
`app.route('/path')(handler)`, and framework-specific registration calls.
Creates `CALLS` edges that would be missed by direct call-site analysis.

---

### p06 · Heritage (Inheritance)
**Module:** `p06_heritage.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`  
**Output:** `EXTENDS` and `IMPLEMENTS` edges in graph

Resolves base class names for all parsed classes. Pure stdlib bases
(`object`, `Exception`, etc.) are skipped. Protocol/ABC bases create
`IMPLEMENTS` edges; all others create `EXTENDS` edges.

---

### p07 · Variable Tracking
**Module:** `p07_variables.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store  
**Output:** `Variable` nodes; variable flow data for pathway context

Tracks variable assignments, parameter bindings, and return values within
function bodies. Feeds the variable-thread section of pathway context docs.

---

### p08 · Type Annotation Analysis
**Module:** `p08_types.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`  
**Output:** `is_type_referenced` flags on `Class` nodes

Scans type annotations and marks classes that appear only as type hints
(not instantiated or called). Used by Phase 11 to avoid false-positive
dead-code on type-only classes.

---

### p09 · Community Detection
**Module:** `p09_communities.py`  
**Required:** no (optional — requires `leidenalg` + `igraph`)  
**Input:** store (call graph)  
**Output:** `Community` nodes; `community_id` on `Function` nodes

Runs the Leiden community detection algorithm over the call graph to
identify tightly coupled module clusters. Micro-communities below
`min_community_size` (default 8) are merged into their most-connected
neighbour.

---

### p10 · Entry-Point Scoring + Pathway BFS
**Module:** `p10_processes.py`  
**Required:** yes  
**Input:** store  
**Output:** `entry_score` flags on `Function` nodes; `Pathway` nodes

Scores every function using `pathways/scorer.score_function()`. Test
functions always score 0.0. Functions that are concrete implementations of
abstract methods receive a ×2.5 boost (`_ABC_IMPL_MULT`). After raw caller
counts are aggregated from `CALLS` edges, **subclass overrides** add the
incoming caller count of the matching in-repo superclass method (same name) so
`entry_caller_count` reflects virtual dispatch for scoring.

The top-N candidates are traced via BFS through `CALLS` edges using
`plugins/static_analyzers/pathways/pathway_bfs.py` (shared constants and traversal). BFS **does not** hop
from `.py` entry files to `.js`/`.tsx`/etc. callees (or the reverse), avoiding
mixed-language pathway noise.

---

### Dead code (sync plugin, not a numbered phase)

**Implementation:** `plugins/static_analyzers/dead_code/` (`on_graph_built`).  
**Required:** yes (runs after the graph build)  
**Input:** store  
**Output:** `is_dead`, `dead_code_tier`, `dead_code_reason` flags on `Function` nodes

Multi-pass tiered classification:

| Tier | Meaning |
|------|---------|
| `definitely_dead` | Zero callers; not in a utility module; no exemption applies |
| `probably_dead` | Only test callers, only fuzzy callers, or only test+fuzzy |
| `possibly_dead` | Exported but uncalled; utility module with zero callers; weak callers only |

Key exemptions (never flagged): entry points, dunder methods, test functions,
lifecycle hooks, closure-returned functions, module-level callers, JS class
methods in HTML-script-loaded files, HTML event-handler referenced symbols,
subclass methods, type-referenced classes, superclass-chain methods,
and ``emit`` on ``logging.Handler`` subclasses (stdlib invokes it dynamically;
see the dead-code plugin’s framework hooks in the same package).

---

### p11b · Duplicate Symbol Detection
**Module:** `repograph/plugins/static_analyzers/duplicates/plugin.py` (`run_duplicate_analysis`)  
**Required:** no  
**Input:** store  
**Output:** `DuplicateSymbol` nodes

Three severity tiers: `high` (same qualified name in 2+ non-test files),
`medium` (same name + identical signature), `low` (same name 3+ times in
one file). Dunder names and common interface method names are exempt.
When one copy is dead, the group is tagged `is_superseded=True`.

---

### p12 · Git Co-Change Coupling
**Module:** `p12_coupling.py`  
**Required:** no (requires `.git` directory)  
**Input:** store, repo root, git history (default last 180 days)  
**Output:** `CO_CHANGES_WITH` edges between `File` nodes

Analyses git commit history to find files that frequently change together.
High-coupling pairs indicate architectural dependencies that static analysis
alone cannot see.

---

### p13 · Vector Embeddings
**Module:** `p13_embeddings.py`  
**Required:** no (optional — requires `sentence-transformers`)  
**Input:** store  
**Output:** embedding vectors on `Function` and `Class` nodes

Generates semantic vector embeddings for function docstrings and signatures.
Enables `search()` to use semantic similarity in addition to BM25 + fuzzy.

---

### p14 · Pathway Context Document Generation
**Module:** `p14_context.py`  
**Required:** no  
**Input:** store  
**Output:** `context_doc` field populated on `Pathway` nodes

Generates the human- and AI-readable context document for each pathway,
including execution steps, config key dependencies, I/O annotations, and
variable threads. Uses a token budget to fit within model context windows.

---

### Doc symbol cross-check (export plugin)

**Implementation:** `plugins/exporters/doc_warnings/` (hook: `on_export`).  
**Required:** no  
**Input:** store, repo Markdown files  
**Output:** `DocWarning` nodes for stale or moved symbol references

Scans Markdown files for backtick-quoted symbol references and checks whether
each still exists in the graph. Reports `moved_reference` when the path hint
in the doc disagrees with the symbol's actual location.

---

### p16 · Module Index *(planned — I-01)*
**Module:** `p16_modules.py` *(not yet implemented)*

Will aggregate per-directory statistics (file count, key classes, dead code
flags, duplicate flags) and write `ModuleIndex` JSON to
`.repograph/meta/modules.json`. Powers the `repograph modules` command.

---

### p17 · Architectural Invariant Extraction *(planned — I-05)*
**Module:** `p17_invariants.py` *(not yet implemented)*

Will scan function and class docstrings for invariant markers (`INV-`,
`INVARIANT:`, `CONTRACT:`, `NEVER`, `MUST NOT`, etc.) and store them as
first-class `Invariant` nodes in the graph. Powers the `repograph invariants`
command.

---

## Adding a New Phase

See [CONTRIBUTING.md](../CONTRIBUTING.md#how-to-add-a-new-pipeline-phase).
