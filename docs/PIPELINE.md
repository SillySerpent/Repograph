# RepoGraph Pipeline Reference

RepoGraph has one static graph-build pipeline plus a runtime-aware full-sync coordinator.

For the broadest validated local baseline when reproducing the current verified
suite of over **1.24k passing tests**, use the **Full local workstation**
install tier documented in [`SETUP.md`](SETUP.md). Install Node.js as well only
if you plan to run the optional Pyright quality gate.

## Runner layout

[`repograph/pipeline/runner.py`](../repograph/pipeline/runner.py) is the stable public facade used by CLI, services, and tests. The implementation is split under [`repograph/pipeline/runner_parts/`](../repograph/pipeline/runner_parts/) by responsibility:

- `config.py` — `RunConfig` and validation
- `shared.py` — observability scopes, warning policy, and cleanup helpers
- `build.py` — static phase execution and optional SPI phases
- `hooks.py` — post-build hook execution and summary merging
- `full.py` — full static rebuild coordination
- `incremental.py` — incremental coordination
- `full_runtime.py` — full rebuild plus runtime-plan execution and overlay merge

## Canonical full-power flow

`repograph sync --full` is the documented full-power workflow. When `auto_dynamic_analysis` is enabled, RepoGraph:

1. rebuilds the static graph,
2. resolves a runtime plan (`attach_live_python`, `managed_python_server`, `traced_tests`, `existing_inputs`, or `none`),
3. executes that plan when appropriate,
4. merges runtime and coverage overlays,
5. finalizes hook/export outputs and health metadata.

`repograph sync --static-only` uses the same static build path without runtime-plan execution or runtime-input merge.

## Static graph build and hook layers

RepoGraph then runs in two layers:

1. **Core graph-build phases** in `repograph/pipeline/phases/` (p01-p13).
2. **Plugin hooks** after graph build (`on_graph_built`, `on_evidence`, `on_export`, runtime-trace hooks).

Optional failures in optional phases/hooks are tolerated unless `--strict` is set.

**Graph persistence:** all writes go through a single [`GraphStore`](../repograph/graph_store/store.py) (Kuzu) during the run — streaming MERGE/SET operations from phase modules (`store_writes_upserts.py`, `store_writes_rel.py`). Post-sync structural checks: `repograph.quality.run_sync_invariants`. See [`repograph/pipeline/README.md`](../repograph/pipeline/README.md) (Graph write path).

---

## Execution Map

```
p01 -> p02 -> p03 -> p03b -> p04 -> p05 -> p05b -> p05c -> p06 -> p06b -> p07 -> p08 -> p09 -> p10
                                                                                               \-> p12 (optional)
                                                                                               \-> p13 (optional)
then:
on_graph_built -> on_evidence -> on_export
if runtime inputs exist:
on_traces_collected -> on_traces_analyzed
```

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

Runs the registered parser plugins for Python, JavaScript, and TypeScript.
Extracts function signatures, class definitions, variable assignments,
decorators, docstrings, and line ranges. Files in other indexed languages
still remain part of the file graph even when they do not have a full parser
plugin.

---

### p03b · Framework Tags
**Module:** `p03b_framework_tags.py`
**Required:** yes
**Input:** `list[ParsedFile]`, store
**Output:** framework-derived route/layer/role metadata on matching files and functions

Persists framework-adapter outputs after parsing so route handlers, page
components, and related framework surfaces are tagged before later phases run.

---

### p04 · Import Resolution
**Module:** `p04_imports.py`  
**Required:** yes  
**Input:** `list[ParsedFile]`, store, `SymbolTable`, repo root  
**Output:** `IMPORTS` edges in graph

Resolves `import` and `require` statements to their target `File` nodes.
Adds all exported symbols to the `SymbolTable` for use by later phases. This
phase also scans HTML files for local `<script src>` tags and inserts
synthetic import edges so browser-loaded JavaScript files are connected into
the graph.

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

### p05c · HTTP Call Detection
**Module:** `p05c_http_calls.py`
**Required:** yes
**Input:** `list[ParsedFile]`, store
**Output:** `MAKES_HTTP_CALL` edges between HTTP client sites and in-repo route handlers

Matches Python HTTP client usage against framework-tagged route metadata so
RepoGraph can connect caller sites to in-repo handlers across file and layer
boundaries.

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

### p06b · Layer Classification
**Module:** `p06b_layer_classify.py`
**Required:** yes
**Input:** `list[ParsedFile]`, store
**Output:** layer/role tags on file and function nodes

Applies architecture-layer heuristics after structural parsing. Framework-
provided tags win first; import/path-based classification fills the remaining
gaps.

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
`min_community_size` (default 3) are merged into their most-connected
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
Enables the hybrid search path to use semantic similarity in addition to
keyword and fuzzy ranking when embeddings are available.

---

### Post-build outputs (plugin hooks, not numbered core phases)

Several user-facing outputs are produced by plugins via hooks instead of numbered phase modules:

- docs mirror sidecars
- pathway context documents
- agent guides
- module summaries
- pathway listings
- summary/status surfaces
- config registry
- invariants
- event topology exports
- async task exports
- entry-point summaries
- doc warnings
- runtime overlay summaries
- observed runtime findings
- grouped report surfaces

See:

- `repograph/pipeline/runner.py`
- `repograph/pipeline/runner_parts/`
- `repograph/plugins/`
- `repograph/pipeline/README.md`

`repograph/pipeline/phases/p14_context.py` exists in the tree as a supporting
helper for pathway/doc-reference behavior, but it is not currently part of the
numbered core full/incremental phase chain documented above.

---

### Doc symbol cross-check (export plugin)

**Implementation:** `plugins/exporters/doc_warnings/` (hook: `on_export`).  
**Required:** no  
**Input:** store, repo Markdown files  
**Output:** `DocWarning` nodes for stale or moved symbol references

Scans Markdown files for backtick-quoted symbol references and checks whether
each still exists in the graph. Reports `moved_reference` when the path hint
in the doc disagrees with the symbol's actual location.

## Adding a New Phase

See [CONTRIBUTING.md](../CONTRIBUTING.md#how-to-add-a-new-pipeline-phase).
