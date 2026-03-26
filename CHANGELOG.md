# Changelog

All notable changes to RepoGraph are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Schema

- **1.2** — `Function` nodes add `entry_score_base`, `entry_score_multipliers`,
  `entry_callee_count`, `entry_caller_count` for verbose score breakdowns.
  Existing graphs require `repograph sync --full` after upgrading.

### Added (RepoGraph improvement plan)

- `utils/path_classifier.py` centralises test / script / docs / vendor path rules.
- Phase 4 records `CALLS` for inline imports; phases 19–20 write `event_topology.json` and `async_tasks.json`.
- Pathway descriptions from docstrings; verbose entry scores persisted on `Function` nodes.
- Module map directory expansion + `category` (production vs tooling); dead-code API includes tooling slices.
- Config registry dotted keys via Python AST; doc staleness skips for annotated blocks.
- Phase 18 meta-invariant filtering.
- CLI: `events`, `interfaces`, `deps`; API: `event_topology`, `async_tasks`, `interface_map`, `constructor_deps`.
- AGENT_GUIDE sections for event bus and background tasks.

### Fixed

- **Community merge without Leiden:** When `igraph`/`leidenalg` are not
  installed, the connected-components fallback (`_run_simple_communities`) now
  runs the same micro-cluster merge and coarse `utils/*` isolation-bucket pass
  as the Leiden path, so environments without optional community dependencies
  still group same-folder singletons.

- **F-01 · Test functions no longer appear in production entry-point lists.**
  `score_function()` in `pathways/scorer.py` now returns `0.0` unconditionally
  for any function whose file path matches a test pattern or whose `is_test`
  flag is set. The guard is applied before any multiplier. `p10_processes.py`
  additionally filters test functions from BFS pathway candidates.
  *Before:* `test_sl_trigger_closes_long_position` scored 9.0 in top entry
  points. *After:* zero test functions in production lists; `ChampionBot.on_tick`
  score rose from 52.5 → 131.2 with noise removed.

- **F-02 · Utility-module helpers no longer false-positively flagged
  `definitely_dead`.** New `_is_utility_file()` helper in `utils/fs.py` detects
  `utils/`, `helpers/`, `lib/`, `common/`, `shared/`, `contrib/`, `support/`.
  Zero-caller functions in these paths are now `possibly_dead /
  utility_module_uncalled` instead of `definitely_dead`.

- **F-03 · JS class methods in HTML `<script src>`-loaded files no longer
  flagged dead.** Two new helpers added to `pipeline/dead_code/javascript.py`:
  `class_method_in_html_script_loaded_file()` and
  `extract_html_reachable_symbols()` (scans `onclick=`, `addEventListener`).

- **Phase 18 invariant patterns improved** to capture inline `(INV-N)`
  references and case-insensitive `Never` mid-sentence, not just leading
  `NEVER` / `INV-N:` prefixes. Added `_PATTERNS` entry for inline refs.
  Now finds 40 invariants in the working repo vs 0 before.

### Added

- **Phase C (accuracy):** Entry-point scoring demotes private helpers (`_*`, not
  dunders) via `private_name_demote` in `pathways/scorer.py`. Config registry
  (Phase 17) excludes test paths and trivial single-character keys; optional
  `repograph sync --include-tests-config-registry` and `repograph config
  --include-tests` (live rebuild). Phase 18 skips Typer/argparse/CLI help prose
  as false invariants. Optional `doc_symbols_flag_unknown: true` in
  `repograph.index.yaml` enables Phase 15 `unknown_reference` (medium) for
  qualified backticks missing from the graph; `RepoGraph.doc_warnings()` accepts
  `min_severity` (high / medium / low).

- **F-04 · ABC / Protocol implementors boosted in entry-point scoring.**
  `_build_abc_implementor_ids()` in `p10_processes.py` uses EXTENDS/IMPLEMENTS
  edges + a polymorphic heuristic (same name across 3+ files). `_ABC_IMPL_MULT
  = 2.5` applied via new `abc_implementor` param on `score_function()`. All 7
  strategy `generate()` methods now surface in pathways.

- **I-01 · `repograph modules` command.** Phase 16 (`p16_modules.py`) builds
  a per-directory module index in `.repograph/meta/modules.json`. CLI command
  with `--issues`, `--min-files`, `--json` flags. `RepoGraph.modules()` API
  method. Replaces needing 100+ `node` calls to understand a repo's structure.

