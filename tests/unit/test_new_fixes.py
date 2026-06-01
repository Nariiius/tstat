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


def test_sync_lock_and_auto_sync_check(monkeypatch):
    """Test that check_auto_sync obeys _sync_in_progress lock and needs_auto_update."""
    from toggl.tui import TogglTUI
    import toggl.tui
    
    app = TogglTUI()
    assert app._sync_in_progress is False
    
    # 1. If sync is already in progress, check_auto_sync must skip and not trigger auto refresh
    app._sync_in_progress = True
    called_refresh = False
    
    def mock_do_auto_refresh():
        nonlocal called_refresh
        called_refresh = True
        
    monkeypatch.setattr(app, "_do_auto_refresh", mock_do_auto_refresh)
    app.check_auto_sync()
    assert called_refresh is False
    
    # 2. If sync is not in progress, but needs_auto_update() is False, it should not trigger
    app._sync_in_progress = False
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: False)
    app.check_auto_sync()
    assert called_refresh is False
    
    # 3. If sync is not in progress, and needs_auto_update() is True, it should trigger
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: True)
    app.check_auto_sync()
    assert called_refresh is True


def test_negative_mode_graph_limits_below_zero(monkeypatch):
    """Verify that in negative mode, GraphWidget receives negative values and Y-limits are set below zero."""
    from toggl.widgets.graph import GraphWidget
    import plotext as plt
    
    captured_ylim = None
    
    def mock_ylim(ymin, ymax):
        nonlocal captured_ylim
        captured_ylim = (ymin, ymax)
        
    monkeypatch.setattr(plt, "ylim", mock_ylim)
    
    # Instantiate graph widget
    graph = GraphWidget()
    graph.set_mode("negative")
    
    # Provide actual negative values (which are correct after the command.py unpacking fix)
    dates = ["2023-01-01", "2023-01-02", "2023-01-03"]
    values = [-10.0, -20.0, -30.0]
    
    graph.set_data(dates, values, avg=-20.0)
    
    # We must mock size to have positive width/height so render() doesn't fail
    class SizeMock:
        width = 40
        height = 10
    monkeypatch.setattr(GraphWidget, "size", property(lambda self: SizeMock()))
    
    # Trigger render
    graph.render()
    
    assert captured_ylim is not None
    ymin, ymax = captured_ylim
    # ymin must be below zero (e.g. around -30) and ymax must be 0.0 (or slightly rounded nice bounds <= 0)
    assert ymin < 0
    assert ymax <= 0


