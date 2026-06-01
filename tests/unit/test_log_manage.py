"""Unit tests for new log management features:

- log_activity_direct with custom entry_date
- delete_activity_entry
- update_activity_date
- DateStepper widget
- _parse_option_name
- ManageScreen key bindings
"""

import csv
import os
from datetime import date

import pytest
from unittest.mock import patch

from toggl.neg import log_activity_direct, delete_activity_entry, update_activity_date
from toggl.widgets.date_stepper import DateStepper
from toggl.screens.dialogs import _parse_option_name


# ─────────────────────────────────────────────────────────────────
# log_activity_direct with entry_date
# ─────────────────────────────────────────────────────────────────


class TestLogActivityWithDate:
    """Test the entry_date parameter on log_activity_direct."""

    def test_log_negative_with_custom_date(self, tmp_data_dir, sample_config):
        """Logs a negative with a specific past date."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")

        ok, msg = log_activity_direct("Procrastination", "negative", entry_date="2023-06-15")
        assert ok is True
        assert "Procrastination" in msg

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["Date"] == "2023-06-15"

    def test_log_positive_with_custom_date(self, tmp_data_dir, sample_config):
        """Logs a positive with a specific past date."""
        import toggl.const

        with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
            f.write("Date,Positive,Points\n")

        ok, msg = log_activity_direct("Exercise", "positive", entry_date="2023-01-01")
        assert ok is True
        assert "Exercise" in msg

        with open(toggl.const.POSITIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["Date"] == "2023-01-01"

    def test_log_with_none_date_defaults_to_today(self, tmp_data_dir, sample_config):
        """None entry_date falls back to today."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")

        ok, _ = log_activity_direct("Procrastination", "negative", entry_date=None)
        assert ok is True

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        today = date.today().strftime("%Y-%m-%d")
        assert rows[0]["Date"] == today

    def test_log_without_date_uses_today(self, tmp_data_dir, sample_config):
        """Omitting entry_date uses today (backward compat)."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")

        ok, _ = log_activity_direct("Procrastination", "negative")
        assert ok is True

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        today = date.today().strftime("%Y-%m-%d")
        assert rows[0]["Date"] == today


# ─────────────────────────────────────────────────────────────────
# delete_activity_entry
# ─────────────────────────────────────────────────────────────────


class TestDeleteActivityEntry:
    """Tests for delete_activity_entry."""

    def test_delete_existing_negative(self, tmp_data_dir, sample_config):
        """Deletes a specific negative entry."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-01,Procrastination,-3.0\n")
            f.write("2023-01-02,Junk Food,-2.0\n")

        ok, msg = delete_activity_entry("negative", "2023-01-01", "Procrastination")
        assert ok is True
        assert "Deleted" in msg

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["Negative"] == "Junk Food"

    def test_delete_existing_positive(self, tmp_data_dir, sample_config):
        """Deletes a specific positive entry."""
        import toggl.const

        with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
            f.write("Date,Positive,Points\n")
            f.write("2023-06-01,Exercise,3.0\n")
            f.write("2023-06-01,Reading,2.0\n")

        ok, msg = delete_activity_entry("positive", "2023-06-01", "Exercise")
        assert ok is True

        with open(toggl.const.POSITIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["Positive"] == "Reading"

    def test_delete_nonexistent_entry(self, tmp_data_dir, sample_config):
        """Returns error when entry not found."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-01,Procrastination,-3.0\n")

        ok, msg = delete_activity_entry("negative", "2023-01-01", "NonExistent")
        assert ok is False
        assert "not found" in msg

        # Original data unchanged
        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1

    def test_delete_from_missing_file(self, tmp_data_dir, sample_config):
        """Handles missing CSV file gracefully."""
        import toggl.const

        if os.path.exists(toggl.const.NEGATIVES_CSV_FILE):
            os.remove(toggl.const.NEGATIVES_CSV_FILE)

        ok, msg = delete_activity_entry("negative", "2023-01-01", "X")
        assert ok is False
        assert "No log entries" in msg

    def test_delete_only_first_matching_entry(self, tmp_data_dir, sample_config):
        """Only deletes the first matching row when duplicates exist."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-01,Procrastination,-3.0\n")
            f.write("2023-01-01,Procrastination,-3.0\n")
            f.write("2023-01-01,Procrastination,-3.0\n")

        ok, _ = delete_activity_entry("negative", "2023-01-01", "Procrastination")
        assert ok is True

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert all(r["Negative"] == "Procrastination" for r in rows)


# ─────────────────────────────────────────────────────────────────
# update_activity_date
# ─────────────────────────────────────────────────────────────────


