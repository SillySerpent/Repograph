# Contributing to RepoGraph

Thank you for contributing. This document covers everything you need to get
a development environment running, understand the codebase, and get a PR
merged cleanly.

---

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Running the Test Suite](#running-the-test-suite)
3. [Code Style](#code-style)
4. [Pipeline Architecture](#pipeline-architecture)
5. [How to Add a New CLI Command](#how-to-add-a-new-cli-command)
6. [How to Add a New Pipeline Phase](#how-to-add-a-new-pipeline-phase)
7. [PR Checklist](#pr-checklist)
8. [Issue References](#issue-references)

---

## Development Environment Setup

**Requirements:** Python 3.11+, pip.

```bash
# Clone and enter the repo
git clone <repo-url>
cd repograph_improved

# Install in editable mode with all optional extras
pip install -e ".[dev,community]"

# Verify the install
repograph doctor
```

The `dev` extra installs `pytest` and `pytest-cov`.  The `community` extra
installs `leidenalg` and `igraph` for community detection.  See [`docs/SETUP.md`](docs/SETUP.md) for the full install-tier matrix.

To also enable the MCP server and vector embeddings:

```bash
pip install -e ".[dev,community,mcp,embeddings]"
```

---

## Running the Test Suite

See **[`tests/README.md`](tests/README.md)** for markers (``integration``, ``dynamic``,
``requires_mcp``, etc.), optional session tracing, and layout.

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=repograph --cov-report=term-missing
```

**Before every PR:** the full suite must pass with zero failures and zero
new warnings.

Recommended maintainable test matrix:

```bash
# Fast guardrail (unit + plugin dispatch)
pytest tests/unit/ -q -m "not integration and not dynamic and not requires_mcp"

# Dynamic/runtime surface
pytest tests/ -q -m dynamic

# Integration confidence
pytest tests/integration/ -q

# Full contract sweep (pre-release / CI nightly)
pytest tests/ -q
```

Equivalent via CLI profiles:

```bash
repograph test --profile unit-fast
repograph test --profile plugin-dynamic
repograph test --profile integration
repograph test --profile full
```

For local reproducibility, prefer the project venv:

```bash
source .venv/bin/activate
python --version
```

---

## Code Style

- **Formatter:** [Black](https://black.readthedocs.io/) — `black repograph/`
- **Linter:** [Ruff](https://docs.astral.sh/ruff/) — `ruff check repograph/`
- **Type hints:** required on all public function signatures
- **Docstrings:** required on all public functions and classes (one-line minimum)
- **No new top-level dependencies** without explicit discussion and
  pyproject.toml update

Quick check before pushing:

```bash
black --check repograph/
ruff check repograph/
```

---

## Pipeline Architecture

RepoGraph analyses a repository in sequentially numbered phases. Each phase
is a module in `repograph/pipeline/phases/` with a `run()` entry point.

| Phase | Module | Description | Required |
|-------|--------|-------------|----------|
| p01 | `p01_walk.py` | File walk + gitignore | ✅ |
| p02 | `p02_structure.py` | Folder tree | ✅ |
| p03 | `p03_parse.py` | AST parsing for all languages | ✅ |
| p04 | `p04_imports.py` | Import resolution | ✅ |
| p05 | `p05_calls.py` | Call-graph resolution | ✅ |
| p05b | `p05b_callbacks.py` | Callback / registration patterns | ✅ |
| p06 | `p06_heritage.py` | Class inheritance (EXTENDS/IMPLEMENTS) | ✅ |
| p07 | `p07_variables.py` | Variable tracking | ✅ |
| p08 | `p08_types.py` | Type annotation analysis | ✅ |
| p09 | `p09_communities.py` | Community detection (Leiden) | optional |
| p10 | `p10_processes.py` | Entry-point scoring + pathway BFS | ✅ |
| p11b | `plugins/static_analyzers/duplicates/` | Duplicate symbol detection | optional |
| p12 | `p12_coupling.py` | Git co-change coupling | optional |
| p13 | `p13_embeddings.py` | Vector embeddings | optional |
| p14 | `p14_context.py` | Pathway context helpers (doc / prose) | optional |

**After the graph build (`p01`–`p12`, optional `p13`):** sync-time analysis and
artefacts run as **plugins** (`on_graph_built`, `on_evidence`, `on_export`) — e.g.
dead code → `plugins/static_analyzers/dead_code/`, doc warnings →
`plugins/exporters/doc_warnings/`. See `repograph/pipeline/README.md` and
`docs/plugins/AUTHORING.md`.

Phases are orchestrated in `repograph/pipeline/runner.py`. Optional phases and
plugin hooks respect `--strict` / `--continue-on-error` where applicable.

---

## How to Add a New CLI Command

1. Add the command function to `repograph/cli.py` using the `@app.command()`
   decorator (or `@pathway_app.command()` for pathway sub-commands).

   ```python
   @app.command()
   def my_command(
       path: Optional[str] = typer.Argument(None),
       some_flag: bool = typer.Option(False, "--flag"),
   ) -> None:
       """One-line description shown in --help."""
       root, store = _get_root_and_store(path)
       # ... implementation
   ```

2. Add the corresponding method to `repograph/api.py` (`RepoGraph` class)
   so the Python API stays in sync with the CLI.

3. Document the command in:
   - `README.md` — CLI command reference table
   - `docs/CLI_REFERENCE.md` — full flag documentation with examples
   - `CHANGELOG.md` — under `[Unreleased] → Added`

4. Add at least one test that calls the API method directly (no CLI invocation
   needed in unit tests).

---

## How to Add a New Pipeline Phase

1. Create `repograph/pipeline/phases/pNN_name.py` where `NN` is the next
   available phase number.

2. Implement a `run(store: GraphStore, ...) -> None` entry point.  Follow the
   existing pattern: pure function, no global state, all I/O through `store`.

3. Add the phase import and call to `runner.py` in both `run_full_pipeline()`
   and `run_incremental_pipeline()`.  Wrap optional phases in
   `_handle_optional_phase_failure()`.

4. If the phase stores new node or edge types, add the schema to
   `repograph/graph_store/schema.py` and the query/write methods to the
   appropriate `store_*.py` split file.

5. Document the phase in `docs/PIPELINE.md`.

6. Add unit tests to `tests/test_phase_NN_name.py`.

7. Update `CHANGELOG.md`.

---

## PR Checklist

Every PR must satisfy all of these before merge:

- [ ] **All existing tests pass** — `pytest tests/ -v` exits 0
- [ ] **New test(s) added** — at least one test covers the changed behaviour
- [ ] **`CHANGELOG.md` updated** — entry added under `[Unreleased]`
- [ ] **Docstrings present** — every new public function and class has a
      docstring (one-line minimum)
- [ ] **Type hints present** — every new public function has annotated
      parameters and return type
- [ ] **Black + Ruff clean** — `black --check` and `ruff check` both pass
- [ ] **New CLI commands documented** — `README.md` and `docs/CLI_REFERENCE.md`
      updated on the same PR
- [ ] **New pipeline phases documented** — `docs/PIPELINE.md` updated

---

## Issue References

The improvement plan uses issue IDs to track work items.  Reference them in
commit messages and PR titles:

| ID | Description |
|----|-------------|
| F-01 | Test functions in production entry points |
| F-02 | Utility module false-positive dead code |
| F-03 | JS class methods in HTML-script files |
| F-04 | ABC implementor scoring |
| I-01 | `repograph modules` command |
| I-02 | Docstring annotations in pathway steps |
| I-03 | Duplicate canonical version guidance |
| I-04 | `repograph config` command |
| I-05 | Architectural invariant extraction (Phase 16) |
| I-06 | Entry score breakdown (`--verbose`) |
| I-07 | `repograph test-map` command |
| H-01 | CHANGELOG.md |
| H-02 | CONTRIBUTING.md |
| H-03 | Phase numbering cleanup |
| H-04 | Unit tests for scorer and dead-code classifier |
| H-05 | README and docs completeness |

Example commit message:

```
fix(dead-code): downgrade utility-module helpers to possibly_dead [F-02]

Functions in utils/, helpers/, lib/, common/, shared/ with zero in-repo
callers are now classified possibly_dead (utility_module_uncalled) rather
than definitely_dead. Adds _is_utility_file() to repograph.utils.fs.
```
