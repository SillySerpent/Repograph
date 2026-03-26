# RepoGraph Accuracy Reference

This document describes what RepoGraph can and cannot determine statically,
how to interpret confidence scores, and which patterns produce known false
positives or false negatives.

---

## Post-sync structural validation

After a sync, ``repograph.quality.run_sync_invariants(store)`` checks **Q1–Q6**: CALLS endpoints exist, structural edges (DEFINES, DEFINES_CLASS, HAS_METHOD) and IMPORTS endpoints are valid, key topology relationships (MEMBER_OF, CLASS_IN, STEP_IN_PATHWAY, …) reference real nodes, Function ids are not duplicated, and ``get_stats()`` matches independent ``COUNT`` queries (including the same Function filter excluding ``is_module_caller`` sentinels).

These checks do **not** guarantee that **full** and **incremental** sync produce identical graphs, that **Leiden** vs fallback community detection match, or that **folder** structure matches when incremental omits **p02** — see ``tests/README.md`` (parity expectations).

### Test coverage map (``repograph test-map``)

The default table measures **Phase-10** ``is_entry_point`` functions only: share of those (per file) that have an incoming ``CALLS`` edge from test code. Many symbols—including typical ``build_plugin`` factories and helpers—are **not** marked as entry points, so **overall percentages often stay far below 50–70%** even when tests exercise the package heavily.

Use ``repograph test-map --any-call`` for a second metric: the share of **all** non-test **functions** in each file that have a test caller. That aligns better with “does test code call into this file?” The **overall %** can be higher or lower than the entry-point metric: the denominator includes every function, so broad but shallow test suites may show a **lower** headline number than the EP-only view. Neither mode is line or branch coverage; use ``pytest --cov`` for that.

``repograph report --json`` includes both ``test_coverage`` / ``coverage_definition`` (entry-point) and ``test_coverage_any_call`` / ``coverage_definition_any_call``.

---

## What RepoGraph Knows

RepoGraph performs **static analysis only** — it reads source files, builds a
call graph, and applies heuristics.  It never executes code.

| Category | What is known |
|----------|--------------|
| File structure | All files, languages, line counts, test/config/vendored flags |
| Functions & classes | Names, signatures, docstrings, decorators, line ranges |
| Call graph | Which functions call which others (with confidence scores) |
| Imports | Which files import which other files or symbols |
| Inheritance | EXTENDS and IMPLEMENTS edges for in-repo class hierarchies |
| Variables | Assignment, parameter, and return-value tracking within functions |
| Entry points | Scored by callee/caller ratio + pattern heuristics; names with a single leading underscore (`_helper`, not `__init__`) are demoted vs public symbols |
| Dead code | Tiered classification: definitely / probably / possibly dead |
| Duplicates | Same-name symbols across multiple files |
| Config keys | Keys read via `cfg["x"]`, `cfg.get("x")`, `os.getenv("x")` |
| Invariants | Constraints documented in docstrings (`INV-`, `NEVER`, `MUST NOT`) |

---

## What RepoGraph Does NOT Know

| Category | Limitation |
|----------|-----------|
| Runtime behaviour | Dynamic dispatch, monkey-patching, metaprogramming |
| External services | HTTP calls, databases, message queues — shown as terminal nodes |
| Generated code | Migrations, protobuf output — excluded from analysis |
| Plugin loading | `importlib.import_module()`, `__import__()`, entry-points |
| Reflection | `getattr(obj, name)()` — may produce missing or low-confidence edges |
| Bundled JS | Functions called across webpack/rollup bundles without source maps |
| Template rendering | Jinja2/Django template `{% call %}` — not tracked |
| C extensions | `.so`/`.pyd` symbols — not parsed |

---

## Confidence Score Interpretation

Every `CALLS` edge carries a confidence score:

| Range | Meaning | Action |
|-------|---------|--------|
| 0.9–1.0 | Direct call, fully resolved symbol | Trust fully |
| 0.7–0.9 | One-hop inference (method on typed receiver) | Trust in most cases |
| 0.5–0.7 | Pattern-matched (name collision resolved by heuristic) | Verify before relying on |
| < 0.5 | Fuzzy match — name found but resolution uncertain | Manual check required |

Pathway confidence is the geometric mean of all edge confidences in the path.
A pathway with confidence < 0.7 should be treated as a starting hypothesis,
not a proven execution sequence.

**Pathway step order** is BFS over `CALLS` edges from the entry function, not
guaranteed source-line or runtime order. **Python-entry** pathways omit
JavaScript/TypeScript callees on the same walk. **`logging.Handler.emit`** is
treated specially in dead-code analysis (see **ACCURACY_CONTRACT.md**).
**Entry-point caller counts** for subclass overrides may include callers of the
superclass method for scoring. Canonical detail: `docs/ACCURACY_CONTRACT.md`.

