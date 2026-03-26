"""Fixture: helper functions called at module level."""


def get_default_config_path() -> str:
    """Called at module level in config.py — must NOT be dead."""
    return "/etc/app/config.yaml"


def get_repo_root() -> str:
    """Also called at module level."""
    return "/home/user/project"


def truly_dead() -> str:
    """Never called anywhere — genuinely dead."""
    return "dead"
