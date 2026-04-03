# RepoGraph test layout

## Running

After installing any dev-capable tier such as `pip install -e ".[dev]"` or the
full workstation bundle, the package installs a `pytests` command that is
equivalent to the `pytest` CLI (same `[tool.pytest.ini_options]` defaults).
From the repo root, either `pytests` or `python -m pytest tests/ -q` runs the
full suite under `tests/`.

For the broadest local baseline, install the **Full local workstation** tier:

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
```

That is the recommended setup if you want the best chance of reproducing the
current verified baseline of over **1.24k passing tests**. If you also run the
optional Pyright quality test, install Node.js so `npx` is available.

```bash
# Full suite
python -m pytest tests/ -q
# or:
pytests

# Coverage (`[tool.coverage.*]` in `pyproject.toml`)
pytests --cov=repograph --cov-report=term-missing
```

The checked-in suite is large enough to matter operationally: the current verified baseline is over 1.24k tests passing.

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

Equivalent RepoGraph CLI profiles:

```bash
repograph test --profile unit-fast
repograph test --profile plugin-dynamic
repograph test --profile integration
repograph test --profile full
```

## Full sync vs incremental parity (expectations)

Do **not** expect bit-identical graphs when comparing **full** vs **incremental** sync, or when **p09** uses **Leiden** vs the **connected-components fallback** (optional ``leidenalg`` / ``igraph``).

- **Incremental** skips **p02** (folder structure) and exits early without hooks when there are **no** file changes; those paths intentionally differ from a full run.
- **Community detection** can assign different ``community_id`` values when the algorithm or seed differs.
- Parity tests in CI should scope comparisons to **stable** subgraphs (e.g. call edges after p05) or document accepted drift instead of requiring identical databases.

## Session tracing (optional)

Start with `repograph sync --full` for the normal runtime-aware workflow.
Default pytest runs do **not** install ``SysTracer`` on their own. If you
explicitly want a manual traced pytest session, run `repograph trace install`
from the repo root. This writes `.repograph/conftest.py`, which pytest
discovers automatically. Traces land under `<repograph_dir>/runtime/*.jsonl`.

## StrayRatz runtime workflows

The heavy StrayRatz runtime workflow tests provision their own temporary copy of
the fixture plus an isolated ``.venv`` from
``tests/fixtures/StrayRatz/requirements.txt``. They do **not** require Flask
and related app dependencies to already be installed in the main RepoGraph dev
environment.

Those tests also own their cleanup boundary: the copied StrayRatz repo,
generated ``.repograph`` directory, SQLite files, launchers, and temporary
fixture ``.venv`` all live under one temp workspace and are deleted on teardown.
