"""Unit tests for dead-code classification — covers F-02 and F-03.

F-02: Functions in utility/helper modules should be classified
      ``possibly_dead`` (not ``definitely_dead``) when they have zero callers.

F-03: JS class methods in HTML-<script src>-loaded files, and symbols
      referenced in HTML event handlers, must be exempt from dead-code
      detection entirely.
"""
from __future__ import annotations

import pytest

from repograph.plugins.static_analyzers.dead_code.plugin import (
    _CallerInfo,
    _classify_tier,
    class_method_in_html_script_loaded_file,
    extract_html_reachable_symbols,
)
from repograph.utils.fs import _is_utility_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_info() -> _CallerInfo:
    """CallerInfo with no callers at all."""
    return _CallerInfo()


def _test_only_info() -> _CallerInfo:
    info = _CallerInfo()
    info.total = 2
    info.from_test = 2
    return info


def _fuzzy_only_info() -> _CallerInfo:
    info = _CallerInfo()
    info.total = 1
    info.fuzzy = 1
    return info


def _fn(file_path: str = "src/app/service.py", *, is_exported: bool = False) -> dict:
    return {"file_path": file_path, "is_exported": is_exported, "name": "helper"}


# ---------------------------------------------------------------------------
# F-02: _is_utility_file detection
# ---------------------------------------------------------------------------

class TestF02IsUtilityFile:
    """_is_utility_file must recognise standard utility/helper directories."""

    @pytest.mark.parametrize("path", [
        "src/utils/timeutil.py",
        "src/utils/mathutil.py",
        "src/utils/idgen.py",
        "utils/logging_setup.py",
        "lib/common/format.py",
        "helpers/string_utils.py",
        "shared/constants.py",
        "common/base.py",
        "contrib/middleware.py",
        "support/retry.py",
        "src/app/utils/misc.py",
    ])
    def test_utility_paths_detected(self, path: str) -> None:
        assert _is_utility_file(path), f"{path!r} should be detected as utility"

    @pytest.mark.parametrize("path", [
        "src/bots/champion_bot.py",
        "src/advisor/engine.py",
        "src/broker/paper_broker.py",
        "src/market/market_data_service.py",
        "src/storage/writer.py",
        "src/risk/risk_engine.py",
    ])
    def test_application_paths_not_utility(self, path: str) -> None:
        assert not _is_utility_file(path), f"{path!r} wrongly flagged as utility"


# ---------------------------------------------------------------------------
# F-02: _classify_tier — utility module functions → possibly_dead
# ---------------------------------------------------------------------------

class TestF02ClassifyTierUtility:
    """Utility-module functions with zero callers must be possibly_dead."""

    @pytest.mark.parametrize("file_path", [
        "src/utils/timeutil.py",
        "src/utils/mathutil.py",
        "utils/logging_setup.py",
        "lib/helpers/format.py",
    ])
    def test_utility_zero_callers_is_possibly_dead(self, file_path: str) -> None:
        fn = _fn(file_path)
        tier, reason = _classify_tier(fn, _zero_info())
        assert tier == "possibly_dead", (
            f"{file_path!r}: expected possibly_dead, got {tier}"
        )
        assert reason == "utility_module_uncalled"

    def test_utility_zero_callers_not_definitely_dead(self) -> None:
        fn = _fn("src/utils/timeutil.py")
        tier, _ = _classify_tier(fn, _zero_info())
        assert tier != "definitely_dead"

    def test_non_utility_zero_callers_is_definitely_dead(self) -> None:
        """Application code with zero callers stays definitely_dead."""
        fn = _fn("src/bots/champion_bot.py")
        tier, reason = _classify_tier(fn, _zero_info())
        assert tier == "definitely_dead"
        assert reason == "zero_callers"

    def test_exported_non_utility_zero_callers_is_possibly_dead(self) -> None:
        """Existing behaviour: exported non-utility fn is possibly_dead (not definitely)."""
        fn = _fn("src/bots/champion_bot.py", is_exported=True)
        tier, reason = _classify_tier(fn, _zero_info())
        assert tier == "possibly_dead"
        assert reason == "exported_but_uncalled"

    def test_test_only_callers_is_probably_dead_regardless_of_path(self) -> None:
        """Test-only callers → probably_dead even for utility files."""
        fn = _fn("src/utils/timeutil.py")
        tier, reason = _classify_tier(fn, _test_only_info())
        assert tier == "probably_dead"
        assert reason == "only_test_callers"

    def test_fuzzy_only_callers_is_probably_dead(self) -> None:
        fn = _fn("src/utils/timeutil.py")
        tier, reason = _classify_tier(fn, _fuzzy_only_info())
        assert tier == "probably_dead"
        assert reason == "only_fuzzy_callers"


