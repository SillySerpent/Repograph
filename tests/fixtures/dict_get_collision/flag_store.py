"""Fixture: unrelated ``.get`` on a class vs ``dict.get`` on a parameter."""


class FlagStore:
    def get(self, key: str) -> str:
        return key


def use_cfg_get(cfg: dict) -> str | None:
    return cfg.get("x")


def use_flag_store(fs: FlagStore) -> str:
    return fs.get("y")
