"""Section-rendering utilities for TUI category tables."""

from __future__ import annotations

from typing import Any, Callable

from rich.text import Text

from toggl.config import CATEGORY_REGISTRY
from toggl.formatters.cells import _fmt_project_tree, _fmt_tree_cells, fmt_pts_rich


# ──────────────────────────────────────────────
# SECTION HEADER COLORS
# ──────────────────────────────────────────────
SECTION_COLORS = {
    "POSITIVE": "#4ADE80",
    "NEGATIVE": "#FF6B6B",
    "UNSCORED": "#8d98a7",
    "LOGGED POSITIVE": "#2DD4BF",
    "LOGGED NEGATIVE": "#C084FC",
}


def _fmt_section_header(label: str) -> Text:
    """Return a Rich Text section-divider row label with its fixed semantic color."""
    key = label
    if key.startswith("\u2022 "):
        key = key[2:]
    elif key.startswith("["):
        key = key[1:-1] if key.endswith("]") else key[1:]
    color = SECTION_COLORS.get(key, "")
    if color:
        return Text(label, style=f"bold {color}")
    return Text(label, style="bold")


# ──────────────────────────────────────────────
# TREE-RENDERED CATEGORY GROUPS
# ──────────────────────────────────────────────


def _render_category_section(
    rows: list[tuple[str, float | None, float | None, float | None]],
    fmt_name_fn: Callable[[str, float | None], Text],
    fmt_cells_fn: Callable[..., Any],
    section_color: str = "",
) -> list[Any]:
    """Render scored rows as a flat list with tree characters.

    No parent rows, no grouping by category. Items stay in their incoming
    sort order (rate desc \u2192 hours desc).

    - Only the ``\u251c`` / ``\u2514`` prefix is colored with *section_color*; names stay plain.
    - The Rate column receives the *category group* color.
    - Zero-rate / zero-point items are dimmed entirely (``#8d98a7``).

    Returns a flat list of cell-tuples ready for ``DataTable.add_rows()``.
    """
    if not rows:
        return []

    dim_color = "#8d98a7"
    result = []
    total = len(rows)
    for i, crow in enumerate(rows):
        is_last = (i == total - 1)
        prefix = "\u2514 " if is_last else "\u251c "
        name, hours, rate, pts = crow
        name_text = fmt_name_fn(name, rate)
        rate_color = CATEGORY_REGISTRY.get_color(name) or ""

        # Grey out zero-rate / zero-point items
        is_zero = (rate is not None and rate == 0) or (pts is not None and pts == 0)
        if is_zero:
            tree_name = Text.assemble((prefix, dim_color), (name_text.plain, dim_color))
            result.append(fmt_cells_fn(tree_name, hours, rate, pts, rate_color="", dim=dim_color))
        else:
            # Prefix color: section color if set, otherwise group color (Recovery view)
            prefix_color = section_color or rate_color
            tree_name = Text.assemble((prefix, prefix_color), (name_text.plain, ""))
            result.append(fmt_cells_fn(tree_name, hours, rate, pts, rate_color=rate_color))

    return result


def _render_logged_results(
    rows: list[Any],
    results: list[tuple[str, int, float, float]],
    section_label: str,
    section_color: str,
) -> None:
    """Append section header and logged result rows to *rows* list.

    Updates *rows* in-place. Each entry is a 4-tuple for DataTable.
    """
    rows.append((_fmt_section_header(section_label), Text(""), Text(""), Text("")))
    for i, (name, count, per_event, total) in enumerate(results):
        prefix = "\u2514 " if i == len(results) - 1 else "\u251c "
        rows.append((
            Text.assemble((prefix, section_color), (name, "")),
            Text(f"\u00d7{count}"), fmt_pts_rich(per_event), fmt_pts_rich(total),
        ))


# ──────────────────────────────────────────────
# SHARED CATEGORY-TABLE BUILDER
# ──────────────────────────────────────────────


_SCORED_SECTION_NAMES = ("positive", "negative", "unscored")


def build_category_rows(
    section_data: dict[str, Any],
    fmt_name_fn: Callable = _fmt_project_tree,
    fmt_cells_fn: Callable = _fmt_tree_cells,
) -> list[Any]:
    """Build a flat row list for a category DataTable.

    Iterates over the three scored sections (positive, negative, unscored),
    adding a coloured section header and rendered tree rows for each.
    Then appends logged-positive and logged-negative sections if present.

    Parameters
    ----------
    section_data:
        Dict with keys ``positive``, ``negative``, ``unscored`` (each a list of
        ``(name, hours, rate, pts)`` tuples) and optionally ``positive_results`` /
        ``negative_results`` (each a list of ``(name, count, per_event, total)``).
    fmt_name_fn:
        Callable ``(name, rate) -> Text`` for the project-name column.
    fmt_cells_fn:
        Callable ``(name, hours, rate, pts, rate_color, dim) -> tuple`` for
        full-row cell formatting.

    Returns
    -------
    list[Any]
        Flat list of 4-tuples ready for ``DataTable.add_rows()``.
    """
    rows: list[Any] = []
    for section_name in _SCORED_SECTION_NAMES:
        section_rows = section_data.get(section_name, [])
        if section_rows:
            rows.append(
                (_fmt_section_header(f"\u2022 {section_name.upper()}"),
                 Text(""), Text(""), Text(""))
            )
        rows.extend(
            _render_category_section(
                section_rows, fmt_name_fn, fmt_cells_fn,
                section_color=SECTION_COLORS.get(section_name.upper(), ""),
            )
        )

    if section_data.get("positive_results"):
        _render_logged_results(
            rows, section_data["positive_results"],
            "\u2022 LOGGED POSITIVE",
            SECTION_COLORS["LOGGED POSITIVE"],
        )
    if section_data.get("negative_results"):
        _render_logged_results(
            rows, section_data["negative_results"],
            "\u2022 LOGGED NEGATIVE",
            SECTION_COLORS["LOGGED NEGATIVE"],
        )

    return rows



