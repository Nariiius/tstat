"""Unit tests for calculation engine and format helpers."""

import pytest
from unittest.mock import patch

from toggl.calc import calculate, format_signed, get_negative_catalog_rows, get_positive_catalog_rows, calculate_logged_activity_totals


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


class TestCalculateLoggedActivityTotals:
    """Tests for calculate_logged_activity_totals()."""

    def test_empty_entries(self):
        """Empty entries list returns empty result."""
        result = calculate_logged_activity_totals([], {"Reading": 2})
        assert result == []

    def test_single_positive_entry(self):
        """One positive entry → count=1, sign=1 gives positive total."""
        entries = [{"name": "Reading", "points": 2.0}]
        result = calculate_logged_activity_totals(entries, {"Reading": 2}, sign=1)
        assert len(result) == 1
        name, count, points_per_event, total_points = result[0]
        assert name == "Reading"
        assert count == 1
        assert points_per_event == 2.0
        assert total_points == 2.0

    def test_single_negative_entry(self):
        """One negative entry → count=1, sign=-1 gives negative total."""
        entries = [{"name": "GI Dailies", "points": 10.0}]
        result = calculate_logged_activity_totals(entries, {"GI Dailies": 10}, sign=-1)
        assert len(result) == 1
        name, count, points_per_event, total_points = result[0]
        assert name == "GI Dailies"
        assert count == 1
        assert points_per_event == -10.0
        assert total_points == -10.0

    def test_multiple_occurrences_positive(self):
        """5 occurrences of Reading at +2 each → count=5, total=+10."""
        entries = [
            {"name": "Reading", "points": 2.0},
            {"name": "Reading", "points": 2.0},
            {"name": "Reading", "points": 2.0},
            {"name": "Reading", "points": 2.0},
            {"name": "Reading", "points": 2.0},
        ]
        result = calculate_logged_activity_totals(entries, {"Reading": 2}, sign=1)
        assert len(result) == 1
        name, count, points_per_event, total_points = result[0]
        assert name == "Reading"
        assert count == 5
        assert points_per_event == 2.0
        assert total_points == 10.0

    def test_multiple_occurrences_negative(self):
        """7 occurrences of GI Dailies at -20 each → count=7, total=-140."""
        entries = [
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
            {"name": "GI Dailies", "points": 20.0},
        ]
        result = calculate_logged_activity_totals(entries, {"GI Dailies": 10}, sign=-1)
        assert len(result) == 1
        name, count, points_per_event, total_points = result[0]
        assert name == "GI Dailies"
        assert count == 7
        assert points_per_event == -10.0
        assert total_points == -140.0

    def test_mixed_activities(self):
        """Multiple different activities → separate rows, sorted by name."""
        entries = [
            {"name": "Care", "points": 4.0},
            {"name": "Reading", "points": 2.0},
            {"name": "Care", "points": 4.0},
            {"name": "Care", "points": 4.0},
            {"name": "Reading", "points": 2.0},
        ]
        result = calculate_logged_activity_totals(entries, {"Care": 4, "Reading": 2}, sign=1)
        assert len(result) == 2
        # Sorted by name
        assert result[0][0] == "Care"
        assert result[0][1] == 3   # count
        assert result[0][3] == 12.0  # total
        assert result[1][0] == "Reading"
        assert result[1][1] == 2   # count
        assert result[1][3] == 4.0   # total

    def test_activity_not_in_config(self):
        """Activity not in config → points_per_event=0, but total_points from CSV still used."""
        entries = [{"name": "Unknown", "points": 5.0}, {"name": "Unknown", "points": 5.0}]
        result = calculate_logged_activity_totals(entries, {}, sign=1)
        assert len(result) == 1
        assert result[0][1] == 2        # count
        assert result[0][2] == 0.0      # points_per_event (not in config)
        assert result[0][3] == 10.0     # total_points (from CSV sum)

    def test_sign_positive(self):
        """sign=+1 keeps values positive."""
        entries = [{"name": "A", "points": 3.0}]
        result = calculate_logged_activity_totals(entries, {"A": 3}, sign=1)
        assert result[0][2] == 3.0   # points_per_event positive
        assert result[0][3] == 3.0   # total_points positive

    def test_sign_negative(self):
        """sign=-1 negates both points_per_event and total_points."""
        entries = [{"name": "A", "points": 3.0}]
        result = calculate_logged_activity_totals(entries, {"A": 3}, sign=-1)
        assert result[0][2] == -3.0  # points_per_event negative
        assert result[0][3] == -3.0  # total_points negative

    def test_config_negative_value_still_uses_abs(self):
        """Even if config stores negative, abs() is used before applying sign."""
        entries = [{"name": "A", "points": 3.0}]
        result = calculate_logged_activity_totals(entries, {"A": -3}, sign=1)
        assert result[0][2] == 3.0   # abs(config) * sign = 3

    def test_total_points_rounded(self):
        """total_points is rounded to 1 decimal place."""
        entries = [
            {"name": "A", "points": 1.666},
            {"name": "A", "points": 1.666},
            {"name": "A", "points": 1.666},
        ]
        result = calculate_logged_activity_totals(entries, {"A": 1.666}, sign=1)
        assert result[0][3] == 5.0  # 4.998 → rounds to 5.0
