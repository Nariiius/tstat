"""Cell-level formatting utilities for TUI DataTable rows."""

from typing import Any

from rich.text import Text

from toggl.config import CATEGORY_REGISTRY, RATE_COLORS
from toggl.widgets.icons import ICON


def _spark_net_rich(
    net: float | None, max_abs: float, bar_w: int = 4, dim_zero: bool = False,
    blame_tracked: float = 0, blame_logged: float = 0, blame_w: int = 3,
) -> str:
    """
    Return Rich markup for a net-points cell in the interactive spark tables.
    Positive \u2192 green bar on left of value.  Negative \u2192 red value + bar on right.
    When net < 0 and blame data is provided, a blame bar (red tracked + magenta
    logged) is appended after the net bar.
    """
    if net is None or (abs(net) < 0.05 and dim_zero):
        return f"[dim]{ICON['em_dash']}[/]"
    if abs(net) < 0.05:
        return "[dim]0.0[/]"
    bar_len = max(1, round(abs(net) / max_abs * bar_w)) if max_abs > 0 else 1
    if net > 0:
        bar = ICON["bar_block"] * bar_len
        return f"[#37d994]{bar} +{net}[/]"
    else:
        blame_total = blame_tracked + blame_logged
        if blame_total > 0 and blame_w > 0:
            net_bar_len = max(1, bar_len - blame_w)
            red_count = round(blame_tracked / blame_total * blame_w)
            mag_count = blame_w - red_count
            bar = ICON["bar_block"] * net_bar_len
            block = ICON["bar_block"]
            blame = f"[#ff5f5f]{block * red_count}[/][#ff5fff]{block * mag_count}[/]"
        bar = ICON["bar_block"] * bar_len
        return f"[#ff5f5f]{net} {bar}[/]"


def fmt_rate(rate: float | None) -> str:
    if rate is None:
        return ICON["em_dash"]
    r = int(rate) if rate == int(rate) else rate
    return f"{ICON['multiply']}{r}"


def fmt_pts(pts: float | None) -> str:
    if pts is None:
        return ICON["em_dash"]
    if pts == 0:
        return "0.0"
    return f"+{pts}" if pts > 0 else str(pts)


def format_signed_rich(value: float) -> str:
    if abs(value) < 0.05:
        value = 0.0
    if value > 0:
        return f"[#37d994]+{value:.1f}[/]"
    elif value < 0:
        return f"[#ff5f5f]{value:.1f}[/]"
    return "0.0"


def fmt_pts_rich(pts: float | None) -> str:
    if pts is None:
        return ICON["em_dash"]
    if pts == 0:
        return "0.0"
    if pts > 0:
        return f"[#37d994]+{pts:.1f}[/]"
    return f"[#ff5f5f]{pts:.1f}[/]"


def _fmt_project_name(name: str) -> Text:
    """Return a Rich Text project name colored by category or rate group.

    Priority: category color > rate_colors > plain.
    """
    cat_color = CATEGORY_REGISTRY.get_color(name)
    if cat_color:
        return Text(name, style=cat_color)
    return Text(name)


def _fmt_project_name_by_rate(name: str, rate: float | None) -> Text:
    """Return a Rich Text project name colored by category or rate group.

    Priority: category color > rate_colors > plain.
    """
    cat_color = CATEGORY_REGISTRY.get_color(name)
    if cat_color:
        return Text(name, style=cat_color)
    if rate is not None:
        rate_color = RATE_COLORS.get_color(rate)
        if rate_color:
            return Text(name, style=rate_color)
    return Text(name)


def _fmt_project_tree(name: str, rate: float | None) -> Text:
    """Name formatter for category-tree rows (category color only, no rate fallback)."""
    cat_color = CATEGORY_REGISTRY.get_color(name)
    if cat_color:
        return Text(name, style=cat_color)
    return Text(name)


def _fmt_tree_cells(
    name_text: Text, hours: float | None, rate: float | None, pts: float | None,
    rate_color: str = "", dim: str = "",
) -> tuple[Any, ...]:
    """Build a 4-tuple for a category-tree row.

    The Rate column inherits *rate_color* (the category group color).
    When *dim* is set the entire row uses that color.
    """
    if dim:
        return (
            name_text,
            Text(f"{hours:.2f}h", style=dim) if hours is not None else Text(""),
            Text(fmt_rate(rate), style=dim) if rate is not None else Text(""),
            Text(f"{pts:.1f}", style=dim) if pts is not None else Text(""),
        )
    rate_cell = Text(fmt_rate(rate), style=rate_color) if rate is not None else Text("")
    return (
        name_text,
        f"{hours:.2f}h" if hours is not None else "",
        rate_cell,
        fmt_pts_rich(pts) if pts is not None else Text(""),
    )


def _fmt_recovery_cells(
    name_text: Text, _hours: float | None, rate: float | None,
    hours_needed: float | None, rate_color: str = "", dim: str = "",
) -> tuple[Text, Text, Text]:
    rate_text = Text(fmt_rate(rate), style=rate_color) if rate is not None else Text("")
    return (
        name_text,
        rate_text,
        Text(str(hours_needed)) if hours_needed is not None else Text(""),
    )
