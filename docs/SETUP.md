# Setup

RepoGraph supports a few install paths depending on your goal.

From a **git checkout**, you can bootstrap with **`./setup.sh`** (runs `scripts/repograph_setup.py`: venv, editable install, optional first-time profile menu, `repograph doctor`). In an interactive shell, `./setup.sh` now opens a repo-venv-backed subshell automatically after setup succeeds so later `repograph ...` commands use the repo interpreter by default. After that, **`./run.sh`** remains the safest direct runner because it always prefers `.venv/bin/python` when present, and you can pass commands directly: `./run.sh sync --full`.

## Install tiers

### Core runtime
Use this if you only need the core CLI/API.

```bash
python -m pip install -e .
```

### Community analysis
Adds optional community detection support.

```bash
python -m pip install -e ".[community]"
```

### Development
Adds test dependencies. Pair with `community` for the common dev setup.

```bash
python -m pip install -e ".[dev,community]"
```

### MCP
Adds MCP server dependencies.

```bash
python -m pip install -e ".[mcp,community]"
```

### Full local workstation
Adds every optional dependency. This is the heaviest setup because embeddings pull in the sentence-transformers/torch stack.

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
```

## Environment doctor

Run the doctor when setup/import/database behavior looks wrong.

```bash
python -m repograph doctor
python -m repograph doctor --verbose
```

The doctor checks:
- Python executable/version
- RepoGraph importability
- Kuzu import
- parser package imports
- optional extras availability
- isolated-cwd import behavior
- writable `.repograph/` location for the target repo
- database openability when an index already exists

## First sync

For routine local use, the canonical first full build is:

```bash
./run.sh sync --full
```

This performs a full static rebuild and, when pytest discovery succeeds, also
runs traced tests and merges runtime observations into the same index. Once the
repo venv shell is active, bare `repograph sync --full` is equivalent. Use
`./run.sh sync --static-only` when you explicitly want a pure static rebuild
that skips both automatic test execution and any merge of on-disk
runtime/coverage inputs.

## Runtime trace tuning (advanced/manual)

Start with `./run.sh sync --full`. That is the normal full-power path and the
only workflow routine users should need. When live repo-scoped servers are
present, RepoGraph reports the attach decision explicitly. A single repo-scoped
Python server can be attached automatically only when it is already publishing
a RepoGraph live trace session; otherwise RepoGraph explains why attach was
unavailable or ambiguous before falling back to a managed runtime or traced
tests. If an approved live attach attempt later fails, RepoGraph records that
failed attach attempt and continues with the next eligible fallback mode when
one is available. Once the repo venv shell is active, bare `repograph sync --full`
uses the same interpreter.

Use the `trace` subcommands below only when you intentionally need manual
instrumentation control, want to inspect raw JSONL trace payloads, or are
debugging why automatic runtime capture is not giving you the evidence you
expect.

If trace files get too large, install tracing with bounds and sampling:

```bash
repograph trace install --max-records 500000 --max-mb 128 --rotate-files 2 --sample-rate 0.2
```

For focused capture, add include/exclude filters:

```bash
repograph trace install --include "repograph/(pipeline|runtime)" --exclude "tests/"
```

Inspect collected volume before merging it:

```bash
repograph trace collect --json
```

To override the automatic full-sync test command for a repo, use the settings CLI:

```bash
repograph config set sync_test_command '["python", "-m", "pytest", "tests"]'
```

Or edit `.repograph/repograph.index.yaml` (created by `repograph init`):

```yaml
# sync_test_command:
#   - python
#   - -m
#   - pytest
#   - tests
```

To run a managed Python server under trace instead of relying on tests, configure:

```bash
repograph config set sync_runtime_server_command '["python", "app.py"]'
repograph config set sync_runtime_probe_url '"http://127.0.0.1:8000/health"'
repograph config set sync_runtime_scenario_urls '["/", "/health"]'
repograph config set sync_runtime_scenario_driver_command '["python", "tools/runtime_driver.py"]'
```

This currently supports Python server commands only. RepoGraph will start the
server under ephemeral tracing, wait for the probe URL, request each scenario
URL, optionally run the scenario-driver command with `REPOGRAPH_BASE_URL` in its
environment, then stop the server and merge the collected runtime observations.

If you want `sync --full` to use an already-running local Python server instead
of spawning one, `repograph trace install --mode sitecustomize` is the live
bootstrap path. Restart the server with `.repograph/` on `PYTHONPATH`; the
server will publish a RepoGraph live-session marker and `sync --full` can then
offer to capture a current attach delta from that live process. For unattended
API or automation use, preconfigure `sync_runtime_attach_policy` to `always` or
`never` instead of relying on the CLI confirmation prompt.