class TestUpdateActivityDate:
    """Tests for update_activity_date."""

    def test_update_negative_date(self, tmp_data_dir, sample_config):
        """Changes the date of a negative entry."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-01,Procrastination,-3.0\n")
            f.write("2023-01-02,Junk Food,-2.0\n")

        ok, msg = update_activity_date(
            "negative", "2023-01-01", "Procrastination", "2023-06-15"
        )
        assert ok is True
        assert "Moved" in msg

        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        dates = [r["Date"] for r in rows]
        assert "2023-06-15" in dates
        assert "2023-01-01" not in dates

    def test_update_positive_date(self, tmp_data_dir, sample_config):
        """Changes the date of a positive entry."""
        import toggl.const

        with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
            f.write("Date,Positive,Points\n")
            f.write("2023-06-01,Exercise,3.0\n")

        ok, msg = update_activity_date(
            "positive", "2023-06-01", "Exercise", "2023-06-15"
        )
        assert ok is True

        with open(toggl.const.POSITIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Date"] == "2023-06-15"
        assert rows[0]["Positive"] == "Exercise"

    def test_update_nonexistent_entry(self, tmp_data_dir, sample_config):
        """Returns error when entry not found."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-01,Procrastination,-3.0\n")

        ok, msg = update_activity_date(
            "negative", "2023-01-01", "NonExistent", "2023-06-15"
        )
        assert ok is False
        assert "not found" in msg

    def test_update_from_missing_file(self, tmp_data_dir, sample_config):
        """Handles missing CSV file gracefully."""
        import toggl.const

        if os.path.exists(toggl.const.NEGATIVES_CSV_FILE):
            os.remove(toggl.const.NEGATIVES_CSV_FILE)

        ok, msg = update_activity_date("negative", "2023-01-01", "X", "2023-01-02")
        assert ok is False
        assert "No log entries" in msg


# ─────────────────────────────────────────────────────────────────
# _parse_option_name
# ─────────────────────────────────────────────────────────────────


class TestParseOptionName:
    """Tests for the _parse_option_name helper."""

    def test_parse_with_key_hint_and_points(self):
        """Parses '[M]  Mistake  (+20 pts)' -> 'Mistake'."""
        assert _parse_option_name("[M]  Mistake  (+20 pts)") == "Mistake"

    def test_parse_with_key_hint_and_negative_points(self):
        """Parses '[P]  Procrastination  (-3 pts)' -> 'Procrastination'."""
        assert _parse_option_name("[P]  Procrastination  (-3 pts)") == "Procrastination"

    def test_parse_without_key_hint(self):
        """Parses 'Exercise  (+3 pts)' -> 'Exercise'."""
        assert _parse_option_name("Exercise  (+3 pts)") == "Exercise"

    def test_parse_no_points_suffix(self):
        """Returns full string if no points suffix."""
        assert _parse_option_name("JustAName") == "JustAName"

    def test_parse_decimal_points(self):
        """Handles decimal points format."""
        assert _parse_option_name("[R]  Reading  (+2.5 pts)") == "Reading"


# ─────────────────────────────────────────────────────────────────
# DateStepper widget
# ─────────────────────────────────────────────────────────────────


class TestDateStepper:
    """Tests for the DateStepper widget."""

    def test_initial_date_defaults_to_today(self):
        """DateStepper defaults to today's date."""
        stepper = DateStepper()
        assert stepper._initial_date == date.today()

    def test_initial_date_custom(self):
        """DateStepper accepts a custom initial date."""
        d = date(2023, 6, 15)
        stepper = DateStepper(initial_date=d)
        assert stepper._initial_date == d

    def test_max_date_defaults_to_today(self):
        """max_date defaults to today."""
        stepper = DateStepper()
        assert stepper._max_date == date.today()

    def test_max_date_custom(self):
        """Accepts a custom max_date."""
        d = date(2023, 12, 31)
        stepper = DateStepper(max_date=d)
        assert stepper._max_date == d

    def test_format_date(self):
        """_format_date returns YYYY-MM-DD."""
        assert DateStepper._format_date(date(2023, 6, 15)) == "2023-06-15"
        assert DateStepper._format_date(date(2023, 1, 1)) == "2023-01-01"

    def test_step_forward_within_max(self):
        """Steps forward when within max_date."""
        stepper = DateStepper(initial_date=date(2023, 6, 14), max_date=date(2023, 6, 15))
        stepper.selected_date = date(2023, 6, 14)
        stepper._step(1)
        assert stepper.selected_date == date(2023, 6, 15)

    def test_step_forward_at_max(self):
        """Does not step past max_date."""
        stepper = DateStepper(initial_date=date(2023, 6, 15), max_date=date(2023, 6, 15))
        stepper.selected_date = date(2023, 6, 15)
        stepper._step(1)
        assert stepper.selected_date == date(2023, 6, 15)

    def test_step_back(self):
        """Steps backward."""
        stepper = DateStepper(initial_date=date(2023, 6, 15))
        stepper.selected_date = date(2023, 6, 15)
        stepper._step(-1)
        assert stepper.selected_date == date(2023, 6, 14)