# ---------------------------------------------------------------------------
# F-03: class_method_in_html_script_loaded_file
# ---------------------------------------------------------------------------

SCRIPT_FILES = frozenset({
    "src/ui/static/chart.js",
    "src/ui/static/app.js",
    "src/ui/static/manual.js",
})


class TestF03ClassMethodHtmlScriptLoaded:
    """Class methods in HTML-script-loaded files must be exempt from dead code."""

    @pytest.mark.parametrize("qualified_name,expected", [
        ("ChartManager.init",         True),
        ("ChartManager.setEmas",      True),
        ("ChartManager.scrollToLive", True),
        ("ChartManager.constructor",  True),
        # Module-scope function (no dot) — not covered by this exemption
        ("initChart",                 False),
        ("renderAll",                 False),
    ])
    def test_class_methods_in_script_loaded_file(
        self, qualified_name: str, expected: bool
    ) -> None:
        fn = {
            "file_path": "src/ui/static/chart.js",
            "qualified_name": qualified_name,
            "name": qualified_name.split(".")[-1],
        }
        result = class_method_in_html_script_loaded_file(fn, set(SCRIPT_FILES))
        assert result == expected, (
            f"{qualified_name!r}: expected {expected}, got {result}"
        )

    def test_file_not_in_script_files_returns_false(self) -> None:
        fn = {
            "file_path": "src/bots/champion_bot.py",
            "qualified_name": "ChampionBot.on_tick",
            "name": "on_tick",
        }
        assert class_method_in_html_script_loaded_file(fn, set(SCRIPT_FILES)) is False

    def test_empty_script_files_returns_false(self) -> None:
        fn = {
            "file_path": "src/ui/static/chart.js",
            "qualified_name": "ChartManager.init",
            "name": "init",
        }
        assert class_method_in_html_script_loaded_file(fn, set()) is False


# ---------------------------------------------------------------------------
# F-03: extract_html_reachable_symbols
# ---------------------------------------------------------------------------

class TestF03ExtractHtmlReachableSymbols:
    """HTML event handler scanner must extract all referenced symbol names."""

    def test_inline_onclick(self) -> None:
        html = '<button onclick="resetChart()">Reset</button>'
        syms = extract_html_reachable_symbols(html)
        assert "resetChart" in syms

    def test_inline_onclick_method_call(self) -> None:
        html = '<button onclick="ChartManager.init()">Init</button>'
        syms = extract_html_reachable_symbols(html)
        # Both the bare name and the dotted form should be present
        assert "init" in syms or "ChartManager.init" in syms

    def test_add_event_listener(self) -> None:
        html = '<script>btn.addEventListener("click", loadData);</script>'
        syms = extract_html_reachable_symbols(html)
        assert "loadData" in syms

    def test_multiple_handlers(self) -> None:
        html = """
        <div onclick="openModal()"></div>
        <form onsubmit="validateForm()"></form>
        <input onchange="updatePreview()">
        """
        syms = extract_html_reachable_symbols(html)
        assert "openModal" in syms
        assert "validateForm" in syms
        assert "updatePreview" in syms

    def test_empty_html_returns_empty_set(self) -> None:
        assert extract_html_reachable_symbols("") == set()

    def test_html_without_handlers_returns_empty_set(self) -> None:
        html = "<html><body><h1>Hello</h1></body></html>"
        assert extract_html_reachable_symbols(html) == set()

    def test_no_false_positives_from_regular_attributes(self) -> None:
        html = '<div class="my-class" id="main" data-value="123">text</div>'
        syms = extract_html_reachable_symbols(html)
        # class, id, data-value should not be extracted as callable symbols
        assert "my-class" not in syms
        assert "main" not in syms
