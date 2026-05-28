"""Unit tests for yearly heatmap grid layout."""

from datetime import date, timedelta

from toggl.tui import (
    HEATMAP_ROW_PREFIX,
    _heatmap_num_week_columns,
    build_yearly_heatmap_lines,
)


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
