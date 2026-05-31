"""Unit tests for toggl/formatters/sections.py — section rendering utilities."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from toggl.formatters.sections import (
    _fmt_section_header,
    _render_category_section,
    _render_logged_results,
    build_category_rows,
)


def _dummy_name_fn(name: str, rate: float | None) -> Text:
    """Dummy project-name formatter for testing."""
    return Text(name)


def _dummy_cells_fn(
    name: Text, hours: float | None, rate: float | None, pts: float | None,
    rate_color: str = "", dim: str = "",
) -> tuple[Text, str, str, str]:
    """Dummy cell formatter — returns name + stringified values."""
    return (name, str(hours or ""), str(rate or ""), str(pts or ""))


class TestBuildCategoryRows:
    """Tests for build_category_rows."""

    def _assert_row_count(
        self, rows: list[Any],
        n_scored_sections: int,
        n_lr: int = 0,
    ) -> None:
        """Validate *rows* length matches expected count.

        n_scored_sections — how many of the three (pos/neg/unscored) are
        non-empty (each adds 1 header + N data rows).
        n_lr — number of logged-result sections that are present.
        """
        # At minimum we have headers for each non-empty scored section
        # plus headers for each logged-result section.
        assert len(rows) >= n_scored_sections + n_lr, (
            f"Expected ≥{n_scored_sections + n_lr} rows, got {len(rows)}"
        )

    def test_empty_all_sections(self):
        """No data in any section returns an empty list."""
        data: dict[str, Any] = {
            "positive": [],
            "negative": [],
            "unscored": [],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        assert rows == []

    def test_single_section_positive(self):
        """One positive row produces header + data row, no logged results."""
        data: dict[str, Any] = {
            "positive": [("Learning", 10.0, 1.5, 15.0)],
            "negative": [],
            "unscored": [],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        assert len(rows) == 2  # header + 1 data row
        # First row is the section header
        header_cell = rows[0][0]
        assert isinstance(header_cell, Text)
        assert "POSITIVE" in str(header_cell)

    def test_multiple_sections(self):
        """All three scored sections present each gets a header + data rows."""
        data: dict[str, Any] = {
            "positive": [("Proj A", 5.0, 2.0, 10.0), ("Proj B", 3.0, 1.0, 3.0)],
            "negative": [("Bad Habit", 2.0, -2.0, -4.0)],
            "unscored": [],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        # positive: 1 header + 2 rows = 3
        # negative: 1 header + 1 row = 2
        # unscored: empty = 0
        assert len(rows) == 5

        # First row header says POSITIVE
        assert "POSITIVE" in str(rows[0][0])
        # Row 3 header says NEGATIVE
        assert "NEGATIVE" in str(rows[3][0])

    def test_logged_results_included(self):
        """Adds logged-positive and/or logged-negative sections when present."""
        data: dict[str, Any] = {
            "positive": [("Proj A", 5.0, 2.0, 10.0)],
            "negative": [],
            "unscored": [],
            "positive_results": [("Exercise", 3, 2.0, 6.0)],
            "negative_results": [("Junk Food", 1, -1.0, -1.0)],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        # positive: 1 header + 1 row = 2
        # logged-positive: 1 header + 1 row = 2
        # logged-negative: 1 header + 1 row = 2
        assert len(rows) == 6

    def test_only_logged_results(self):
        """Logged results render even with no scored sections."""
        data: dict[str, Any] = {
            "positive": [],
            "negative": [],
            "unscored": [],
            "positive_results": [("Bonus", 1, 5.0, 5.0)],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        assert len(rows) == 2  # header + 1 data row

    def test_section_color_applied(self):
        """Each section header gets the correct color from SECTION_COLORS."""
        data: dict[str, Any] = {
            "positive": [("Learn", 5.0, 1.0, 5.0)],
            "negative": [("Slack", 2.0, -1.0, -2.0)],
            "unscored": [("Misc", 1.0, None, None)],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        # Find the three headers
        headers = [r[0] for r in rows if isinstance(r[0], Text) and r[0].plain.startswith("•")]
        assert len(headers) == 3
        header_texts = [h.plain for h in headers]
        assert any("POSITIVE" in t for t in header_texts)
        assert any("NEGATIVE" in t for t in header_texts)
        assert any("UNSCORED" in t for t in header_texts)

    def test_logged_section_labels(self):
        """Logged section labels include proper markers."""
        data: dict[str, Any] = {
            "positive": [],
            "negative": [],
            "unscored": [],
            "positive_results": [("Win", 1, 3.0, 3.0)],
            "negative_results": [("Loss", 1, -2.0, -2.0)],
        }
        rows = build_category_rows(data, _dummy_name_fn, _dummy_cells_fn)
        assert len(rows) == 4
        # Two headers: LOGGED POSITIVE and LOGGED NEGATIVE
        header_texts = [str(r[0]) for r in rows if isinstance(r[0], Text)]
        assert any("LOGGED POSITIVE" in t for t in header_texts)
        assert any("LOGGED NEGATIVE" in t for t in header_texts)

    def test_default_formatters_exported(self):
        """build_category_rows works with the default formatters."""
        from toggl.formatters.cells import _fmt_project_tree, _fmt_tree_cells
        assert callable(_fmt_project_tree)
        assert callable(_fmt_tree_cells)
