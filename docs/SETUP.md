# Setup

RepoGraph supports a few install paths depending on your goal.

From a **git checkout**, you can bootstrap with **`./setup.sh`** (runs `scripts/repograph_setup.py`: venv, editable install, optional first-time profile menu, `repograph doctor`). After that, **`./run.sh`** gives a guided runner (interactive menu, doctor, help, status, or custom args), or you can pass commands directly: `./run.sh sync --full`.

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
repograph sync --full
```

This performs a full static rebuild and, when pytest discovery succeeds, also
runs traced tests and merges runtime observations into the same index. Use
`repograph sync --static-only` when you explicitly want a pure static rebuild.

## Runtime trace tuning (advanced/manual)

`repograph sync --full` is the default dynamic-analysis path. Use the `trace`
subcommands below only when you want manual control over instrumentation or
trace collection.

If trace files get too large, install tracing with bounds and sampling:

```bash
repograph trace install --max-records 500000 --max-mb 128 --rotate-files 2 --sample-rate 0.2
```

For focused capture, add include/exclude filters:

```bash
repograph trace install --include "repograph/(pipeline|runtime)" --exclude "tests/"
```

Inspect collected volume before sync:

```bash
repograph trace collect --json
```

To override the automatic full-sync test command for a repo, add this to
`.repograph/repograph.index.yaml` (or the legacy repo-root `repograph.index.yaml`):

```yaml
sync_test_command:
  - python
  - -m
  - pytest
  - tests
```
