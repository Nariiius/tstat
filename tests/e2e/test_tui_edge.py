"""Edge-case and error-handling tests for TogglTUI."""

import json
import os
from datetime import date

import pytest

from toggl.tui import TogglTUI


@pytest.fixture
def tui_data(tmp_data_dir, monkeypatch):
    """Set up minimal config + data for edge case tests (reuses conftest tmp_data_dir)."""
    import toggl.const
    import toggl.tui
    import toggl.cache
    import toggl.config

    config_path = os.path.join(tmp_data_dir, "toggl_config.json")
    monkeypatch.setattr(toggl.const, "CONFIG_FILE", config_path)
    monkeypatch.setattr(toggl.config, "CONFIG_FILE", config_path)
    config_data = {
        "points": {"Learning to Code": 1.5, "Building Projects": 2.0},
        "negatives": {"Procrastination": -3.0},
        "positives": {"Exercise": 3.0},
        "daily_target": 13.0,
    }
    with open(config_path, "w") as f:
        json.dump(config_data, f)

    # -- Weekly CSV with 1 week --
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("Week,Project,Hours\n")
        f.write("2023-W01,Learning to Code,10.5\n")

    # -- Daily CSV (2 days) --
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("Date,Project,Hours\n")
        f.write("2023-01-02,Learning to Code,1.5\n")
        f.write("2023-01-03,Learning to Code,2.0\n")

    # -- Empty negatives / positives CSVs --
    with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
        f.write("Date,Negative,Points\n")
    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")

    # -- Sync history --
    with open(toggl.const.HISTORY_FILE, "w") as f:
        json.dump({"last_updated": "2023-01-02T10:00:00",
                    "synced_weeks": {"2023-W01": "ok"},
                    "synced_days": {}}, f)

    # -- Freeze time --
    FAKE_TODAY = date(2023, 1, 2)

    class MockDate(date):
        @classmethod
        def today(cls):
            return FAKE_TODAY

    monkeypatch.setattr(toggl.tui, "date", MockDate)
    monkeypatch.setattr(toggl.cache, "date", MockDate)
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: False)

    return tmp_data_dir


# ───────────────────────────────────────────────────────────────────
# Edge case tests
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_data_shows_gracefully(tui_data):
    """App renders all views without crash when CSV files are empty."""
    import toggl.const

    # Replace CSVs with headers only (no data rows)
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("Week,Project,Hours\n")
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("Date,Project,Hours\n")

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for i in range(8):
            app.active_view_index = i
            app._refresh_view_by_index(i)
            await pilot.pause()

        # If we got here without exception, empty data is handled


@pytest.mark.asyncio
async def test_missing_data_files_shows_gracefully(tui_data):
    """App renders without crash when no CSV data files exist."""
    import toggl.const

    # Delete all data files
    for path in [toggl.const.CSV_FILE, toggl.const.DAILY_CSV_FILE,
                 toggl.const.NEGATIVES_CSV_FILE, toggl.const.POSITIVES_CSV_FILE]:
        if os.path.exists(path):
            os.remove(path)

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for i in range(8):
            app.active_view_index = i
            app._refresh_view_by_index(i)
            await pilot.pause()

        # If we got here without exception, missing files are handled


@pytest.mark.asyncio
async def test_csv_with_blank_lines(tui_data):
    """App handles CSV files with trailing blank lines without error."""
    import toggl.const

    # Append a blank line to the weekly CSV (common edge case)
    with open(toggl.const.CSV_FILE, "a") as f:
        f.write("\n")

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Still renders Day view with data
        day_table = app.query_one("#day-table")
        assert day_table.row_count > 0


@pytest.mark.asyncio
async def test_rapid_view_switching(tui_data):
    """Quick successive view switches do not crash the app."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for _ in range(20):
            app.action_next_view()
        await pilot.pause()

        # Active view is still a valid index (8 views: 0-7)
        assert 0 <= app.active_view_index < 8


@pytest.mark.asyncio
async def test_confirm_screen_cancel(tui_data):
    """Pressing escape on ConfirmScreen cancels without side effects."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Push a ConfirmScreen (sync action does this)
        app.action_sync_current_week()
        await pilot.pause()

        # Cancel
        await pilot.press("escape")
        await pilot.pause()

        # Back on main screen, day view still renders
        day_view = app.query_one("#day-view")
        assert "-active" in day_view.classes
        day_table = app.query_one("#day-table")
        assert day_table.row_count > 0


@pytest.mark.asyncio
async def test_negative_modal_escape_closes(tui_data):
    """Pressing escape on NegativeInputScreen closes it without logging."""
    import toggl.const
    import csv

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_add_negative()
        await pilot.pause()

        from toggl.tui import NegativeInputScreen
        assert isinstance(app.screen, NegativeInputScreen)

        # Press escape to cancel
        await pilot.press("escape")
        await pilot.pause()

        # Back on main screen
        assert not isinstance(app.screen, NegativeInputScreen)

        # CSV is unchanged (still just header)
        with open(toggl.const.NEGATIVES_CSV_FILE) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_sync_view_shows_all_status_fields(tui_data):
    """Sync/Quota view shows current week, last updated, and quota info."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for _ in range(6):
            app.action_next_view()
            await pilot.pause()
        assert app.active_view_index == 7

        sync_table = app.query_one("#sync-table")
        all_text = " ".join(
            str(sync_table.get_row_at(i)[0]).lower()
            for i in range(sync_table.row_count)
        )
        assert "current week" in all_text
        assert "last updated" in all_text
        assert "backfill" in all_text
