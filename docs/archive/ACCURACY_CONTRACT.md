---
repograph_skip_staleness: true
---

# RepoGraph accuracy contract

RepoGraph is **static analysis** over parsed source. It is designed to work on **any** repository that uses supported languages and file layouts; nothing is tuned to a single project.

Machine-readable contract version: see `repograph.trust.contract.CONTRACT_VERSION` (also recorded in `.repograph/meta/health.json` after each sync).

## What tends to be reliable

- **File and module structure**, imports, and many **direct** call edges.
- **Aliased imports** (`from M import X as Y`) - call sites using the alias correctly resolve to the original; aliased functions are not falsely flagged dead.
- **Dead code context** - each flagged symbol has `dead_context`: `dead_everywhere` (zero callers) or `dead_in_production` (only test/script callers).
- **Entry-point scoring** and **pathway sketches** as navigation aids.
- **Duplicate-name** groups with the same language and qualified names (when configured).
- **Dead code** for **small, pure helpers** with no imports and no inheritance story — after verifying **`CALLS`** edges, especially for **instance methods** (`obj.method`).

### Runtime traces merged into the graph

When JSONL traces exist under `.repograph/runtime/`, sync can **persist**
observations onto `Function` nodes: `runtime_observed`,
`runtime_observed_for_hash` (the file `source_hash` at observation time), call counts,
and timestamps. Static dead-code classification **skips** functions whose observation
still matches the **current** `source_hash`. Re-indexing a **changed** file clears stale
runtime fields in `upsert_function`, so dead-code tiers can be recomputed for the new
revision. This does **not** add new `CALLS` edges to the database (those remain static);
it adjusts **per-function** evidence and dead flags only.

`repograph trace report` is read-only: it analyzes collected JSONL files against the
current graph but does not persist overlay results by itself.

## Known limitations (any repo)

1. **Virtual dispatch** — A call `self.method()` on a base-class type may resolve to a subclass override. Incoming call edges to **overrides** may be missing; the **inheritance** dead-code hint mitigates false `definitely_dead` when a same-named method exists on a recorded superclass.
2. **Dynamic calls** — `getattr`, `eval`, reflection, and plugin registries are invisible.
3. **JavaScript** - Bundlers and complex dynamic wiring are not fully modeled. HTML script-tag files are scanned to build cross-file global scope CALLS edges. Server-relative URL paths (e.g. /static/js/utils.js) are resolved via suffix-fallback. Query-string cache busters (?v=21) are stripped before resolution. Same-file `new ClassName()` is used as a conservative live hint for class methods.
4. **Name collisions** — If a **method name** matches an **imported function** in the same scope, resolution prefers **typed-local class methods** when the receiver was inferred from a constructor assignment (`obj = MyClass(...)`). Remaining ambiguity should be treated as **uncertain**.
5. **Mapping-shaped calls** — For receivers **without** a recorded class type (parameters use type hints where available), calls like ``cfg.get(...)`` **do not** resolve to an unrelated class method named ``get`` (e.g. ``FlagStore.get``). Typed receivers (``fs: FlagStore`` → ``fs.get``) still resolve via **typed_local**.
6. **Concurrency** — Kuzu uses a **single writer** per `graph.db`. Only one indexer or writer should open the database at a time; see `RepographDBLockedError` if another process holds the lock. A **``meta/sync.lock``** file indicates an indexer run in progress; **``health.json``** with ``status: failed`` marks an aborted sync.

7. **CALLS edges** — A caller→callee pair has at most one `CALLS` relationship. Additional source lines are stored in `extra_site_lines` (JSON list); `get_all_call_edges()` exposes a merged `lines` array. Schema version **1.1+**; older DB files fall back to a single `line` per edge until the next full rebuild.

8. **Module-scope calls (Python and JavaScript)** — Top-level invocations (e.g. `setup()` after imports, or `foo();` at the end of a `.js` file) have no enclosing user function. RepoGraph attributes them to a synthetic function node **`__module__`** with `is_module_caller=true`, so Phase 5 can emit **`CALLS`** edges from that sentinel to the resolved callee. Behaviour is aligned across Python and JS/TS parsers.

## Doc symbol phase (p15)

Phase 15 checks **backtick identifiers** in Markdown against the symbol graph. It surfaces **`moved_reference`** (high) when a path hint on the line disagrees with where the symbol lives. **Unknown** tokens are not flagged by default (too noisy). Set `doc_symbols_flag_unknown: true` in `repograph.index.yaml` to emit **`unknown_reference`** (medium) for **qualified** (dotted) tokens that look like code but do not appear in the index. Use `RepoGraph.doc_warnings(min_severity="medium")` (or the interactive `medium` filter) to include those rows; `full_report` includes medium-severity doc warnings.

## Interpreting confidence scores

See `README.md` confidence tables. Treat low-confidence edges and **blast radius** on overridden methods as **assistive**, not proof. Run `repograph doctor` after install if imports or the database fail unexpectedly.

## CI / strict sync

