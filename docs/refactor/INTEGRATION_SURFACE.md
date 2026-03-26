# Meridian ↔ RepoGraph Integration Surface

## Meridian entrypoint

Meridian integrates with RepoGraph through:
- `src/main/ipc/repograph.ts`

## IPC handlers that depend on RepoGraph

- `repograph:sync`
- `repograph:query`
- `repograph:pathway`
- `repograph:checkPython`
- `repograph:getAppRoot`
- `repograph:isIndexed`
- `repograph:autoSync`

## RepoGraph surfaces currently relied on

### CLI contract
- `init`
- `sync --full`
- `summary --json`
- `modules --json`
- `pathway show <name>`

### API contract
- `RepoGraph(repo_root)`
- context manager support (`with RepoGraph(...) as rg:`)
- `rg.pathways(min_confidence=0.4)`
- `rg.dead_code()`

## Meridian parsing assumptions

### sync output
Meridian extracts counts from `sync` stdout using regexes matching table rows for:
- `Files`
- `Functions`
- `Pathways`

### summary/modules output
Meridian expects valid JSON from:
- `summary --json`
- `modules --json`

### pathway output
Meridian expects `pathway show <name>` to return a printable document string.

### inline API script
Meridian runs an inline Python script that imports `RepoGraph`, calls `.pathways()` and `.dead_code()`, then prints JSON.

## Refactor rule

The internal RepoGraph codebase may move freely as long as this observable contract remains stable until Meridian is deliberately updated.
