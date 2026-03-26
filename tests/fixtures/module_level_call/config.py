"""Fixture: calls helpers at module level (outside any function)."""
from helpers import get_default_config_path, get_repo_root

# These are module-level calls — the callee must not be flagged dead.
CONFIG_PATH = get_default_config_path()
REPO_ROOT = get_repo_root()


def use_config() -> str:
    return CONFIG_PATH
