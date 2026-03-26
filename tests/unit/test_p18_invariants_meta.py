"""Tests for Phase 18 meta-doc filtering (RG-05)."""
from repograph.plugins.exporters.invariants.plugin import (
    _is_meta_invariant_text,
    _scan_docstring,
)


def test_drops_extractor_meta_phrases() -> None:
    assert _is_meta_invariant_text(
        "invariant_type is set from the pattern label extracted by Phase 18"
    )


def test_keeps_short_imperative() -> None:
    assert not _is_meta_invariant_text("Never raises")


def test_scan_docstring_skips_meta_doc() -> None:
    doc = '''Module doc.

    The invariant_text field holds the constraint string. Invariant_type
    labels are extracted by Phase 18 from docstrings.
    '''
    out = _scan_docstring(doc)
    assert not any("invariant_type" in t.lower() for _, t in out)


def test_scan_keeps_real_never() -> None:
    doc = "NEVER mutates shared state across async boundaries."
    out = _scan_docstring(doc)
    assert any("NEVER" in t for _, t in out)


def test_skips_typer_option_help_prose() -> None:
    assert _is_meta_invariant_text(
        "Same as typer.Option default: current working directory for the sync command."
    )


def test_skips_double_dash_flag_lines() -> None:
    assert _is_meta_invariant_text(
        "  --verbose / -v  Increase log verbosity and show diagnostic output."
    )


def test_skips_argparse_style() -> None:
    assert _is_meta_invariant_text(
        "Passed to argparse add_argument as the metavar string for the repo path."
    )


def test_scan_skips_cli_docstring_noise() -> None:
    doc = """
    Run the pipeline.

    Repository root path.  --verbose  Also enable debug logging.
    """
    out = _scan_docstring(doc)
    assert not any("--verbose" in t for _, t in out)
