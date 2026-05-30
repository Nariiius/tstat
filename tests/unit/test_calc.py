"""Unit tests for calculation engine and format helpers."""

import pytest
from unittest.mock import patch

from toggl.calc import calculate, format_signed, get_negative_catalog_rows, get_positive_catalog_rows


class TestCalculate:
    """Tests for the calculate() function."""

    def test_empty_projects(self):
        """Empty projects dict returns empty list."""
        result = calculate({})
        assert result == []

    def test_single_project_with_rate(self):
        """Single project with rate calculates points correctly."""
        with patch('toggl.calc.POINTS', {'Work': 2.0}):
            result = calculate({'Work': 5.0})
            assert len(result) == 1
            name, hours, rate, pts = result[0]
            assert name == 'Work'
            assert hours == 5.0
            assert rate == 2.0
            assert pts == 10.0

    def test_project_without_rate(self):
        """Project without rate returns None for points."""
        with patch('toggl.calc.POINTS', {}):
            result = calculate({'Unknown': 3.0})
            assert len(result) == 1
            name, hours, rate, pts = result[0]
            assert name == 'Unknown'
            assert hours == 3.0
            assert rate is None
            assert pts is None

    def test_multiple_projects_sorted_by_rate(self):
        """Multiple projects sorted by rate descending."""
        with patch('toggl.calc.POINTS', {'Low': 1.0, 'High': 3.0, 'Mid': 2.0}):
            result = calculate({'Low': 1.0, 'High': 1.0, 'Mid': 1.0})
            assert len(result) == 3
            # Should be sorted: High (3.0), Mid (2.0), Low (1.0)
            assert result[0][0] == 'High'
            assert result[1][0] == 'Mid'
            assert result[2][0] == 'Low'

    def test_unscored_projects_at_end(self):
        """Projects without rates (unscored) appear at end."""
        with patch('toggl.calc.POINTS', {'Scored': 2.0}):
            result = calculate({'Scored': 1.0, 'Unscored': 1.0})
            assert len(result) == 2
            assert result[0][0] == 'Scored'
            assert result[1][0] == 'Unscored'
            assert result[1][2] is None

    def test_negative_rate_projects(self):
        """Projects with negative rates are handled correctly."""
        with patch('toggl.calc.POINTS', {'Bad': -1.5, 'Good': 2.0}):
            result = calculate({'Bad': 2.0, 'Good': 3.0})
            assert len(result) == 2
            # Good (2.0) should come before Bad (-1.5)
            assert result[0][0] == 'Good'
            assert result[0][3] == 6.0
            assert result[1][0] == 'Bad'
            assert result[1][3] == -3.0

    def test_zero_hours(self):
        """Zero hours calculates zero points."""
        with patch('toggl.calc.POINTS', {'Work': 2.0}):
            result = calculate({'Work': 0.0})
            assert result[0][3] == 0.0

    def test_fractional_hours(self):
        """Fractional hours round correctly."""
        with patch('toggl.calc.POINTS', {'Work': 1.5}):
            result = calculate({'Work': 2.333})
            assert result[0][3] == 3.5  # 2.333 * 1.5 = 3.4995, rounds to 3.5


class TestFormatSigned:
    """Tests for the format_signed() function."""

    def test_positive_value(self):
        """Positive values get + prefix."""
        assert format_signed(5.0) == "+5.0"
        assert format_signed(0.5) == "+0.5"

    def test_negative_value(self):
        """Negative values keep - sign."""
        assert format_signed(-5.0) == "-5.0"
        assert format_signed(-0.5) == "-0.5"

    def test_zero_value(self):
        """Zero displays as 0.0."""
        assert format_signed(0.0) == "0.0"

    def test_near_zero_positive(self):
        """Values < 0.05 round to 0.0."""
        assert format_signed(0.04) == "0.0"
        assert format_signed(0.01) == "0.0"

    def test_near_zero_negative(self):
        """Negative values > -0.05 round to 0.0."""
        assert format_signed(-0.04) == "0.0"
        assert format_signed(-0.01) == "0.0"

    def test_boundary_values(self):
        """Boundary at 0.05."""
        assert format_signed(0.05) == "+0.1"
        assert format_signed(-0.05) == "-0.1"


class TestCatalogRows:
    """Tests for catalog row functions."""

    def test_get_negative_catalog_rows(self):
        """Returns list of (name, points) tuples."""
        with patch('toggl.calc.NEGATIVES', {'Bad1': -1.0, 'Bad2': -2.0}):
            rows = get_negative_catalog_rows()
            assert len(rows) == 2
            # Check structure
            for name, points in rows:
                assert isinstance(name, str)
                assert isinstance(points, (int, float))

    def test_get_positive_catalog_rows(self):
        """Returns list of (name, points) tuples."""
        with patch('toggl.calc.POSITIVES', {'Good1': 1.0, 'Good2': 2.0}):
            rows = get_positive_catalog_rows()
            assert len(rows) == 2
            for name, points in rows:
                assert isinstance(name, str)
                assert isinstance(points, (int, float))

    def test_empty_catalogs(self):
        """Empty catalogs return empty lists."""
        with patch('toggl.calc.NEGATIVES', {}):
            assert get_negative_catalog_rows() == []
        with patch('toggl.calc.POSITIVES', {}):
            assert get_positive_catalog_rows() == []