- **I-02 · Docstring annotations in pathway step boxes.** Each step in a
  pathway context doc now shows the function's first docstring sentence.
  `_docstring_first_sentence()` helper added to `context/formatter.py` with
  full Google/reST section-header skip logic.

- **I-03 · Duplicate report canonical version guidance.** `_select_canonical()`
  scoring heuristic added in `repograph/plugins/static_analyzers/duplicates/plugin.py`
  (historically also referenced via `p11b_duplicates.py`). `canonical_path` and
  `superseded_paths` fields added to `DuplicateSymbolGroup` dataclass, schema,
  upsert, and reader. Summary shows which copy is canonical vs stale.

- **I-04 · `repograph config` command.** Phase 17 (`p17_config_registry.py`)
  aggregates all config key reads from pathway docs and source files into
  `.repograph/meta/config_registry.json`. CLI with `--key` blast-radius drill-
  down. `RepoGraph.config_registry()` API method.

- **I-05 · `repograph invariants` command + Phase 18.** Phase 18
  (`p18_invariants.py`) scans function and class docstrings for `INV-N`,
  `INVARIANT:`, `CONTRACT:`, `NEVER`, `MUST NOT`, `NOT thread-safe`, and
  lifecycle constraint patterns. Writes `meta/invariants.json`. CLI with
  `--type` filter. `RepoGraph.invariants()` API method.

- **I-06 · Score breakdown `--verbose` flag.** `ScoreBreakdown` dataclass and
  `score_function_verbose()` added to `pathways/scorer.py`. `score_function()`
  now delegates to it (no behaviour change). `repograph summary --verbose`
  shows per-entry-point multiplier breakdown.

- **I-07 · `repograph test-map` command.** `get_test_coverage_map()` added to
  `store_queries_analytics.py`. CLI shows per-file entry-point coverage
  percentage sorted ascending. `RepoGraph.test_coverage()` API method.

- **`repograph report` command (full intelligence dump).** Single command that
  aggregates every insight into one structured output: purpose, stats, module
  map, top entry points, top pathways with full context docs, dead code, 
  duplicates with canonical guidance, invariants, config registry, test
  coverage, doc warnings, communities. Ideal as a single context injection
  for AI agents. `RepoGraph.full_report()` Python API method.

- **Interactive menu `_action_full_report` rewritten** to delegate to
  `rg.full_report()`. Now includes modules, invariants, config registry, and
  test coverage alongside the original fields.

- **`ScoreBreakdown` exported from `repograph.pathways.scorer`** as a public
  dataclass with `explain()` method.

- **`_is_utility_file()` exported from `repograph.utils.fs`.**

- **`class_method_in_html_script_loaded_file()` and
  `extract_html_reachable_symbols()` exported from
  `repograph.pipeline.dead_code.javascript`.**

- **`tests/test_scorer.py`** — 21 unit tests for F-01 and F-04.

- **`tests/test_dead_code_classifier.py`** — 41 unit tests for F-02 and F-03.

- **`CHANGELOG.md`** — this file.

- **`CONTRIBUTING.md`** — dev setup, code style, pipeline extension guide, PR
  checklist.

- **`docs/PIPELINE.md`** — authoritative phase-by-phase reference (p01–p18).

- **`docs/ACCURACY.md`** — known limitations, confidence interpretation, false-
  positive patterns by language.

- **`docs/CLI_REFERENCE.md`** — full command reference with all flags.

- **`docs/AGENT_USAGE.md`** — recommended 8-step workflow for AI agents,
  efficient patterns for code review and debugging, token budget tips.

### Changed

- **Phase numbering:** `p14_doc_symbols.py` → `p15_doc_symbols.py`. Backward-
  compat shim kept at old path. Runner updated.

- **`DuplicateSymbolGroup` dataclass** gains `canonical_path: str` and
  `superseded_paths: list[str]` fields (default-safe; existing consumers
  unaffected).

- **`score_function()` signature** gains `abc_implementor: bool = False`
  parameter (backward-compatible default).

- **`repograph summary`** gains `--verbose / -v` flag.

---

