"""Unit tests for newly added bug fixes and robust sync/token logic."""

import os
import csv
import json
import pytest
from datetime import date, timedelta

from toggl.api import get_api_token, TogglAPIError
from toggl.cache import (
    _patch_daily_csv,
    _patch_weekly_csv,
    needs_auto_update,
    parse_iso,
)
from toggl.backfill import _week_has_daily_data


def test_get_api_token_raises_error_on_missing(monkeypatch):
    """get_api_token must cleanly raise TogglAPIError when token is missing, instead of calling input()."""
    # Ensure env variable is cleared
    monkeypatch.delenv("TOGGL_API_TOKEN", raising=False)
    
    # Mock load_config to return no token
    import toggl.api
    monkeypatch.setattr(toggl.api, "load_config", lambda: {})
    
    # Ensure standard input won't be called (would raise OSError if called by input())
    with pytest.raises(TogglAPIError) as exc:
        get_api_token()
    
    assert "Toggl API Token not found" in str(exc.value)


def test_needs_auto_update_true_on_fresh_install(monkeypatch):
    """needs_auto_update must return True on a fresh install (when no last_updated timestamp exists)."""
    import toggl.cache
    # Mock _load_history to return empty dictionary
    monkeypatch.setattr(toggl.cache, "_load_history", lambda: {})
    
    assert needs_auto_update() is True


def test_patch_daily_csv_replaces_synced_week(tmp_data_dir):
    """_patch_daily_csv replaces all data for the synced week; data from other weeks is preserved."""
    import toggl.const
    
    # Write existing rows: W01 dates (2023-01-01, 2023-01-02) and a W02 date (2023-01-08)
    with open(toggl.const.DAILY_CSV_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Project", "Hours"])
        w.writeheader()
        w.writerow({"Date": "2023-01-01", "Project": "Learning to Code", "Hours": "1.5"})
        w.writerow({"Date": "2023-01-01", "Project": "Manual Points", "Hours": "2.0"})
        w.writerow({"Date": "2023-01-02", "Project": "Fitness", "Hours": "1.0"})
        w.writerow({"Date": "2023-01-08", "Project": "Reading", "Hours": "3.0"})  # W02 — untouched

    # Sync W01: API returns only "Learning to Code" on 2023-01-01
    daily_data = {
        "2023-01-01": {"Learning to Code": 3.0}
    }
    
    _patch_daily_csv("2023-W01", daily_data)
    
    with open(toggl.const.DAILY_CSV_FILE, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        
    by_date_proj = {(row["Date"], row["Project"]): float(row["Hours"]) for row in rows}
    
    # 1. "Learning to Code" updated to 3.0
    assert by_date_proj[("2023-01-01", "Learning to Code")] == 3.0
    # 2. "Manual Points" REMOVED — API didn't return it for this week
    assert ("2023-01-01", "Manual Points") not in by_date_proj
    # 3. "Fitness" on 2023-01-02 REMOVED — day is in W01 but API returned nothing for it
    assert ("2023-01-02", "Fitness") not in by_date_proj
    # 4. W02 data preserved
    assert by_date_proj[("2023-01-08", "Reading")] == 3.0


def test_patch_weekly_csv_replaces_synced_week(tmp_data_dir):
    """_patch_weekly_csv replaces all data for the synced week; other weeks are preserved."""
    import toggl.const
    
    with open(toggl.const.CSV_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Week", "Project", "Hours"])
        w.writeheader()
        w.writerow({"Week": "2023-W01", "Project": "Learning to Code", "Hours": "10.5"})
        w.writerow({"Week": "2023-W01", "Project": "Manual Points", "Hours": "5.0"})
        w.writerow({"Week": "2023-W02", "Project": "Learning to Code", "Hours": "8.0"})

    # Sync W01: API returns only "Learning to Code" (no "Manual Points")
    weekly_data = {
        "Learning to Code": 12.0
    }
    
    _patch_weekly_csv("2023-W01", weekly_data)
    
    with open(toggl.const.CSV_FILE, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        
    by_week_proj = {(row["Week"], row["Project"]): float(row["Hours"]) for row in rows}
    
    # 1. "Learning to Code" updated to 12.0
    assert by_week_proj[("2023-W01", "Learning to Code")] == 12.0
    # 2. "Manual Points" REMOVED — API didn't return it
    assert ("2023-W01", "Manual Points") not in by_week_proj
    # 3. W02 data preserved
    assert by_week_proj[("2023-W02", "Learning to Code")] == 8.0


def test_week_has_daily_data_summation_comparison():
    """_week_has_daily_data must return True when daily hours sum up close to weekly hours, even with empty days."""
    # Week starts on 2023-01-01
    weekly_hours = {"2023-W01": 10.0}
    
    # 1. Total daily hours = 10.0, but spread over only 4 days (3 days have 0 activity, i.e. zero entries)
    daily_data = {
        "2023-01-01": {"Learning to Code": 2.5},
        "2023-01-02": {"Learning to Code": 2.5},
        "2023-01-03": {"Learning to Code": 2.5},
        "2023-01-04": {"Learning to Code": 2.5},
        # days 5, 6, 7 are empty
    }
    
    # Should return True because 10.0 - 10.0 == 0 < 0.05
    assert _week_has_daily_data("2023-W01", daily_data, weekly_hours) is True
    
    # 2. Total daily hours = 5.0, weekly hours = 10.0 (incomplete daily data)
    daily_data_partial = {
        "2023-01-01": {"Learning to Code": 5.0}
    }
    
    # Should return False because 10.0 - 5.0 = 5.0 >= 0.05
    assert _week_has_daily_data("2023-W01", daily_data_partial, weekly_hours) is False
