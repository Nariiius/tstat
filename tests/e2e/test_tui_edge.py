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

    # -- Weekly CSV --
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("Week,Project,Hours\n")
        f.write("2023-W01,Learning to Code,10.5\n")
        f.write("2023-W01,Building Projects,4.2\n")

    # -- Daily CSV --
    from toggl.cache import get_week_dates
    from datetime import timedelta

    start_d, _ = get_week_dates("2023-W01")
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("Date,Project,Hours\n")
        for i in range(7):
            d = (start_d + timedelta(days=i)).strftime("%Y-%m-%d")
            f.write(f"{d},Learning to Code,1.5\n")
            f.write(f"{d},Building Projects,0.6\n")

    # -- Empty negatives / positives CSVs --
    with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
        f.write("Date,Negative,Points\n")
    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")

    # -- Sync history --
    with open(toggl.const.HISTORY_FILE, "w") as f:
        json.dump({"last_updated": None}, f)

    return tmp_data_dir


# ═══════════════════════════════════════════════════════════════════
# Edge case tests
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mounts_without_crash(tui_data):
    """App mounts and renders overview without crash."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Overview view renders with data
        cat_table = app.query_one("#overview-categories-table")
        assert cat_table.row_count > 0

        # Recovery table exists
        rec_table = app.query_one("#overview-recovery-table")
        assert rec_table is not None


@pytest.mark.asyncio
async def test_mounts_with_broken_csv(tui_data):
    """App does not crash if CSV has blank lines."""
    import toggl.const

    # Append a blank line to the weekly CSV (common edge case)
    with open(toggl.const.CSV_FILE, "a") as f:
        f.write("\n")

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Still renders overview with data
        cat_table = app.query_one("#overview-categories-table")
        assert cat_table.row_count > 0


@pytest.mark.asyncio
async def test_rapid_view_switching(tui_data):
    """Quick successive view switches do not crash the app."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for _ in range(20):
            app.action_next_view()
        await pilot.pause()

        # Active view is still a valid index (3 views: 0-2)
        assert 0 <= app.active_view_index < 3


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

        # Back on main screen, overview still renders
        cat_table = app.query_one("#overview-categories-table")
        assert cat_table.row_count > 0


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
async def test_insights_sync_line_has_quota(tui_data):
    """Insights tab sync footer mentions quota."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_next_view()
        await pilot.pause()
        assert app.active_view_index == 2

        sync_line = app.query_one("#insights-sync-line")
        assert "quota" in str(sync_line.render()).lower()