---

## Dead Code Tiers

| Tier | Meaning | False-positive risk |
|------|---------|-------------------|
| `definitely_dead` | Zero callers, not in utility module, no exemption | Low for application code; higher for scripts |
| `probably_dead` | Only test callers, only fuzzy callers, or both | Low |
| `possibly_dead` | Exported but uncalled; utility module with zero in-repo callers | Medium — may be public API or external consumer |

**Known safe `possibly_dead` categories:**
- Functions in `utils/`, `helpers/`, `lib/`, `common/`, `shared/` — utility modules designed for import
- Exported functions that are part of the public package API

**Do not auto-delete** `possibly_dead` symbols without checking whether they
are referenced by external packages, documentation examples, or scripts outside
the indexed repo root.

**Runtime traces vs static dead code:** Sync runs static analyzers (including dead code) during `on_graph_built`, then runs dynamic overlay when `.repograph/runtime/*.jsonl` traces exist (`on_traces_collected`). The overlay resolves `call` records to graph functions and calls `apply_runtime_observation`, which clears `is_dead` and dead-code tier fields for those functions when the trace matches the current `source_hash`. Anything **not** seen in traces is unchanged by overlay—dynamic analysis does not “prove live” except through resolved JSONL `fn` → graph `qualified_name` matches. Later sync passes skip re-applying static dead flags while `runtime_observed_for_hash` still matches the file hash (see `repograph/plugins/static_analyzers/dead_code/plugin.py`). Full contract: `docs/ACCURACY_CONTRACT.md` (“Runtime traces merged into the graph”).

---

## Entry-Point Scoring

Scores are computed as `callees / (callers + 1)` × multipliers.  A high score
means the function calls many things but is called by few — the signature of an
orchestrator or entry point.

**Multipliers applied:**

| Condition | Multiplier |
|-----------|-----------|
| `is_exported` | ×2.0 |
| Name matches `handle*`, `on_*`, `controller*`, `view*`, `route*` | ×1.5 |
| File is in `routes/`, `handlers/`, `api/`, etc. | ×3.0 |
| File is `__main__.py` or function is `__main__` | ×5.0 |
| Route decorator (`app.post`, `router.get`, etc.) | ×4.0 |
| Celery/Click task decorator | ×3.5 |
| ABC/Protocol concrete implementor (F-04) | ×2.5 |
| File is in `scripts/`, `diagnostics/`, `bin/`, etc. | ×0.1 |
| File is a test file | 0 (hard zero) |

Use `repograph summary --verbose` to see the breakdown for each entry point.

---

## Known False Positives

### Dead code — JS/TS
- **Functions called from HTML `onclick=` or `addEventListener`** — these have
  no static JS callers but are DOM-reachable.  RepoGraph now scans HTML files
  for event-handler references (fixed in F-03).
- **Class methods in `<script src>`-loaded files** — all methods of globally
  loaded classes are now exempt (fixed in F-03).
- **Bundled JS** — if source maps are absent, inter-bundle calls are invisible.

### Dead code — Python
- **Plugin entry points** — functions registered via `setup.cfg` / `pyproject.toml`
  `[project.scripts]` or `[options.entry_points]` have no in-repo callers but
  are reachable from the command line.  These will appear as `possibly_dead`.
- **Functions called only via `__all__`** — if `__all__` re-exports a name that
  is only called externally, it will appear uncalled.
- **`@pytest.fixture` functions** — fixtures are called by the pytest framework
  via injection, not direct calls.  RepoGraph exempts functions with decorators
  from dead-code flagging to handle this.

### Duplicate symbols
- **Common interface methods** — `generate`, `run`, `compute`, `start`, `stop`,
  and similar names are exempt from high/medium duplicate detection because
  they are expected to appear on every class implementing a given interface.

---

## Incremental Sync Accuracy

Incremental sync reprocesses only files whose source hash changed since the
last full sync.  Call edges, heritage edges, and communities are recomputed
from scratch on changed files but may miss:

- Newly added callers of unchanged functions
- Heritage changes in unchanged base classes

**Recommendation:** run `repograph sync --full` after major refactors or when
the call-edge count seems unexpectedly low.

---

## Language-Specific Notes

| Language | Parse quality | Dead code | Call graph |
|----------|--------------|-----------|------------|
| Python | High | High | High (type-annotated code) / Medium (untyped) |
| TypeScript | High | Medium | Medium |
| JavaScript | Medium | Low (bundle uncertainty) | Low–Medium |
| Shell | Low (function detection only) | Low | None |
| HTML | Structure only | N/A | Script-src links only |
| CSS | Not analysed | N/A | N/A |
| Markdown | Not analysed | N/A | Symbol cross-check only |
