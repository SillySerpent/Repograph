# Canonical entry-point scoring helpers owned by the pathways plugin.
"""Entry point scorer — computes pathway entry point scores.

This is the single authoritative implementation of the scoring formula.
Both the pipeline phase (p10_processes) and the assembler import from here.

Test functions always receive a score of exactly 0.0 and are excluded from
all production entry-point lists.  This is enforced here — the single source
of truth — so callers do not need their own guards.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from repograph.utils.path_classifier import SCRIPT_PATH_RE, is_test_path

_ROUTE_DEC = re.compile(r"^(app|router|blueprint)\.(get|post|put|delete|patch|route)", re.I)
_TASK_DEC = re.compile(r"^(click\.command|celery\.task|schedule)", re.I)
_HANDLE_NAME = re.compile(r"^(handle|on_|controller|view|route)", re.I)
_ROUTE_FILE = re.compile(r"/(routes|handlers|views|api|endpoints|controllers)/", re.I)
# Non-production script paths — delegated to path_classifier.SCRIPT_PATH_RE
_SCRIPT_PATH = SCRIPT_PATH_RE
_MAIN_MULT = 5.0
_ROUTE_DEC_MULT = 4.0
_TASK_DEC_MULT = 3.5
_ROUTE_PATH_MULT = 3.0
_EXPORT_MULT = 2.0
_HANDLE_MULT = 1.5
_ABC_IMPL_MULT = 2.5   # boost for concrete implementations of abstract methods (F-04)
_SCRIPT_DEMOTE = 0.1   # 10× penalty for script/diagnostic paths
# Single-leading-underscore helpers (_foo) are internal; demote vs public entry points.
_PRIVATE_NAME_DEMOTE = 0.35
_MIN_SCORE = 0.5


@dataclass
class ScoreBreakdown:
    """Human-readable decomposition of an entry-point score.

    Returned by ``score_function_verbose()`` so developers and AI agents can
    understand *why* a function scored the way it did rather than treating the
    number as an opaque black box.
    """
    final_score: float
    base_score: float
    callees_count: int
    callers_count: int
    multipliers: list[tuple[str, float]] = field(default_factory=list)
    zeroed_reason: str = ""   # non-empty when score is forced to 0.0

    def explain(self) -> str:
        """Return a one-line human-readable explanation of the score."""
        if self.zeroed_reason:
            return f"0.0 ({self.zeroed_reason})"
        parts = [
            f"base({self.base_score:.2f} = fan_out/(log1p(callers)+1)+7*log1p(callers), "
            f"callees={self.callees_count}, callers={self.callers_count})",
        ]
        for label, mult in self.multipliers:
            parts.append(f"× {label}({mult})")
        parts.append(f"= {self.final_score:.1f}")
        return "  ".join(parts)



def score_function_verbose(
    fn: dict,
    callees_count: int = 0,
    callers_count: int = 0,
    abc_implementor: bool = False,
) -> ScoreBreakdown:
    """Return a full ScoreBreakdown explaining how the entry-point score was computed.

    Use this for the ``--verbose`` flag on ``repograph summary`` and
    ``repograph node`` to make scores interpretable rather than opaque numbers.

    Args:
        fn: function record dict (as returned by GraphStore)
        callees_count: how many functions this function calls
        callers_count: how many functions call this function
        abc_implementor: True when the function implements an abstract method.
    """
    if fn.get("is_dead"):
        return ScoreBreakdown(0.0, 0.0, callees_count, callers_count,
                              zeroed_reason="is_dead=True")

    # Synthetic __module__ sentinels exist for dead-code call attribution only.
    if fn.get("is_module_caller"):
        return ScoreBreakdown(0.0, 0.0, callees_count, callers_count,
                              zeroed_reason="is_module_caller_sentinel")

    file_path: str = fn.get("file_path", "") or ""
    if is_test_path(file_path) or fn.get("is_test"):
        return ScoreBreakdown(0.0, 0.0, callees_count, callers_count,
                              zeroed_reason="test_function")

    name: str = fn.get("name", "") or ""
    decorators: list[str] = fn.get("decorators") or []
    is_exported: bool = fn.get("is_exported", False)

    # Callee fan-out drives the base; caller penalty is log-damped so widely
    # called orchestrators (api, cli, tests) are not zeroed.
    fan_out = float(callees_count)
    caller_dampen = math.log1p(callers_count)
    base = fan_out / (caller_dampen + 1.0)
    # Many distinct callers strongly indicates a dispatch/orchestration entry
    # point; additive term prevents single-caller pipeline phases from dominating.
    base += 7.0 * math.log1p(callers_count)
    score = base
    applied: list[tuple[str, float]] = []

    if callers_count == 0 and not fn.get("is_module_caller"):
        score *= 2.0
        applied.append(("zero_callers_root", 2.0))

    if is_exported:
        score *= _EXPORT_MULT
        applied.append(("exported", _EXPORT_MULT))
    if _HANDLE_NAME.match(name):
        score *= _HANDLE_MULT
        applied.append(("handle_name", _HANDLE_MULT))
    if _ROUTE_FILE.search(file_path):
        score *= _ROUTE_PATH_MULT
        applied.append(("route_file", _ROUTE_PATH_MULT))
    if name == "__main__" or file_path.endswith("__main__.py"):
        score *= _MAIN_MULT
        applied.append(("__main__", _MAIN_MULT))

    for dec in decorators:
        if _ROUTE_DEC.match(dec):
            score *= _ROUTE_DEC_MULT
            applied.append((f"route_dec({dec})", _ROUTE_DEC_MULT))
            break
        if _TASK_DEC.match(dec):
            score *= _TASK_DEC_MULT
            applied.append((f"task_dec({dec})", _TASK_DEC_MULT))
            break

    if abc_implementor:
        score *= _ABC_IMPL_MULT
        applied.append(("abc_impl", _ABC_IMPL_MULT))

    if name.startswith("_") and not name.startswith("__"):
        score *= _PRIVATE_NAME_DEMOTE
        applied.append(("private_name_demote", _PRIVATE_NAME_DEMOTE))

    if _SCRIPT_PATH.search(file_path):
        score *= _SCRIPT_DEMOTE
        applied.append(("script_demote", _SCRIPT_DEMOTE))

    final = score if score > _MIN_SCORE else 0.0
    return ScoreBreakdown(
        final_score=final,
        base_score=round(base, 4),
        callees_count=callees_count,
        callers_count=callers_count,
        multipliers=applied,
        zeroed_reason="" if final > 0 else f"below_min({score:.3f}<{_MIN_SCORE})",
    )


def score_function(
    fn: dict,
    callees_count: int = 0,
    callers_count: int = 0,
    abc_implementor: bool = False,
) -> float:
    """Backward-compatible score-only wrapper around score_function_verbose()."""
    return score_function_verbose(
        fn,
        callees_count=callees_count,
        callers_count=callers_count,
        abc_implementor=abc_implementor,
    ).final_score
