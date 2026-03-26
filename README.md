# RepoGraph

AI-oriented/Human repository intelligence layer. Indexes your codebase into a graph database and exposes pathways, call graphs, dead code, variable flows, and entry points — through a Python API, CLI, or MCP server.

---

## Quick start

From a checkout you can use the helper scripts (executable bit: `chmod +x setup.sh run.sh`):

```bash
./setup.sh                  # runs scripts/repograph_setup.py (venv + editable install + doctor)
./run.sh                    # pick how to run repograph (menu, doctor, help, or custom args)
```

Or install and run the CLI directly:

```bash
pip install -e "."          # or pip install repograph
repograph init              # Init .repograph
repograph sync --full       # index the current directory
repograph status            # check what was found
repograph summary           # one-screen intelligence overview
```

**Requirements:** Python 3.11+.

### Three ways to interact

**1 — CLI (recommended)**

```bash
repograph init [PATH]
repograph sync [PATH]
repograph sync --full [PATH]
repograph status [PATH]
repograph pathway list [PATH]
repograph pathway show <name>
repograph node <file_or_symbol>
repograph impact <symbol>
repograph query <text>
repograph mcp [PATH]
repograph clean [PATH]
```

**2 — Python API**

```python
from repograph.api import RepoGraph

with RepoGraph("/path/to/repo") as rg:
    rg.sync(full=True)
    print(rg.dead_code())
    print(rg.pathways())
```

**3 — MCP server (AI agents)**

```bash
repograph mcp /path/to/repo
```

See [`docs/SETUP.md`](docs/SETUP.md) for install tiers (`core`, `community`, `dev`, `mcp`, `full`).

**Documentation index:** [`docs/README.md`](docs/README.md) · **API / CLI / MCP surfaces:** [`docs/SURFACES.md`](docs/SURFACES.md)

---

## Installation

```bash
# Recommended (includes Leiden community detection)
pip install -e ".[community]"

# With vector embeddings (semantic search)
pip install -e ".[community,embeddings]"

# MCP server support
pip install -e ".[community,mcp]"

# Development
pip install -e ".[community,dev]"
```

**Requirements:** Python 3.11+. On macOS: `brew install python@3.11`

---

## Python API Reference

### `RepoGraph(repo_path, repograph_dir, include_git)`

```python
from repograph.api import RepoGraph

rg = RepoGraph("/path/to/repo")

# Context manager — auto-closes DB handles
with RepoGraph("/path/to/repo") as rg:
    ...
```

| Parameter | Default | Description |
|---|---|---|
| `repo_path` | `os.getcwd()` | Repo root directory |
| `repograph_dir` | `<repo_path>/.repograph` | Where to store the index |
| `include_git` | auto-detected | Analyse git history for coupling |

---

### Core pipeline

```python
# Full rebuild from scratch
stats = rg.sync(full=True)

# Incremental (only changed files)
stats = rg.sync()

# Returns: {"files": 277, "functions": 1936, "classes": 252, ...}
```

---

### Status

```python
rg.status()
# {"initialized": True, "files": 277, "functions": 1936,
#  "pathways": 50, "last_sync": "2026-03-20T09:00:00Z", ...}
```

---

### Pathways

```python
# All pathways sorted by confidence
for p in rg.pathways(min_confidence=0.7):
    print(p["name"], p["confidence"], p["step_count"])

# Full context document (the primary AI injection artifact)
doc = rg.get_pathway("_async_main_flow")
print(doc["context_doc"])   # preformatted text with files, steps, variable threads

# Ordered steps
for step in rg.pathway_steps("_async_main_flow"):
    print(step["step_order"], step["role"], step["function_name"], step["file_path"])
```

---

### Nodes

```python
# By file path
f = rg.node("src/advisor/engine.py")
# {"type": "file", "functions": [...], "classes": [...]}

# By function name
fn = rg.node("validate_credentials")
# {"type": "function", "callers": [...], "callees": [...], ...}

# All indexed files
files = rg.get_all_files()
```

---

### Entry points & dead code

```python
eps = rg.entry_points(limit=20)
# [{"qualified_name": "ChampionBot.on_tick", "entry_score": 49.5, ...}, ...]

dead = rg.dead_code()
# [{"qualified_name": "atr_based_size", "file_path": "src/risk/sizing.py", ...}, ...]
```

Dead code detection automatically exempts:
- ABC / interface implementations (subclasses of abstract bases)
- Methods on classes with `EXTENDS` or `IMPLEMENTS` graph edges
- Classes with names ending in `ABC`, `Interface`, `Base`, `Protocol`, `Mixin`
- Common lifecycle callback names: `start`, `stop`, `run`, `close`, `shutdown`, etc.
- Decorated functions, dunders, test functions
- JavaScript module-scope functions in HTML script-tag loaded files (shared global scope)

