# RepoGraph test layout

## Running

After ``pip install -e ".[dev]"``, the package installs a ``pytests`` command that is equivalent to the ``pytest`` CLI (same ``[tool.pytest.ini_options]`` defaults). From the repo root, ``pytests`` with no arguments runs the full suite under ``tests/``.

```bash
# Full suite (default: ``tests/`` only; see ``pyproject.toml``)
pytests
# or: pytest tests/ -v

# Coverage (``[tool.coverage.*]`` in ``pyproject.toml``)
pytests --cov=repograph --cov-report=term-missing
```

## Markers

Registered in ``pyproject.toml`` (``--strict-markers`` is on — unknown markers fail).

| Marker | Meaning |
|--------|---------|
| ``integration`` | Heavy disk / full-pipeline tests |
| ``slow`` | Noticeably slow |
| ``dynamic`` | Runtime JSONL / overlay |
| ``accuracy`` | Contract + golden fixture checks |
| ``quality`` | Post-sync graph invariant checks (Q1–Q6) |
| ``plugin`` | Registry / scheduler |
| ``requires_mcp`` | Needs ``pip install -e '.[mcp]'`` |

Examples:

```bash
pytest tests/ -m "not integration"
pytest tests/ -m dynamic
pytest tests/ -m requires_mcp
```

### Suggested CI tiers

Use layered jobs so failures are isolated and fast to triage:

1. **unit-fast**: `pytest tests/unit/ -q -m "not dynamic"`
2. **plugin-and-dynamic**: `pytest tests/ -q -m "plugin or dynamic"`
3. **integration**: `pytest tests/integration/ -q`
4. **full** (nightly/release): `pytest tests/ -q`

## Full sync vs incremental parity (expectations)

Do **not** expect bit-identical graphs when comparing **full** vs **incremental** sync, or when **p09** uses **Leiden** vs the **connected-components fallback** (optional ``leidenalg`` / ``igraph``).

- **Incremental** skips **p02** (folder structure) and exits early without hooks when there are **no** file changes; those paths intentionally differ from a full run.
- **Community detection** can assign different ``community_id`` values when the algorithm or seed differs.
- Parity tests in CI should scope comparisons to **stable** subgraphs (e.g. call edges after p05) or document accepted drift instead of requiring identical databases.

## Session tracing (optional)

Default pytest runs do **not** install ``SysTracer``. To trace a test session, copy
``conftest_repograph_trace_install.example.py`` to the repo root as ``conftest.py`` and set
``REPGRAPH_REPO_ROOT`` / ``REPGRAPH_DIR`` if needed. Traces land under ``<repograph_dir>/runtime/*.jsonl``.
