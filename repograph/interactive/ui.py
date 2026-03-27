"""Terminal colour helpers for the interactive menu — no third-party deps."""
from __future__ import annotations

import textwrap

# Returned by _choose / _choose_with_details when allow_back is True:
#   empty Enter  → CHOOSE_BACK   (go up one level in the UI)
#   "0"          → CHOOSE_EXIT  (quit the entire interactive session)
CHOOSE_BACK = "__menu_back__"
CHOOSE_EXIT = "__menu_exit__"


class MenuExit(Exception):
    """User chose full exit (0) from a nested screen; caught by main() for a clean shutdown."""

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_RESET = "\033[0m"
_BLUE = "\033[94m"


def _b(s: str) -> str:
    return f"{_BOLD}{s}{_RESET}"


def _c(s: str) -> str:
    return f"{_CYAN}{s}{_RESET}"


def _g(s: str) -> str:
    return f"{_GREEN}{s}{_RESET}"


def _y(s: str) -> str:
    return f"{_YELLOW}{s}{_RESET}"


def _r(s: str) -> str:
    return f"{_RED}{s}{_RESET}"


def _d(s: str) -> str:
    return f"{_DIM}{s}{_RESET}"


def _hr(char: str = "─", width: int = 60) -> None:
    print(_d(char * width))


def _header(title: str) -> None:
    print()
    _hr("═")
    print(f"  {_b(_c(title))}")
    _hr("═")
    print()


def _section(title: str) -> None:
    print()
    _hr()
    print(f"  {_b(title)}")
    _hr()


def _ask(prompt: str, default: str = "", *, help_lines: list[str] | None = None) -> str:
    """Prompt for input with an optional default.

    *help_lines* — short hints printed **before** the prompt (e.g. how to answer).
    """
    if help_lines:
        print()
        for line in help_lines:
            print(f"  {_d(line)}")
        print()
    hint = f"  {_d(f'[{default}]')} " if default else "  "
    try:
        val = input(f"  {_y('▸')} {prompt}{hint}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val or default


def _table(headers: list[str], rows: list[list[str]], col_widths: list[int] | None = None) -> None:
    """Print a simple fixed-width table using spaces (ANSI-safe)."""
    if not rows:
        print(f"  {_d('(no rows)')}")
        return
    n = len(headers)
    if col_widths is None:
        col_widths = []
        for i in range(n):
            w = len(headers[i])
            for r in rows:
                if i < len(r):
                    w = max(w, len(r[i]))
            col_widths.append(min(w, 72))
    # header
    head_parts = [f"{headers[i]:<{col_widths[i]}}" for i in range(n)]
    print("  " + _b(" ".join(head_parts)))
    print("  " + _d(" ".join("─" * col_widths[i] for i in range(n))))
    for r in rows:
        cells = []
        for i in range(n):
            cell = r[i] if i < len(r) else ""
            if len(cell) > col_widths[i]:
                cell = cell[: col_widths[i] - 1] + "…"
            cells.append(f"{cell:<{col_widths[i]}}")
        print("  " + " ".join(cells))
    print()


def _choose(
    prompt: str,
    options: list[tuple[str, str]],
    allow_back: bool = True,
    *,
    foot: str | None = None,
) -> str:
    """
    Display a numbered menu and return the key of the chosen option.

    When *allow_back* is True: **Enter** (empty) → :data:`CHOOSE_BACK`, **0** → :data:`CHOOSE_EXIT`.
    """
    print(f"\n  {_b(prompt)}\n")
    for i, (key, label) in enumerate(options, 1):
        print(f"    {_c(str(i)):>6}  {label}")
    if allow_back:
        print(f"    {_d('(Enter)  ← Back one level')}")
        print(f"    {_c('0'):>6}  {_d('Exit  — quit RepoGraph (end this session)')}")
    if foot:
        print(f"\n  {_d(foot)}")
    print()

    n = len(options)
    while True:
        try:
            raw = input(
                f"  {_y('▸')} 1–{n}, Enter=back, 0=exit — "
            ).strip()
        except EOFError:
            print()
            return CHOOSE_EXIT
        except KeyboardInterrupt:
            print()
            raise

        if allow_back and raw == "":
            return CHOOSE_BACK
        if raw == "0":
            return CHOOSE_EXIT
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= n:
                return options[idx - 1][0]
        print(
            f"  {_r(f'Type 1–{n}, or 0 to exit' + (', or Enter to go back' if allow_back else '') + '.')}"
        )


def _choose_with_details(
    prompt: str,
    options: list[tuple[str, str, str | None]],
    allow_back: bool = True,
    *,
    intro: str | None = None,
    foot: str | None = None,
) -> str:
    """Numbered menu with an optional dim explanation line under each primary label.

    *options* — (return_key, primary_label, optional_plain_language_detail).
    """
    prefix_cols = 12  # align wrapped detail under primary text
    wrap_w = 68

    print(f"\n  {_b(prompt)}\n")
    if intro:
        for line in textwrap.wrap(intro, width=76):
            print(f"  {_d(line)}")
        print()

    for i, (key, primary, detail) in enumerate(options, 1):
        print(f"    {_c(str(i)):>6}  {primary}")
        if detail:
            for line in textwrap.wrap(detail, width=wrap_w):
                print(f"{' ' * prefix_cols}{_d(line)}")
    if allow_back:
        print(f"    {_d('(Enter)  ← Back one level')}")
        print(f"    {_c('0'):>6}  {_d('Exit  — quit RepoGraph (end this session)')}")
    if foot:
        print()
        for line in textwrap.wrap(foot, width=76):
            print(f"  {_d(line)}")
    print()

    n = len(options)
    while True:
        try:
            raw = input(
                f"  {_y('▸')} 1–{n}, Enter=back, 0=exit — "
            ).strip()
        except EOFError:
            print()
            return CHOOSE_EXIT
        except KeyboardInterrupt:
            print()
            raise

        if allow_back and raw == "":
            return CHOOSE_BACK
        if raw == "0":
            return CHOOSE_EXIT
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= n:
                return options[idx - 1][0]
        print(
            f"  {_r(f'Type 1–{n}, or 0 to exit' + (', or Enter to go back' if allow_back else '') + '.')}"
        )


def _confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"  {_y('▸')} {prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not raw:
        return default
    return raw in ("y", "yes")


def _print_dict(d: dict, indent: int = 2) -> None:
    pad = " " * indent
    for k, v in d.items():
        if isinstance(v, list):
            print(f"{pad}{_b(str(k))}: [{len(v)} items]")
            for item in v[:10]:
                print(f"{pad}  {_d('·')} {item}")
            if len(v) > 10:
                print(f"{pad}  {_d(f'… and {len(v)-10} more')}")
        elif isinstance(v, dict):
            print(f"{pad}{_b(str(k))}:")
            _print_dict(v, indent + 4)
        else:
            print(f"{pad}{_b(str(k))}: {v}")
