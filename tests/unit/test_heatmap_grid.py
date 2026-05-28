"""Unit tests for yearly heatmap grid layout."""

import re
from datetime import date, timedelta

from toggl.tui import (
    HEATMAP_ROW_PREFIX,
    _heatmap_num_week_columns,
    build_yearly_heatmap_lines,
)


def _plain_width(line: str) -> int:
    """Terminal display width (Rich markup stripped)."""
    return len(re.sub(r"\[[^\]]*\]", "", line))


def test_heatmap_header_matches_row_width():
    year = 2026
    day_map = {"2026-04-15": 5.0, "2026-05-20": -3.0}
    lines, grid_start, num_weeks = build_yearly_heatmap_lines(year, day_map, 5.0)
    assert len(lines) == 8  # header + 7 DOW rows
    header, first_row = lines[0], lines[1]
    assert len(header) == len(first_row)
    assert num_weeks == _heatmap_num_week_columns(year)
    assert len(header) == HEATMAP_ROW_PREFIX + num_weeks * 2


def test_heatmap_all_dow_rows_same_width():
    year = 2026
    lines, _, _ = build_yearly_heatmap_lines(year, {}, 1.0)
    widths = {len(line) for line in lines[1:]}
    assert len(widths) == 1


def test_heatmap_click_date_mapping():
    year = 2026
    lines, grid_start, num_weeks = build_yearly_heatmap_lines(year, {}, 1.0)
    col, row = 10, 2  # Wed of week 10
    clicked = grid_start + timedelta(weeks=col, days=row)
    assert clicked.year == year
    assert clicked.weekday() == row


def test_heatmap_plain_width_matches_with_rich_cells():
    """Colored cells use Rich markup; display columns must still align with header."""
    day_map = {
        "2026-01-15": 5.0,
        "2026-02-15": -3.0,
        "2026-03-15": 2.0,
        "2026-04-15": -8.0,
    }
    lines, _, _ = build_yearly_heatmap_lines(2026, day_map, 8.0)
    header_w = _plain_width(lines[0])
    assert header_w == HEATMAP_ROW_PREFIX + _heatmap_num_week_columns(2026) * 2
    for line in lines[1:]:
        assert _plain_width(line) == header_w
