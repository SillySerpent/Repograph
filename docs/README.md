# Docs Home

Use this page as the quick map to the current RepoGraph documentation set.

The default operator path is:

```bash
repograph sync --full
repograph summary
repograph report
```

Use `repograph sync --static-only` when you intentionally want a pure static rebuild with no automatic runtime execution or overlay merge.

For the broadest validated local baseline, use the **Full local workstation**
install tier from [`SETUP.md`](SETUP.md). That is the recommended environment
for reproducing the current verified suite of over **1.24k passing tests**
locally. Install Node.js as well only if you plan to run the optional Pyright
quality gate.

## Start Here

1. Product overview: [`../README.md`](../README.md)
2. Setup and install tiers: [`SETUP.md`](SETUP.md)
3. Command overview: [`CLI_REFERENCE.md`](CLI_REFERENCE.md)
4. Surface boundaries and entrypoints: [`SURFACES.md`](SURFACES.md)
5. Pipeline and runtime orchestration: [`PIPELINE.md`](PIPELINE.md)
6. Accuracy, trust, and limitations: [`ACCURACY.md`](ACCURACY.md), [`ACCURACY_CONTRACT.md`](ACCURACY_CONTRACT.md)

## Find Docs by Task

| I want to... | Go to |
|---|---|
| Install and run RepoGraph | [`SETUP.md`](SETUP.md) |
| Learn all CLI commands and flags | [`CLI_REFERENCE.md`](CLI_REFERENCE.md) |
| Understand API vs CLI vs MCP | [`SURFACES.md`](SURFACES.md) |
| Understand pipeline internals and runtime orchestration | [`PIPELINE.md`](PIPELINE.md) |
| Understand config ownership and `.repograph` artifact boundaries | [`CONFIG_HYGIENE.md`](CONFIG_HYGIENE.md) |
| Understand confidence, runtime evidence, and limitations | [`ACCURACY.md`](ACCURACY.md), [`ACCURACY_CONTRACT.md`](ACCURACY_CONTRACT.md) |
| Write or extend plugins | [`plugins/AUTHORING.md`](plugins/AUTHORING.md), [`plugins/DISCOVERY.md`](plugins/DISCOVERY.md) |
| Understand plugin hooks vs optional experimental phases | [`architecture/PLUGIN_PHASES_AND_HOOKS.md`](architecture/PLUGIN_PHASES_AND_HOOKS.md) |
| Use RepoGraph for agent workflows | [`AGENT_USAGE.md`](AGENT_USAGE.md) |
| Understand test layout and markers | [`../tests/README.md`](../tests/README.md) |

## Contributor Shortcuts

- Contribution process: [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- Test guide: [`../tests/README.md`](../tests/README.md)
- Plugin package overview: [`../repograph/plugins/README.md`](../repograph/plugins/README.md)

## Historical Docs

Older refactor notes are archived here:

- [`archive/repo_history/`](archive/repo_history/)
- [`refactor/INDEX.md`](refactor/INDEX.md)

Archived material is historical context only. Treat the active docs above, current CLI help, and current runtime/status surfaces as the source of truth for present behavior.
