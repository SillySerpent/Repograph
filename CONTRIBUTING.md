# Contributing to RepoGraph

This guide covers the current contributor workflow: setup, validation, where the live entry surfaces are in the codebase, and the docs/tests you are expected to update with your changes.

## Development Environment Setup

Requirements: Python 3.11+.

Fastest repo-local path:

```bash
git clone <repo-url>
cd <checkout-dir>
./setup.sh
```

Recommended contributor baseline:

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
repograph doctor
```

That is the safest contributor install when you want the best chance of
matching the current verified baseline of over **1.24k passing tests**. If you
prefer a lighter core contributor environment, `python -m pip install -e
".[dev,community]"` remains valid for narrower work. Install Node.js as well if
you plan to run the optional Pyright quality gate.

Useful extras when you are intentionally not using the full workstation tier:

- `.[mcp]` for the MCP server
- `.[embeddings]` for semantic search/ranking
- `.[templates]` for template-related extras

See [`docs/SETUP.md`](docs/SETUP.md) for the full install-tier matrix.

## Running the Test Suite

See [`tests/README.md`](tests/README.md) for markers, session-tracing notes, and layout.

Recommended local matrix:

```bash
python -m pytest tests/unit/ -q -m "not dynamic and not integration and not requires_mcp"
python -m pytest tests/ -q -m "plugin or dynamic"
python -m pytest tests/integration/ -q
python -m pytest tests/ -q
```

Equivalent CLI profiles:

```bash
repograph test --profile unit-fast
repograph test --profile plugin-dynamic
repograph test --profile integration
repograph test --profile full
```

Optional type-check quality gate:

```bash
python -m pytest tests/quality/test_pyright_codebase.py -q -m pyright
```

That test shells out to a pinned `npx pyright` run, so it requires Node.js with
`npx` available.

## Codebase Orientation

These are the high-value entry surfaces for contributors:

- Console entry: `repograph/entry.py`
- CLI surface package: `repograph/surfaces/cli/`
- Python API facade: `repograph/surfaces/api.py`
- MCP surface: `repograph/surfaces/mcp/`
- Shared service layer: `repograph/services/`
- Pipeline facade: `repograph/pipeline/runner.py`
- Focused runner implementation: `repograph/pipeline/runner_parts/`
- Runtime orchestration and execution: `repograph/runtime/`
- Settings system: `repograph/settings/`
- Plugin families and lifecycle wiring: `repograph/plugins/`

If you are changing operator behavior, trace the real call path through the surface layer, `RepoGraphService`, runner/runtime orchestration, settings, tests, and docs before you edit.

## Validation and Style Expectations

- Keep public function signatures typed.
- Add comments/docstrings only where they explain intent, invariants, or non-obvious constraints.
- Do not add new top-level dependencies casually; update `pyproject.toml` and docs when you do.
- The checked-in quality bar is driven primarily by tests and the pinned Pyright quality test, not a repo-wide Black/Ruff configuration in `pyproject.toml`.
- If you change runtime behavior, update the operator-facing docs and health/report wording in the same change.

## How to Add or Change a CLI Command

1. Start in `repograph/surfaces/cli/commands/` for the shipped CLI command path.
2. If the change affects app assembly or shared CLI behavior, update `repograph/surfaces/cli/app.py` and related output/rendering helpers.
3. If the change affects entry dispatch or menu presets, also audit `repograph/entry.py` and the interactive catalog.
4. Wire the command to the real service/runtime architecture instead of duplicating business logic in the CLI.
5. Update the relevant user docs in the same change:
   - [`README.md`](README.md)
   - [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)
   - [`docs/SURFACES.md`](docs/SURFACES.md)
6. Add or update tests that cover the command contract directly.

## How to Add a New Pipeline Phase

1. Add the phase module under `repograph/pipeline/phases/`.
2. Keep the phase focused on one responsibility and route persistence through `GraphStore`.
3. Wire it through the current runner structure in `repograph/pipeline/runner.py` and the appropriate file in `repograph/pipeline/runner_parts/`.
4. Update schema/query/write helpers when new node or edge types are introduced.
5. Update [`docs/PIPELINE.md`](docs/PIPELINE.md).
6. Add focused tests for the new phase behavior.

## Documentation Expectations

If behavior changes, update docs in the same PR. At minimum audit:

- [`README.md`](README.md)
- [`docs/README.md`](docs/README.md)
- [`docs/SETUP.md`](docs/SETUP.md)
- [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)
- [`docs/SURFACES.md`](docs/SURFACES.md)
- [`docs/PIPELINE.md`](docs/PIPELINE.md)
- [`docs/ACCURACY.md`](docs/ACCURACY.md)
- [`docs/ACCURACY_CONTRACT.md`](docs/ACCURACY_CONTRACT.md)
- [`docs/CONFIG_HYGIENE.md`](docs/CONFIG_HYGIENE.md) when settings or config ownership semantics change
- [`tests/README.md`](tests/README.md) when test guidance changes

When the root README links to a document, treat that linked document as part of the same documentation contract.

## PR Checklist

- [ ] Relevant tests pass for the touched behavior
- [ ] New or changed behavior has regression coverage
- [ ] Public-facing docs were updated together with the code
- [ ] Type-check quality gate was considered when typed surfaces changed
- [ ] No stale flags, workflows, or file-path references remain in the touched docs