Each result now includes a `dead_context` field:
- `"dead_everywhere"` — zero callers of any kind
- `"dead_in_production"` — only called from `tests/` or `scripts/` directories (safe to keep)

Aliased imports (`from M import X as Y`) are fully resolved — functions imported under
aliases are never falsely flagged dead.

---

### Blast radius

```python
result = rg.impact("validate_credentials", depth=3)
# {
#   "symbol": "validate_credentials",
#   "direct_callers": [...],
#   "transitive_callers": [...],
#   "files_affected": ["src/routes/auth.py", ...]
# }
```

---

### Search

```python
results = rg.search("rate limiter", limit=10)
# [{"qualified_name": "RateLimiter.check", "file_path": ..., "signature": ...}, ...]
```

---

### Communities

```python
for c in rg.communities():
    print(c["label"], c["member_count"], c["cohesion"])
# "Advisor"   42 members  cohesion: 0.21
# "Market"    38 members  cohesion: 0.18
```

---

### Raw Cypher

```python
rows = rg.query(
    "MATCH (f:Function {is_dead: true}) RETURN f.qualified_name, f.file_path"
)
```

---

## CLI Reference

```
repograph init [PATH]              Initialize .repograph/ in a repository
repograph sync [PATH]              Incremental re-index
repograph sync --full [PATH]       Force full rebuild
repograph sync --embeddings        Include vector embeddings
repograph sync --no-git            Skip git coupling
repograph sync --strict            Fail on optional-phase errors (CI-friendly)

repograph doctor [PATH]            Verify Python, imports, DB (use after install issues)
repograph status [PATH]            Index health (+ last sync health summary when present)
repograph pathway list [PATH]      All pathways with confidence
repograph pathway show <name>      Full context doc for a pathway
repograph node <file_or_symbol>    Structured data for a file or symbol
repograph impact <symbol>          Blast radius
repograph query <text>             Symbol name search

repograph watch [PATH]             Watch mode: re-sync on changes
repograph watch --strict           Propagate optional-phase failures like sync --strict
repograph mcp [PATH]               Start MCP server (stdio)
repograph export [PATH]            Export graph as JSON
repograph clean [PATH]             Delete .repograph/ entirely
```

---

## MCP Server

10 tools for AI agents:

```bash
repograph mcp /path/to/repo
```

Tools: `get_pathway`, `list_pathways`, `get_node`, `get_dependents`, `get_dependencies`, `search`, `impact`, `trace_variable`, `get_entry_points`, `get_dead_code`

---

## What's indexed

