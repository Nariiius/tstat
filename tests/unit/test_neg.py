"""Unit tests for negative/positive action logging."""

import pytest
import csv
from datetime import date
from unittest.mock import patch

from toggl.neg import log_negative_direct, log_positive_direct


class TestLogNegativeDirect:
    """Tests for log_negative_direct function."""

    def test_log_negative_success(self, tmp_data_dir, sample_config):
        """Successfully logs a negative action."""
        import toggl.const
        
        # Create empty negatives CSV
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
        
        ok, message = log_negative_direct('Procrastination')
        
        assert ok is True
        assert 'Procrastination' in message
        assert 'Logged' in message
        
        # Verify CSV was updated
        with open(toggl.const.NEGATIVES_CSV_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
        
        assert len(rows) == 1
        assert rows[0]['Negative'] == 'Procrastination'
        assert float(rows[0]['Points']) == -3.0

    def test_log_negative_case_insensitive(self, tmp_data_dir, sample_config):
        """Negative name lookup is case-insensitive."""
        import toggl.const
        
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
        
        ok, message = log_negative_direct('procrastination')
        
        assert ok is True
        assert 'Procrastination' in message

    def test_log_negative_not_found(self, tmp_data_dir, sample_config):
        """Returns error when negative not found."""
        import toggl.const
        
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
        
        ok, message = log_negative_direct('NonExistent')
        
        assert ok is False
        assert 'not found' in message

    def test_log_negative_preserves_existing(self, tmp_data_dir, sample_config):
        """Logging preserves existing entries."""
        import toggl.const
        
        # Create CSV with existing entry
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-01,Junk Food,-2.0\n')
        
        ok, message = log_negative_direct('Procrastination')
        
        assert ok is True
        
        # Verify both entries exist
        with open(toggl.const.NEGATIVES_CSV_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
        
        assert len(rows) == 2
        assert rows[0]['Negative'] == 'Junk Food'
        assert rows[1]['Negative'] == 'Procrastination'

    def test_log_negative_creates_file_if_missing(self, tmp_data_dir, sample_config):
        """Creates CSV file if it doesn't exist."""
        import toggl.const
        import os
        
        # Ensure file doesn't exist
        if os.path.exists(toggl.const.NEGATIVES_CSV_FILE):
            os.remove(toggl.const.NEGATIVES_CSV_FILE)
        
        ok, message = log_negative_direct('Procrastination')
        
        assert ok is True
        assert os.path.exists(toggl.const.NEGATIVES_CSV_FILE)


class TestLogPositiveDirect:
    """Tests for log_positive_direct function."""

    def test_log_positive_success(self, tmp_data_dir, sample_config):
        """Successfully logs a positive action."""
        import toggl.const
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
        
        ok, message = log_positive_direct('Exercise')
        
        assert ok is True
        assert 'Exercise' in message
        assert 'Logged' in message
        
        # Verify CSV was updated
        with open(toggl.const.POSITIVES_CSV_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
        
        assert len(rows) == 1
        assert rows[0]['Positive'] == 'Exercise'
        assert float(rows[0]['Points']) == 3.0

    def test_log_positive_case_insensitive(self, tmp_data_dir, sample_config):
        """Positive name lookup is case-insensitive."""
        import toggl.const
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
        
        ok, message = log_positive_direct('exercise')
        
        assert ok is True
        assert 'Exercise' in message

    def test_log_positive_not_found(self, tmp_data_dir, sample_config):
        """Returns error when positive not found."""
        import toggl.const
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
        
        ok, message = log_positive_direct('NonExistent')
        
        assert ok is False
        assert 'not found' in message

    def test_log_positive_preserves_existing(self, tmp_data_dir, sample_config):
        """Logging preserves existing entries."""
        import toggl.const
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
            f.write('2023-01-01,Reading,2.0\n')
        
        ok, message = log_positive_direct('Exercise')
        
        assert ok is True
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
        
        assert len(rows) == 2
        assert rows[0]['Positive'] == 'Reading'
        assert rows[1]['Positive'] == 'Exercise'

    def test_log_positive_multiple_same_day(self, tmp_data_dir, sample_config):
        """Can log multiple positives on same day."""
        import toggl.const
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
        
        log_positive_direct('Exercise')
        log_positive_direct('Reading')
        
        with open(toggl.const.POSITIVES_CSV_FILE, 'r') as f:
            rows = list(csv.DictReader(f))
        
        assert len(rows) == 2
        # Both should have today's date
        today = date.today().strftime('%Y-%m-%d')
        assert rows[0]['Date'] == today
        assert rows[1]['Date'] == today
