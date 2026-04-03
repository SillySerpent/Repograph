# RepoGraph Accuracy Reference

This document explains what RepoGraph can determine confidently, what it
infers heuristically, how runtime and coverage evidence change the picture, and
how to read the trust signals emitted by the current merged-master codebase.

RepoGraph is static-first, but not static-only. The graph always starts with a
static rebuild or incremental static update. The canonical full-power path,
`repograph sync --full`, can then augment that graph with runtime evidence from
one of several real execution modes:

- `attach_live_python` for one eligible repo-scoped traced Python server
- `managed_python_server` for a RepoGraph-managed traced Python server plus scenario URLs or a scenario-driver command
- `traced_tests` for a traced test run under the current repo interpreter
- `existing_inputs` when RepoGraph reuses existing `.repograph/runtime/*.jsonl` or `coverage.json`
- `none` when no runtime execution or reusable inputs are available

`repograph sync --static-only` is the explicit pure-static rebuild path.

## Recommended validated environment

If you want the broadest validated local environment and the best chance of
matching the current passing test baseline, install the **Full local
workstation** tier instead of a partial extras set:

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
```

This is the recommended RepoGraph install for contributors and operators who
want to reproduce the current verified baseline of over **1.24k passing tests**
locally. Smaller install tiers remain valid for narrower workflows, but the
full workstation tier is the safest documented baseline for the full checked-in
Python test surface. If you also run the optional Pyright quality gate, install
Node.js so `npx` is available.

## Accuracy in practice

- Static graph output is the baseline truth about in-repo structure, symbols, imports, and many call relationships.
- Runtime overlay only proves behavior RepoGraph actually observed and resolved from the collected trace window.
- Coverage overlay only proves executed lines from the `coverage.json` file that was actually merged.
- Absence of runtime or coverage evidence is not proof of absence; it often means the relevant input did not exist or was not applied.
- `health.dynamic_analysis`, `health.analysis_readiness`, `status`, `summary`, and `report` are part of the accuracy story. Read them before treating runtime-derived conclusions as authoritative.

## Reading trust and provenance

Use these surfaces to understand how much evidence backed a result:

| Surface | What to read | Why it matters |
|---------|--------------|----------------|
| CLI `sync --full` output | Selected runtime mode, attach decision, fallback, scenario activity, cleanup result | Tells you what RepoGraph actually executed during this sync |
| `.repograph/meta/health.json` | `dynamic_analysis` and `analysis_readiness` | Machine-readable runtime and coverage provenance |
| `repograph status` | Runtime mode summary, readiness, warnings | Fast operator-facing health check |
| `repograph summary` | High-level trust and risk framing | Good compact view for humans and agents |
| `repograph report` | Deep runtime/coverage findings and warnings | Best place to inspect detailed provenance and overlay effects |

If those surfaces show `mode: none`, no runtime-ready input, or no coverage
overlay, treat dead-code, reachability, and runtime-derived findings as
primarily static analysis output.

## Runtime modes and what they prove

| Runtime mode | What RepoGraph can learn | Important caveat |
|--------------|--------------------------|------------------|
| `attach_live_python` | Observed calls from one already-running repo-scoped traced Python server during the attach window | Only traffic that happens during the attach delta is captured |
| `managed_python_server` | Observed calls while RepoGraph launches the server, waits for readiness, and drives configured scenarios | Only startup plus the exercised scenarios are captured |
| `traced_tests` | Observed calls from the traced test command | Only what the selected tests execute is captured |
| `existing_inputs` | Observed-live or covered evidence from already-present trace or coverage artifacts | Accuracy depends on freshness of those artifacts relative to the indexed source tree |
| `none` | No new runtime evidence | Output is static-first only |

Runtime analysis is a real first-class capability in RepoGraph, but it still
has the normal boundary of runtime tooling: it proves what was observed, not
everything the application could do under every input.

## Post-sync structural validation

After a sync, `repograph.quality.run_sync_invariants(store)` checks **Q1-Q6**:
CALLS endpoints exist, structural edges (`DEFINES`, `DEFINES_CLASS`,
`HAS_METHOD`) and IMPORTS endpoints are valid, key topology relationships
(`MEMBER_OF`, `CLASS_IN`, `STEP_IN_PATHWAY`, and others) reference real nodes,
Function ids are not duplicated, and `get_stats()` matches independent `COUNT`
queries including the same Function filter excluding `is_module_caller`
sentinels.

These checks do **not** guarantee that:

- full and incremental sync produce bit-identical graphs
- Leiden and fallback community detection produce identical communities
- folder structure stays identical when incremental sync omits `p02`

See [`tests/README.md`](../tests/README.md) for the accepted parity
expectations.

## What RepoGraph knows well

| Category | What is usually strong |
|----------|------------------------|
| File structure | File inventory, language classification, line counts, test/config/vendored flags |
| Functions and classes | Names, signatures, decorators, docstrings, line ranges, class relationships |
| Imports | Direct in-repo imports and import aliases |
| Call graph | Direct calls and many one-hop method calls with confidence scores |
| Entry surfaces | CLI commands, route handlers, orchestrators, tasks, and `__main__`-style entry points after scoring |
| Dead-code review | Strong static review aid for application code with few framework indirection tricks |
| Runtime evidence | Observed-live functions, attach/fallback metadata, scenario execution, unresolved-symbol diagnostics when runtime analysis succeeds |
| Coverage evidence | `is_covered` function evidence when a valid `coverage.json` is applied |
| Reports and summaries | High-signal rollups of the currently indexed repo plus runtime provenance |

## What RepoGraph infers heuristically

These surfaces are useful, but should be read as informed inference rather than
hard proof:

| Category | Why caution is needed |
|----------|-----------------------|
| Fuzzy call edges | Name-based or pattern-based resolution can still pick the wrong target |
| Dynamic dispatch | Untyped receivers, monkey-patching, and reflection reduce certainty |
| Plugin loading | `importlib`, `__import__`, entry-point loading, and custom registries can hide edges |
| Cross-language linkage | HTML script-src, route/link matching, and mixed Python/JS boundaries are partial and heuristic |
| External services | HTTP, queues, databases, and RPC systems are usually represented as terminals, not fully modeled remote graphs |
| Runtime attach coverage | A live attach window proves observed activity, not the full lifetime behavior of the server |
| Existing inputs | Reused trace or coverage files may be stale relative to the current source tree |

## What RepoGraph does not know automatically

| Category | Limitation |
|----------|-----------|
| Arbitrary live processes | RepoGraph does not claim universal attach support for every local process type |
| Full-stack browser state | Browser-only behavior outside the configured runtime path is not automatically captured |
| Template execution semantics | Jinja2/Django `{% call %}` and equivalent template dispatch are not deeply modeled |
| Generated code semantics | Generated files may be excluded or treated as opaque |
| Bundled frontend output | Webpack/Rollup/Vite output without usable source linkage remains low-confidence |
| Native extensions | `.so` and `.pyd` symbols are not parsed into the same graph |
| External schema truth | Databases and third-party APIs are not turned into first-class semantic graphs |

## Test coverage map (`repograph test-map`)

The default `repograph test-map` table measures **Phase-10**
`is_entry_point` functions only: the share of those functions, per file, that
have an incoming `CALLS` edge from test code.

That means overall percentages often stay well below line-coverage intuitions,
even when the suite exercises the package heavily. Many helpers, plugin
factories, and framework-driven surfaces are not counted as entry points.

Use `repograph test-map --any-call` for a broader metric: the share of **all**
non-test functions in each file that have a test caller. Neither mode is line
coverage or branch coverage. Use `pytest --cov` for that.

`repograph report --json` includes both entry-point and any-call test-map
summaries.

## Confidence score interpretation

Every `CALLS` edge carries a confidence score:

| Range | Meaning | Recommended reading |
|-------|---------|---------------------|
| 0.9-1.0 | Direct call, fully resolved symbol | Usually trustworthy without extra review |
| 0.7-0.9 | One-hop inference such as a method on a typed receiver | Trust in most cases |
| 0.5-0.7 | Pattern-matched or heuristically disambiguated | Verify before relying on it for a risky change |
| below 0.5 | Fuzzy match with weak resolution certainty | Treat as a lead, not proof |

Pathway confidence is the geometric mean of all edge confidences in the path.
Low-confidence pathways are exploration aids, not authoritative execution
transcripts.

Pathway step order is breadth-first traversal over `CALLS` edges from the entry
function. It is not guaranteed to be source-line order or runtime order.

## Dead-code semantics

| Tier | Meaning | Typical false-positive risk |
|------|---------|-----------------------------|
| `definitely_dead` | Zero callers, not in an exempt utility or convention surface | Low for normal application code; higher for scripts and external APIs |
| `probably_dead` | Only test callers, only fuzzy callers, or both | Low to medium |
| `possibly_dead` | Exported but uncalled, or utility-style module with zero in-repo callers | Medium |

Practical rules:

- Do not auto-delete `possibly_dead` symbols without checking external consumers, documentation examples, scripts, and plugin-style dispatch.
- Runtime overlay can clear stale dead-code flags when an observed trace event resolves to a function with a matching `source_hash`.
- Coverage overlay does not prove reachability. It only marks executed lines from the imported `coverage.json`.
- Dead-code output is a review aid, not delete-on-sight authority.

Runtime overlay diagnostics expose:

- total call records seen
- resolved and unresolved call counts
- unresolved symbol examples

That is intentional. RepoGraph tries to make weak runtime signal visible instead
of quietly pretending the runtime pass was rich enough to justify stronger
claims.

## Entry-point scoring

RepoGraph scores likely entry surfaces using graph structure plus operator-facing
heuristics. The signal is strongest for public CLI commands, route handlers,
`__main__` entry points, tasks, and orchestration functions. Internal parser
machinery, plugin bootstrap helpers, and non-operator lifecycle plumbing are
demoted where the scorer knows about them.

The score is still a ranking aid, not a mathematical proof that a function is
the most important entry point in the repo.

## Common false positives and false negatives

### Dead code and reachability

- Functions called through reflection, metaprogramming, or registry lookup can appear uncalled.
- Public package APIs used only outside the indexed repo can appear as `possibly_dead`.
- Framework-owned injection points such as pytest fixtures are not reached through ordinary in-repo callers.
- Browser-triggered JavaScript paths can look dead when they are only reachable from HTML or bundled frontend state.

### Duplicate symbols

- Common interface methods such as `run`, `start`, `stop`, or `generate` are expected to repeat across implementations.
- Required plugin contract names such as `build_plugin` can legitimately duplicate.
- Duplicate reports are review prompts, not automatic cleanup authority.

### Runtime evidence

- Runtime overlay only covers the attach window, the driven managed scenarios, or the traced test execution that actually ran.
- Unresolved runtime symbols mean the trace saw activity that the current graph could not map cleanly.
- Reused runtime inputs can give valid historical evidence but still be stale for the current checkout.

## Incremental sync caveats

Incremental sync is intentionally not a bit-for-bit substitute for a fresh full
static rebuild.

You should expect possible differences when:

- new callers were added in unchanged files
- inheritance relationships shifted in unchanged base classes
- folder-structure details depend on a phase incremental sync does not rerun
- community detection falls back differently or reuses different cached state

Recommendations:

- Use `repograph sync --full` for the canonical full-power refresh.
- Use `repograph sync --static-only` when you explicitly want a pure static rebuild with no runtime execution or overlay merge.
- Re-run a fresh static rebuild after large refactors if the graph shape looks suspiciously stale.

When the latest sync mode is `incremental_traces_only`, treat the result as a
runtime-overlay refresh over an existing static index, not as a fresh rebuild.

## Language coverage and certainty

| Language or surface | Parse quality | Typical graph confidence |
|---------------------|---------------|--------------------------|
| Python | High | High in typed/direct-call code, medium when runtime dispatch dominates |
| TypeScript | High | Medium to high depending on project structure and explicit imports |
| JavaScript | Medium | Low to medium because frontend and dynamic patterns are looser |
| HTML | File indexing plus script-src scanning | Structural only, with limited JS linkage |
| CSS | File indexing only | Structural only |
| Shell | File indexing only | Structural only |
| Markdown | Not deeply parsed into the graph | Reference and documentation support only |

RepoGraph’s cross-language story is useful, but partial. Python, JavaScript,
and TypeScript are the primary parser-backed languages. HTML linkage exists, but
it is not a full browser execution model. CSS and shell files participate in
repository structure more than semantic call analysis.

## Bottom line

RepoGraph is strongest when you read it as:

- a high-confidence static repository graph
- plus runtime evidence when `sync --full` actually collected or merged it
- plus clear provenance signals that tell you which claims are structural, which are observed, and which remain heuristic

For the most trustworthy local baseline, use the **Full local workstation**
install tier, run the canonical `repograph sync --full` workflow, and read the
runtime and readiness fields alongside any dead-code, pathway, or impact result
that matters.
