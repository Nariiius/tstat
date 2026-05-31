"""Formatting utilities for TUI display cells and sections."""
from toggl.formatters.colors import (
    _net_color,
    _label_for_day,
)
from toggl.formatters.cells import (
    format_signed_rich,
    _spark_net_rich,
    fmt_rate,
    fmt_pts,
    fmt_pts_rich,
    _fmt_project_name,
    _fmt_project_name_by_rate,
    _fmt_project_tree,
    _fmt_tree_cells,
    _fmt_recovery_cells,
)
from toggl.formatters.sections import (
    _fmt_section_header,
    _render_category_section,
    _render_logged_results,
    SECTION_COLORS,
)

__all__ = [
    "_net_color", "_label_for_day",
    "format_signed_rich", "_spark_net_rich", "fmt_rate", "fmt_pts", "fmt_pts_rich",
    "_fmt_project_name", "_fmt_project_name_by_rate", "_fmt_project_tree",
    "_fmt_tree_cells", "_fmt_recovery_cells",
    "_fmt_section_header", "_render_category_section", "_render_logged_results", "SECTION_COLORS",
]
