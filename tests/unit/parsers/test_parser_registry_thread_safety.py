from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from repograph.plugins.lifecycle import reset_hook_scheduler
from repograph.plugins.parsers import registry as parser_registry


def _reset_parser_registry_state() -> None:
    reset_hook_scheduler()
    parser_registry._DEFAULTS_REGISTERED = False
    parser_registry._LANGUAGE_TO_PLUGIN.clear()
    parser_registry._PARSER_REGISTRY._plugins.clear()
    parser_registry._PARSER_REGISTRY._aliases.clear()


def test_ensure_default_parsers_registered_concurrent_once() -> None:
    _reset_parser_registry_state()
    errors: list[Exception] = []

    def worker() -> None:
        try:
            parser_registry.ensure_default_parsers_registered()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker) for _ in range(24)]
        for future in futures:
            future.result(timeout=10)

    assert not errors
    ids = sorted(parser_registry.get_registry().ids())
    assert ids == sorted(set(ids))
    assert ids, "Expected parser plugins to be registered"


def test_get_parser_plugin_concurrent_does_not_double_register() -> None:
    _reset_parser_registry_state()
    errors: list[Exception] = []
    got_plugins: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            plugin = parser_registry.get_parser_plugin("python")
            with lock:
                got_plugins.append(plugin.plugin_id() if plugin else "")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker) for _ in range(24)]
        for future in futures:
            future.result(timeout=10)

    assert not errors
    assert all(pid == "parser.python" for pid in got_plugins)
    assert sorted(parser_registry.get_registry().ids()) == sorted(
        set(parser_registry.get_registry().ids())
    )


def test_supported_languages_concurrent_is_deterministic() -> None:
    _reset_parser_registry_state()
    errors: list[Exception] = []
    seen: list[tuple[str, ...]] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            langs = tuple(parser_registry.supported_languages())
            with lock:
                seen.append(langs)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker) for _ in range(24)]
        for future in futures:
            future.result(timeout=10)

    assert not errors
    assert seen
    baseline = seen[0]
    assert all(item == baseline for item in seen)
