# RepoGraph - Repository Intelligence for Humans and AI

RepoGraph turns a codebase into a queryable intelligence graph for exploration, impact analysis, and architecture understanding.

It is a **hybrid static + dynamic analysis tool**:

- **Static analysis** maps files, symbols, imports, call edges, pathways, dead code signals, config usage, and invariants.
- **Dynamic analysis** overlays runtime traces to add observed evidence and correct static blind spots. The default one-shot path is `repograph sync --full`; manual `trace` subcommands are still available for advanced workflows.

## Core Capabilities

- Build a repository-wide symbol and call graph
- Generate pathway context docs for likely execution flows
- Classify dead code with confidence tiers and supporting signals
- Estimate blast radius with dependency and caller impact analysis
- Map module-level structure, config key usage, and architectural invariants
- Surface event topology, interface implementations, and constructor dependency hints
- Merge runtime traces into static analysis to improve confidence and reduce blind spots

## Quick Start

```bash
./setup.sh
./run.sh
```

Or direct CLI:

```bash
pip install -e "."
repograph sync --full
repograph summary
```

Requirements: Python 3.11+

`repograph init` is optional. It only creates the `.repograph/` folder layout ahead of time.

## Interfaces

### CLI (full surface)

Primary interface for local development:

- index/sync: `init`, `sync`, `status`, `watch`, `clean`
- exploration: `summary`, `report`, `modules`, `node`, `query`, `impact`
- architecture: `invariants`, `config`, `test-map`, `events`, `interfaces`, `deps`
- pathways: `pathway list`, `pathway show`, `pathway update`
- runtime tracing (advanced/manual): `trace install`, `trace collect`, `trace report`, `trace clear`
- integrations: `mcp`, `export`, `doctor`, `test`

Full command and flags: [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)

### Python API

Use `RepoGraph` for scripts, test tooling, and service integrations:

```python
from repograph.api import RepoGraph

with RepoGraph("/path/to/repo") as rg:
    rg.sync(full=True)
    print(rg.pathways())
    print(rg.dead_code())
    print(rg.full_report())
```

`RepoGraph.sync(full=True)` is a static full rebuild. The automatic traced-test
overlay workflow is the CLI command `repograph sync --full`.

Surface details: [`docs/SURFACES.md`](docs/SURFACES.md)

### MCP Server (curated AI surface)

Expose RepoGraph to AI tools via MCP:

```bash
repograph mcp /path/to/repo
```

MCP intentionally exposes a curated subset of CLI/API methods.

### Interactive Menu (guided full functionality)

RepoGraph includes a full interactive terminal menu:

```bash
repograph menu
```

The menu includes command browsing, plain-language explanations, and run presets so users can use the full tool without memorizing CLI flags.

## Why use RepoGraph

- Reduce onboarding time in unfamiliar repositories
- Replace ad-hoc grep exploration with structured repository intelligence
- Improve change safety before refactors with impact-first analysis
- Give AI coding agents a reliable map of the project

## Example workflow

```bash
repograph sync --full
repograph summary
repograph modules --issues
repograph pathway list
repograph pathway show <name>
repograph impact <symbol>
```

Then, if needed:

```bash
repograph sync --static-only
repograph trace install
pytest
repograph sync
repograph trace report
```

## Documentation Map

- Start here: [`docs/README.md`](docs/README.md)
- Setup and install tiers: [`docs/SETUP.md`](docs/SETUP.md)
- CLI flags and examples: [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)
- API/CLI/MCP boundaries: [`docs/SURFACES.md`](docs/SURFACES.md)
- Pipeline and hooks: [`docs/PIPELINE.md`](docs/PIPELINE.md)
- Accuracy and known limits: [`docs/ACCURACY.md`](docs/ACCURACY.md)
- Config ownership and generated artifact policy: [`docs/CONFIG_HYGIENE.md`](docs/CONFIG_HYGIENE.md)

## License

RepoGraph is licensed under **GNU AGPL v3.0**.  
See [`LICENSE`](LICENSE).

---

## Development Status

> **RepoGraph is under active development.**  
> Interfaces and docs are being improved continuously; verify behavior against current CLI help and source when integrating deeply.
