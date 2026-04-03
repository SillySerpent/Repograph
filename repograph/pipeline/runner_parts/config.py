"""Runner configuration and validation contracts.

This module owns the pipeline-runner configuration shape so orchestration code
does not mix sequencing logic with schema validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repograph.runtime.session import (
    RuntimeAttachApproval,
    RuntimeAttachDecision,
    RuntimeAttachPolicy,
)
from repograph.settings import (
    DEFAULT_CONTEXT_TOKENS as _DEFAULT_CONTEXT_TOKENS,
    DEFAULT_GIT_DAYS as _DEFAULT_GIT_DAYS,
    DEFAULT_MIN_COMMUNITY_SIZE as _DEFAULT_MIN_COMMUNITY_SIZE,
    DEFAULT_MODULE_EXPANSION_THRESHOLD as _DEFAULT_MODULE_EXPANSION_THRESHOLD,
)

__all__ = ["RunConfig", "validate_run_config_paths"]


def validate_run_config_paths(config: "RunConfig") -> None:
    """Fail fast if the runner is called with invalid path-like values."""
    if not isinstance(config.repo_root, str):
        raise ValueError(
            "RunConfig.repo_root must be a str path, "
            f"got {type(config.repo_root).__name__}"
        )
    if not isinstance(config.repograph_dir, str):
        raise ValueError(
            "RunConfig.repograph_dir must be a str path, "
            f"got {type(config.repograph_dir).__name__}"
        )
    if not Path(config.repo_root).is_dir():
        raise ValueError(
            f"RunConfig.repo_root must be an existing directory: {config.repo_root!r}"
        )


@dataclass
class RunConfig:
    """Validated runner inputs shared by full, incremental, and runtime flows."""

    repo_root: str
    repograph_dir: str
    include_git: bool = True
    include_embeddings: bool = False
    full: bool = False
    max_context_tokens: int = _DEFAULT_CONTEXT_TOKENS
    duplicates_same_language_only: bool = True
    strict: bool = False
    continue_on_error: bool = True
    min_community_size: int = _DEFAULT_MIN_COMMUNITY_SIZE
    git_days: int = _DEFAULT_GIT_DAYS
    module_expansion_threshold: int = _DEFAULT_MODULE_EXPANSION_THRESHOLD
    include_tests_config_registry: bool = False
    experimental_phase_plugins: bool = False
    allow_dynamic_inputs: bool = True
    runtime_attach_policy: RuntimeAttachPolicy = "prompt"
    runtime_attach_approval_resolver: (
        Callable[[RuntimeAttachDecision], RuntimeAttachApproval] | None
    ) = None

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.min_community_size < 0:
            errors.append(f"min_community_size must be >= 0, got {self.min_community_size}")
        if self.git_days < 0:
            errors.append(f"git_days must be >= 0, got {self.git_days}")
        if self.module_expansion_threshold < 1:
            errors.append(
                f"module_expansion_threshold must be >= 1, got {self.module_expansion_threshold}"
            )
        if self.max_context_tokens < 100:
            errors.append(f"max_context_tokens must be >= 100, got {self.max_context_tokens}")
        if self.runtime_attach_policy not in {"prompt", "always", "never"}:
            errors.append(
                "runtime_attach_policy must be one of "
                f"'prompt', 'always', or 'never', got {self.runtime_attach_policy!r}"
            )
        if not Path(self.repo_root).is_dir():
            errors.append(f"repo_root does not exist or is not a directory: {self.repo_root!r}")
        if errors:
            raise ValueError("Invalid RunConfig:\n" + "\n".join(f"  - {e}" for e in errors))