## [0.1.0] — Initial release
  `score_function()` in `pathways/scorer.py` now returns `0.0` unconditionally
  for any function whose file path matches a test pattern or whose `is_test`
  flag is set.  The guard is applied before any multiplier, so no decorator,
  export flag, or callee count can rescue a test function into the production
  summary.  `p10_processes.py` additionally filters test functions from BFS
  pathway candidates as a defence-in-depth measure.
  *Before:* `test_sl_trigger_closes_long_position` scored 9.0 and appeared in
  top entry points.  *After:* zero test functions in production entry-point
  lists; `ChampionBot.on_tick` score rose from 52.5 → 131.2 with the noise
  removed.

- **F-02 · Utility-module helpers no longer false-positively flagged
  `definitely_dead`.**  A new `_is_utility_file()` helper in `utils/fs.py`
  detects files living under `utils/`, `helpers/`, `lib/`, `common/`,
  `shared/`, `contrib/`, and `support/` directories.  Functions in these files
  with zero in-repo callers are now classified `possibly_dead` with reason
  `utility_module_uncalled` instead of `definitely_dead`.  This fixes the
  `now_s`, `clamp`, `safe_div`, `ms_to_iso` false positives observed in the
  evaluation.

- **F-03 · JS class methods in HTML `<script src>`-loaded files no longer
  flagged dead.**  Two new helpers were added to
  `pipeline/dead_code/javascript.py`:
  - `class_method_in_html_script_loaded_file()` — exempts any class method
    whose class is defined in a file loaded via an HTML `<script src>` tag.
    Fixes `ChartManager.init`, `ChartManager.setEmas`, `ChartManager.scrollToLive`.
  - `extract_html_reachable_symbols()` — scans HTML `onclick=`, `onload=`,
    and `addEventListener()` attributes and returns referenced symbol names.
    Functions matching these names are exempted from dead-code detection.

### Added

- **F-04 · ABC / Protocol implementors boosted in entry-point scoring.**
  `p10_processes.py` now calls `_build_abc_implementor_ids()` before scoring.
  Functions that are concrete implementations of abstract methods receive a
  `×2.5` multiplier (`_ABC_IMPL_MULT`).  A polymorphic-pattern heuristic
  additionally boosts any bare function name shared by 3+ classes across 3+
  non-test files.  *Before:* 2 of 7 strategy `generate()` methods appeared in
  pathways.  *After:* all 7 surface together.

- **`_is_utility_file(path)` exported from `repograph.utils.fs`.**  Public
  utility for checking whether a file path belongs to a shared helper module.

- **`class_method_in_html_script_loaded_file()` and
  `extract_html_reachable_symbols()` exported from
  `repograph.pipeline.dead_code.javascript`.**

- **`tests/test_scorer.py`** — 21 unit tests covering F-01 (test-zero guard)
  and F-04 (ABC implementor boost), plus regression tests for existing scoring
  behaviours (script demote, route decorator boost, `__main__` boost).

- **`tests/test_dead_code_classifier.py`** — 41 unit tests covering F-02
  (`_is_utility_file` detection and `_classify_tier` integration) and F-03
  (`class_method_in_html_script_loaded_file`, `extract_html_reachable_symbols`).

- **`CHANGELOG.md`** (this file) — tracks all changes from this point forward.
  Every PR must add an entry under `[Unreleased]` before merge.

- **`CONTRIBUTING.md`** — development environment setup, code style, PR
  checklist, and pipeline extension guide.

---

## [0.1.0] — Initial release

First packaged version of RepoGraph including:

- 14-phase analysis pipeline (walk → parse → imports → calls → callbacks →
  heritage → variables → types → communities → entry points → dead code →
  duplicates → coupling → doc symbols)
- KuzuDB graph store with Cypher query interface
- CLI: `init`, `sync`, `status`, `summary`, `doctor`, `pathway`, `node`,
  `impact`, `query`, `watch`, `mcp`, `export`, `clean`
- Python API (`RepoGraph` class) with `sync()`, `status()`, `pathways()`,
  `entry_points()`, `dead_code()`, `duplicates()`, `impact()`, `search()`
- MCP server with 10 tools and 4 resources
- Interactive terminal menu
- Language support: Python, JavaScript, TypeScript, Shell, HTML, CSS, Markdown
- Pathway context documents with variable threads and config dependency tracking
- Incremental sync with file-hash diffing
- Watch mode (`watchdog`-backed)
- Community detection (Leiden algorithm, optional dependency)
- Vector embeddings for semantic search (optional dependency)
