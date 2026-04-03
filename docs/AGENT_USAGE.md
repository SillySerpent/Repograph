# RepoGraph for AI Agents

This guide explains how to use RepoGraph most efficiently as an AI agent
doing context-gathering on an unfamiliar repository.

**Documentation index:** [`docs/README.md`](README.md). **CLI vs API vs MCP**
(including what MCP exposes): [`docs/SURFACES.md`](SURFACES.md).

---

## The Core Principle

**Use the fewest tool calls to build the most accurate mental model.**

RepoGraph is designed so that a well-ordered sequence of 5–8 commands gives
you everything needed to reason about a large codebase.  Do not grep random
files — use the structured queries.

---

## Recommended Workflow

### Step 1 — Get the one-screen summary

```
repograph summary
```

This gives you in a single call:
- What the repo does (extracted from README)
- Index size plus sync/runtime health and trust status
- Top 5 operational entry points with scores
- Top 5 pathways with confidence and source
- Major risks plus structural hotspots
- Dynamic-analysis status and warnings

**Decision point:** if the summary alone answers your question, stop here.

---

### Step 2 — Map the module structure

```
repograph modules
```

One call returns the full directory-level structural map: how many files and
classes live in each module, what the key classes are, whether tests exist,
and whether there are known issues.  This replaces calling `node` on every
file.

Filter to problem areas:

```
repograph modules --issues
```

---

### Step 3 — Understand the main flows

```
repograph pathway list
repograph pathway show <name>
```

List gives you all 20–50 detected pathways sorted by importance.  Show gives
the full context document with file paths, line ranges, docstring annotations,
config dependencies, and variable threads.  Each doc starts with **INTERPRETATION**:
steps are **BFS over the call graph**, not guaranteed source-line or runtime order.

For the most important repo flows, read the top 3–5 pathways.  Each pathway
doc is designed to replace reading 10–20 source files.

---

### Step 4 — Check architectural constraints

```
repograph invariants
```

Before modifying anything, check whether the symbols you're working with have
documented constraints.  This surfaces `NEVER`, `MUST NOT`, `INV-N`,
`NOT thread-safe`, and similar annotations from docstrings.  Violating an
invariant is a common source of hard-to-debug bugs.

---

### Step 5 — Drill into a specific symbol

```
repograph node <file_or_symbol>
```

Use this when a pathway or module map points you to a specific file or class.
Returns: all functions in the file with line ranges, entry-point flags, and
dead-code flags.

For a symbol: returns callers, callees, signature, and pathway membership.
Prefer exact qualified names when possible; if a short name is ambiguous,
RepoGraph now shows the candidate list instead of guessing.

---

### Step 6 — Assess change impact

```
repograph impact <symbol>
```

Before modifying a function, check its blast radius.  Returns direct callers,
transitive callers up to depth 3, and affected files.  Use this to know which
tests to run and which other modules may need updating.
If the symbol name is ambiguous, `impact` returns the candidates and asks you
to retry with the exact qualified name.

---

### Step 7 — Find something by concept

```
repograph query "rate limiting middleware"
```

When you know what you're looking for but not its exact name.  Uses BM25 +
fuzzy name search and returns ranked results with type (function/class/pathway)
and file path.

---

### Step 8 — Understand config dependencies

```
repograph config
repograph config --key trading
```

Use `config --key` to understand what breaks when a config value changes.
Returns all pathways and files that read that key.

---

## Efficient Pattern for Code Review

When reviewing a PR or understanding a change:

1. `repograph summary` — current state of the repo
2. `repograph impact <changed_symbol>` — what the change affects
3. `repograph pathway show <relevant_pathway>` — full execution context
4. `repograph node <changed_file>` — all functions in the changed file
5. `repograph invariants --type constraint` — constraints on nearby symbols

---

## Efficient Pattern for Debugging

When diagnosing unexpected behavior:

1. `repograph pathway show <entry_point_near_bug>` — trace execution path
2. `repograph node <suspect_function>` — callers and callees
3. `repograph config --key <relevant_config>` — config consumers
4. `repograph query "<error_message_keywords>"` — find related symbols
5. `repograph impact <suspect_function>` — what depends on it

---

## Confidence Interpretation

Always check the confidence score on pathways and edges:

| Score | Meaning |
|-------|---------|
| ≥ 0.9 | Derived from direct static analysis — trust fully |
| 0.7–0.9 | One hop of inference — trust in most cases |
| 0.5–0.7 | Pattern-matched — verify before relying on |
| < 0.5 | Fuzzy — do not rely on without manual check |

---

## What NOT to Do

- **Do not grep source files to build your own call graph** — RepoGraph has
  already done this with higher accuracy than string matching.
- **Do not read every file in a module** — use `repograph modules` and
  `repograph pathway show` instead.
- **Do not trust `definitely_dead` blindly for functions in `utils/`** — these
  are `possibly_dead` (utility module pattern) and may be intentionally kept.
- **Do not ignore invariants** — `repograph invariants` is the fastest way to
  find the constraints that will break your changes.

---

## Token Budget Tips

When operating under a tight context window:

- `repograph summary --json` is the most compact overview
- `repograph modules --json` gives the full structure in ~50 lines
- `repograph pathway list` gives all pathway names in ~30 lines
- A single `repograph pathway show <n>` is ~80–120 lines and replaces
  reading 10–20 source files
