"""Unit tests for _detect_io_tags() — false-positive prevention and true-positive coverage."""
from __future__ import annotations

import pytest
from repograph.plugins.exporters.pathway_contexts.formatter import _detect_io_tags


class TestHTTPFalsePositives:
    """dict.get() / class.get() must never trigger the HTTP tag."""

    def test_cfg_dict_get_is_not_http(self):
        src = 'arm = cfg.get("arm_live_trading")'
        assert "HTTP" not in _detect_io_tags(src), \
            "cfg.get() incorrectly tagged as HTTP"

    def test_plain_dict_get_is_not_http(self):
        src = 'value = some_dict.get("key", default)'
        assert "HTTP" not in _detect_io_tags(src), \
            "dict.get() incorrectly tagged as HTTP"

    def test_flagstore_get_bool_is_not_http(self):
        src = 'return bool(self._store.get(key, False))'
        assert "HTTP" not in _detect_io_tags(src), \
            "FlagStore._store.get() incorrectly tagged as HTTP"

    def test_nested_dict_get_is_not_http(self):
        src = 'trading = cfg.get("trading", {}).get("mode", "paper")'
        assert "HTTP" not in _detect_io_tags(src), \
            "Chained dict.get() incorrectly tagged as HTTP"

    def test_settings_get_is_not_http(self):
        src = 'timeout = settings.get("timeout", 30)'
        assert "HTTP" not in _detect_io_tags(src), \
            "settings.get() incorrectly tagged as HTTP"

    def test_config_get_is_not_http(self):
        src = 'val = config.get("retry_count")'
        assert "HTTP" not in _detect_io_tags(src), \
            "config.get() incorrectly tagged as HTTP"

    def test_env_get_is_not_http(self):
        src = 'key = os.environ.get("API_KEY", "")'
        # os.environ.get is not an HTTP call (it's an env var read)
        assert "HTTP" not in _detect_io_tags(src), \
            "os.environ.get() incorrectly tagged as HTTP"


class TestHTTPTruePositives:
    """Real HTTP calls must still be detected."""

    def test_requests_get_triggers_http(self):
        src = 'resp = requests.get("https://api.example.com/v1/orders")'
        assert "HTTP" in _detect_io_tags(src), \
            "requests.get() not detected as HTTP"

    def test_requests_post_triggers_http(self):
        src = 'r = requests.post(url, json=payload, headers=headers)'
        assert "HTTP" in _detect_io_tags(src), \
            "requests.post() not detected as HTTP"

    def test_httpx_triggers_http(self):
        src = 'result = await httpx.get(endpoint)'
        assert "HTTP" in _detect_io_tags(src), \
            "httpx.get() not detected as HTTP"

    def test_aiohttp_triggers_http(self):
        src = 'async with aiohttp.ClientSession() as session:'
        assert "HTTP" in _detect_io_tags(src), \
            "aiohttp usage not detected as HTTP"

    def test_session_post_triggers_http(self):
        src = 'result = await self._session.post(url, data=payload)'
        assert "HTTP" in _detect_io_tags(src), \
            "self._session.post() not detected as HTTP"

    def test_client_get_triggers_http(self):
        src = 'resp = self.client.get("/api/health")'
        assert "HTTP" in _detect_io_tags(src), \
            "self.client.get() not detected as HTTP"

    def test_self_rest_post_triggers_http(self):
        src = 'ack = await self._rest.post("/order", body=body)'
        assert "HTTP" in _detect_io_tags(src), \
            "self._rest.post() not detected as HTTP"

    def test_response_get_triggers_http(self):
        src = 'data = response.get("/items")'
        assert "HTTP" in _detect_io_tags(src), \
            "response.get() not detected as HTTP"


class TestOtherIoTagsUnaffected:
    """Ensure other IO tags still work correctly after the HTTP regex change."""

    def test_await_still_detected_as_async(self):
        src = 'result = await some_coroutine()'
        assert "async" in _detect_io_tags(src)

    def test_file_open_still_detected(self):
        src = 'with open("config.yaml") as f: data = f.read()'
        assert "file I/O" in _detect_io_tags(src)

    def test_db_execute_still_detected(self):
        src = 'await conn.execute("SELECT * FROM trades")'
        assert "database" in _detect_io_tags(src)

    def test_websocket_still_detected(self):
        src = 'await ws.send(json.dumps(msg))'
        assert "websocket" in _detect_io_tags(src)

    def test_empty_source_returns_no_tags(self):
        assert _detect_io_tags("") == []

    def test_pure_business_logic_returns_no_tags(self):
        src = """
def compute_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    edge = win_rate * avg_win - (1 - win_rate) * avg_loss
    variance = win_rate * avg_win**2 + (1 - win_rate) * avg_loss**2
    return edge / variance if variance else 0.0
"""
        assert _detect_io_tags(src) == [], \
            f"Pure math function incorrectly tagged: {_detect_io_tags(src)}"