`repograph sync --strict` (or `RepoGraph.sync(strict=True)`) re-raises failures from **optional**
downstream phases (duplicate detection, pathway context generation, agent guide, doc symbol check,
and missing optional embedding dependencies) instead of logging a warning. Core parse/import phases
are unchanged. Use this when a green pipeline should mean the full auxiliary toolchain succeeded.

---

## Known limitations and mitigations (added post-audit)

### Logging `Handler.emit` and framework dispatch

**Limitation:** Subclasses of `logging.Handler` implement `emit`; the logging package calls `emit` at runtime. Static analysis often only sees test code calling `handler.emit(...)`, so `emit` could be misclassified as test-only / dead in production.

**Mitigation:** Phase 11 exempts `emit` on classes whose `base_names` include `logging.Handler` (or `logging`-qualified `Handler` bases) from dead-code flagging.

### Pathway BFS vs runtime order; Python vs JS/TS steps

**Limitation:** Pathway steps are produced by breadth-first search over `CALLS` edges from an entry function. Order does not necessarily match source line order or a single execution trace. Mixed Python/JS edges from imprecise resolution could pull unrelated static assets into a pathway.

**Mitigation:** Context documents include an explicit interpretation banner. Pathway expansion from a Python entry skips JavaScript/TypeScript callees on the same walk (and the converse); constants and rules live in `repograph/plugins/static_analyzers/pathways/pathway_bfs.py` for Phase 10; `PathwayAssembler` applies the same language rule.

### Entry-point `entry_caller_count` for method overrides

**Limitation:** `self.method()` may resolve to a base-class `Function` node; subclass overrides can show zero incoming callers despite being live.

**Mitigation:** Phase 10 adds superclass-method caller counts onto subclass override nodes for **scoring only** (no new `CALLS` edges). See `rollup_override_incoming_callers` in `repograph/plugins/static_analyzers/dead_code/plugin.py`.

### Interface-based polymorphism (virtual dispatch via ABCs)

**Limitation:** When callers type their broker/service variable as an interface
(`broker: IBroker`) and Phase 5 resolves the call to the interface method
(`IBroker.submit_order`) rather than the concrete implementation
(`LiveBroker.submit_order`), calling `impact("LiveBroker.submit_order")`
returned 0 callers.

**Mitigation:** `impact()` now falls back to `get_interface_callers()` when
direct callers are empty.  This walks the class hierarchy via `EXTENDS` /
`IMPLEMENTS` edges, finds the corresponding base-class method by name, and
returns its callers with a 0.9× confidence penalty.  The response includes
`"callers_resolved_via_interface"` in `warnings` when the fallback fires.

**Residual gap:** The fallback only triggers when `direct_callers` is empty.
If Phase 5 partially resolves some calls to the concrete method and misses
others, the interface callers are not unioned in.  For a complete blast radius
on polymorphic entry points, also query `impact()` on the interface method
directly.

---

### IO tag false positives on dict.get() / class.get()

**Limitation:** The `⚡ HTTP` annotation in pathway context docs was
incorrectly applied to any function containing `.get(`, `.post(`, etc. —
including plain dict reads (`cfg.get("key")`), flag store methods
(`FlagStore.get_bool`), and any method named `.get()`.

**Mitigation:** The `http_call` regex in `context/formatter.py` is now
anchored to known HTTP client object prefixes: `requests`, `httpx`, `aiohttp`,
`self._session`, `self.client`, `session`, `response`, `resp`, etc.  Plain
`.get()` calls on unrecognised receivers no longer trigger the tag.

---

### Vendored in-tree libraries polluting pathway steps

**Limitation:** When a repository vendors an OSS library in-tree (e.g.
copies `aiosqlite/` into `src/`), that library's internal methods appear
as named pathway steps alongside application code.  This adds irrelevant
steps (e.g. `Connection.execute`, `Connection.commit`) and obscures the
actual data flow.

**Mitigation:** `is_likely_vendored(dir_path)` in `utils/fs.py` detects
vendored directories using a `_KNOWN_OSS_PACKAGES` frozenset plus presence
of `pyproject.toml` / `PKG-INFO` / `setup.py` markers.  Vendored files are
tagged `FileRecord.is_vendored = True` during walk.  `format_context_doc()`
filters vendored steps from EXECUTION STEPS and replaces them with a
footnote: `[+ N step(s) in vendored lib(s): <name>]`.

**Residual gap:** Only libraries in `_KNOWN_OSS_PACKAGES` are detected.
Custom vendored forks with non-standard names will not be filtered.  Add
the package name to `_KNOWN_OSS_PACKAGES` in `utils/fs.py` to extend
coverage.

---

### Community over-fragmentation

**Limitation:** Leiden community detection on large repositories with many
small isolated modules produced 500+ communities on `working.zip`, many with
1-5 members.  This made `communities()` output noisy.

**Mitigation:** `RunConfig.min_community_size` (default: 8) triggers a
post-detection merge pass.  Micro-communities are merged into their
most-connected neighbour by counting cross-community `CALLS` edges.
Isolated micros (no cross-edges) are preserved.  Set
`min_community_size=0` to disable merging.
