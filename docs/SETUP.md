# Setup

RepoGraph supports a small number of install paths depending on what you need to do.

From a **git checkout**, you can bootstrap with **`./setup.sh`** (runs `scripts/repograph_setup.py`: venv, editable install, optional first-time profile menu, `repograph doctor`). After that, **`./run.sh`** offers a small menu (interactive CLI, doctor, help, status, or custom `repograph` args) or pass arguments through: `./run.sh sync --full`.

## Install tiers

### Core runtime
Use this when you want to run the CLI/API against repositories and do not need test, MCP, or embedding extras.

```bash
python -m pip install -e .
```

### Community analysis
Adds the optional community-detection stack.

```bash
python -m pip install -e ".[community]"
```

### Development
Adds test dependencies. Pair with `community` if you want the default analysis surface.

```bash
python -m pip install -e ".[dev,community]"
```

### MCP
Adds MCP server dependencies.

```bash
python -m pip install -e ".[mcp,community]"
```

### Full local workstation
Adds every optional dependency. This is the heaviest path because embeddings pull in the sentence-transformers / torch stack.

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
```

## Environment doctor

Use the doctor after setup problems, parser import issues, or database lock confusion.

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

## Runtime trace tuning

If trace files become too large, install tracing with bounds/sampling:

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