| Phase | What it builds |
|---|---|
| 1–2 | File walk, folder structure |
| 3 | AST parse: functions, classes, imports, call sites, variables |
| 4 | Import resolution → `IMPORTS` edges |
| 5 | Call resolution → `CALLS` edges with ranked fuzzy matching |
| 6 | Class inheritance → `EXTENDS` / `IMPLEMENTS` edges |
| 7 | Variable argument tracking → `FLOWS_INTO` edges |
| 8 | Type annotation analysis |
| 9 | Leiden community detection with package-level labels |
| 10 | Entry point scoring, pathway assembly |
| 11 | Dead code detection with ABC/interface/lifecycle exemptions |
| 12 | Git co-change coupling (optional) |
| 13 | Vector embeddings (optional, `--embeddings`) |\n| 14 | Pathway context document generation |\n| 15 | Doc symbol cross-check |\n| 16 | Module index (`modules.json`) |\n| 17 | Config key registry (`config_registry.json`) |\n| 18 | Architectural invariant extraction (`invariants.json`) |\n\nSee [`docs/PIPELINE.md`](docs/PIPELINE.md) for full per-phase documentation.\n\n---\n\n## CLI Command Reference\n\nAll commands accept an optional `PATH` argument (defaults to current directory).\n\n| Command | Description | Key flags |\n|---------|-------------|----------|\n| `init [PATH]` | Initialise `.repograph/` directory | `--force` |\n| `sync [PATH]` | Index or re-index the repository | `--full`, `--embeddings`, `--no-git`, `--strict` |\n| `report [PATH]` | **Full intelligence dump** — every insight in one command | `--json`, `--pathways N`, `--dead N` |\n| `summary [PATH]` | One-screen overview: purpose, entry points, pathways, issues | `--json`, `--verbose` |\n| `modules [PATH]` | Per-directory structural map (replaces calling `node` on every file) | `--issues`, `--min-files N`, `--json` |\n| `config [PATH]` | Global config-key → consumer mapping | `--key NAME`, `--top N`, `--json` |\n| `invariants [PATH]` | Architectural constraints from docstrings | `--type TYPE`, `--json` |\n| `test-map [PATH]` | Entry-point test coverage per file | `--uncovered`, `--min-eps N`, `--json` |\n| `pathway list [PATH]` | List all detected pathways | `--include-tests` |\n| `pathway show NAME` | Full context doc for a pathway | |\n| `pathway update NAME` | Re-generate context doc for a single pathway | |\n| `node IDENTIFIER` | Structured data for a file path or symbol | |\n| `impact SYMBOL` | Blast radius: everything that calls this symbol | `--depth N` |\n| `query TEXT` | Hybrid search: BM25 + fuzzy name matching | `--limit N` |\n| `status [PATH]` | Index health: node counts, staleness, last sync | |\n| `doctor [PATH]` | Verify Python environment and imports | `--verbose` |\n| `export [PATH]` | Export full graph as JSON | `--output FILE` |\n| `watch [PATH]` | Watch mode: re-sync on file changes | `--no-git`, `--strict` |\n| `mcp [PATH]` | Start the MCP server | `--port N` |\n| `clean [PATH]` | Delete `.repograph/` directory | `--yes` |\n\nFor full flag documentation and examples see [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md).\n\n### Recommended first-use sequence for AI agents\n\n```bash\nrepograph sync          # index the repo\nrepograph report        # every insight in one call\nrepograph modules       # structural map\nrepograph invariants    # architectural constraints\nrepograph pathway show <name>  # full execution context\n```\n\nSee [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) for the full 8-step context-gathering workflow.\n\n---\n\n## Supported Languages\n\n| Language | Parse quality | Call graph | Dead code |\n|----------|--------------|------------|----------|\n| Python | High | High (typed) / Medium (untyped) | High |\n| TypeScript | High | Medium | Medium |\n| JavaScript | Medium | Medium | Low (bundle uncertainty) |\n| Shell | Low (functions only) | None | None |\n| HTML | Structure + script-src links | N/A | N/A |\n| CSS | Not analysed | N/A | N/A |\n| Markdown | Not analysed | Doc symbol cross-check only | N/A |\n\nSee [`docs/ACCURACY.md`](docs/ACCURACY.md) for a full accuracy reference including known false-positive patterns.\n\n---\n\n## Confidence scores

| Range | Meaning |
|---|---|
| 0.9–1.0 | Direct static analysis — fully trustworthy |
| 0.7–0.9 | One inference hop (method call on typed receiver) |
| 0.5–0.7 | Pattern match — verify before relying on |
| < 0.5 | Uncertain — do not rely on without manual check |

For static-analysis limits (virtual dispatch, JS globals, DB locking), see **`docs/ACCURACY.md`**.

---

## Excluding directories from the index

RepoGraph walks the whole tree (respecting `.gitignore`) plus built-in skips like `node_modules` and `.repograph`.

**Automatic:** If your repo contains a nested copy of RepoGraph at `repograph/` with its own `repograph/pyproject.toml`, that top-level folder is **excluded by default** so you do not need any config file.

**Manual:** To skip additional top-level folders, add `repograph.index.yaml` either next to the index (preferred — keeps the tracked repo clean) or at the repository root (legacy):

- `.repograph/repograph.index.yaml` (preferred)
- `repograph.index.yaml` at the repo root (legacy)

Both are merged if present. Example:

```yaml
exclude_dirs:
  - vendor
  - fixtures
# disable_auto_excludes: true   # opt out of the automatic repograph/ exclude above
```

Only **top-level** directory names are supported (no path segments). This does not affect Git; it only changes what gets parsed into the graph.

## Curated pathways (optional)

To override auto-detected pathways, add `pathways.yml` under `.repograph/` (preferred) or at the repository root (legacy). See the pathway curator / assembler docs for the YAML shape.

---

## Output layout

```
.repograph/
  graph.db              KuzuDB graph database
  meta.json             Repo-level index + pathway list
  repograph.index.yaml  optional — extra exclude_dirs (preferred over repo root)
  pathways.yml          optional — curated pathway overrides
  AGENT_GUIDE.md        Navigation guide for AI agents
  pathways/             Per-pathway JSON + Markdown context docs
  mirror/               Per-source-file JSON + Markdown sidecars
  meta/
    file_index.json         File hash index for incremental sync
    staleness.json          Artifact staleness tracking
    modules.json            Per-directory module index (Phase 16)
    config_registry.json    Config key → consumer mapping (Phase 17)
    invariants.json         Architectural invariants from docstrings (Phase 18)
```
