"""Fixture: dict.get() and class .get() that must NOT trigger the HTTP IO tag."""


class FlagStore:
    """Simple in-memory flag store — .get() is NOT an HTTP call."""
    def __init__(self):
        self._store: dict = {}

    def get(self, key: str):
        return self._store.get(key)

    def get_bool(self, key: str) -> bool:
        return bool(self._store.get(key, False))


def use_cfg_get(cfg: dict) -> str | None:
    """Reads from a plain dict — cfg.get() is NOT an HTTP call."""
    arm = cfg.get("arm_live_trading")
    trading = cfg.get("trading", {})
    return str(arm) if arm else trading.get("mode", "paper")


def use_flagstore_get(fs: FlagStore) -> bool:
    """Calls FlagStore.get() — NOT an HTTP call."""
    return fs.get_bool("trading_enabled")


def real_http_call(session, url: str) -> dict:
    """This IS an HTTP call — session.get() should trigger the HTTP tag."""
    resp = session.get(url, timeout=10)
    return resp.json()


def real_requests_call(endpoint: str) -> dict:
    """Direct requests usage — must trigger HTTP tag."""
    import requests
    return requests.get(endpoint).json()


def real_httpx_call(client, path: str):
    """httpx client — must trigger HTTP tag."""
    return client.post(path, json={"key": "value"})
