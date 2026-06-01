"""Textual Pilot E2E tests for TogglTUI — behavioural tests of user-visible features."""

import json
import os
from datetime import date, timedelta

import pytest

from toggl.tui import TogglTUI


@pytest.fixture
def tui_data(tmp_data_dir, monkeypatch):
    """Set up test data, config, and frozen time for TUI tests."""
    import toggl.const
    import toggl.tui
    import toggl.cache
    import toggl.config

    from toggl.cache import get_week_dates

    # -- Config file at a temp path --
    config_path = os.path.join(tmp_data_dir, "toggl_config.json")
    monkeypatch.setattr(toggl.const, "CONFIG_FILE", config_path)
    monkeypatch.setattr(toggl.config, "CONFIG_FILE", config_path)
    config_data = {
        "points": {
            "Learning to Code": 1.5,
            "Building Projects": 2.0,
            "Fitness": 1.0,
        },
        "negatives": {"Procrastination": -3.0, "Junk Food": -2.0},
        "positives": {"Exercise": 3.0, "Reading": 2.0},
        "daily_target": 13.0,
    }
    with open(config_path, "w") as f:
        json.dump(config_data, f)

    # -- Weekly CSV --
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("Week,Project,Hours\n")
        f.write("2023-W01,Learning to Code,10.5\n")
        f.write("2023-W01,Building Projects,4.2\n")

    # -- Daily CSV (all 7 days of 2023-W01) --
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
# Tests
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mount_shows_overview_with_data(tui_data):
    """Overview view is active after mount and shows category data rows."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Overview view is the default (index 0)
        assert app.active_view_index == 0

        # Tab indicator matches
        tabs = app.query_one("#view-tabs")
        assert tabs.active == "tab-0"

        # Overview categories table has data
        cat_table = app.query_one("#overview-categories-table")
        assert cat_table.row_count >= 2

        # Recovery table exists
        rec_table = app.query_one("#overview-recovery-table")
        assert rec_table is not None


@pytest.mark.asyncio
async def test_app_launches_and_shows_default_view(tui_data):
    """App starts without crash; the default Overview view renders data."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Default active view is Overview (index 0)
        assert app.active_view_index == 0

        # Overview categories table renders data
        table = app.query_one("#overview-categories-table")
        assert table.row_count > 0

        # Ensure no exceptions in the overview
        overview_view = app.query_one("#overview-view")
        assert "-active" in overview_view.classes


@pytest.mark.asyncio
async def test_view_switching(tui_data):
    """Left / Right cycles through views; tab indicators update."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        assert app.active_view_index == 0

        app.action_next_view()
        await pilot.pause()
        assert app.active_view_index == 1
        tabs = app.query_one("#view-tabs")
        assert tabs.active == "tab-1"

        app.action_prev_view()
        await pilot.pause()
        assert app.active_view_index == 0
        assert tabs.active == "tab-0"


@pytest.mark.asyncio
async def test_view_navigation_wraps_around(tui_data):
    """Pressing right through all 3 views wraps back to Overview."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for _ in range(3):
            app.action_next_view()
            await pilot.pause()

        # Back at Overview after wrap-around
        assert app.active_view_index == 0
        overview_view = app.query_one("#overview-view")
        assert "-active" in overview_view.classes


@pytest.mark.asyncio
async def test_refresh_reloads_data(tui_data):
    """Pressing r refreshes all views without error."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_refresh_data()
        await pilot.pause()

        # Overview table still renders with data after refresh
        cat_table = app.query_one("#overview-categories-table")
        assert cat_table.row_count > 0


@pytest.mark.asyncio
async def test_footer_shows_keybindings(tui_data):
    """Footer displays navigation and action hints via built-in Footer widget."""
    from textual.widgets import Footer

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Textual's built-in Footer auto-renders BINDINGS as child widgets
        footer = app.query_one(Footer)
        keys = list(footer.children)
        assert len(keys) > 0

        # Each key binding widget has a 'description' attribute
        descriptions = [
            k.description for k in keys
            if hasattr(k, "description") and k.description
        ]
        desc_text = " ".join(d.lower() for d in descriptions)
        assert "neg" in desc_text
        assert "pos" in desc_text
        assert "prev" in desc_text
        assert "next" in desc_text


@pytest.mark.asyncio
async def test_all_views_render_without_error(tui_data):
    """All 3 views can be switched to without throwing exceptions."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for i in range(3):
            app.active_view_index = i
            app._refresh_view_by_index(i)
            app.update_view_visibility()
            await pilot.pause()

        # No exception means success


@pytest.mark.asyncio
async def test_sync_view_shows_status(tui_data):
    """Sync / Quota view renders status rows."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Navigate to Sync/Quota view (index 2)
        for _ in range(2):
            app.action_next_view()
            await pilot.pause()
        assert app.active_view_index == 2

        sync_table = app.query_one("#sync-table")
        assert sync_table.row_count > 0


@pytest.mark.asyncio
async def test_log_negative_via_tui(tui_data, monkeypatch):
    """Opening the negative modal shows an OptionList; confirming writes to CSV.

    (Modal interaction tested by opening screen + verifying OptionList populated.
    The actual log function is verified by calling it directly, with paths
    patched so it writes inside the temp data dir.)
    """
    import csv
    import toggl.const
    import toggl.neg

    # Ensure toggl.neg.NEGATIVES_CSV_FILE points to the temp path
    # (it may have been imported before monkeypatches were applied)
    monkeypatch.setattr(toggl.neg, "NEGATIVES_CSV_FILE", toggl.const.NEGATIVES_CSV_FILE)

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Open NegativeInputScreen — the modal screen is shown
        app.action_add_negative()
        await pilot.pause()

        from toggl.tui import NegativeInputScreen
        assert isinstance(app.screen, NegativeInputScreen)

        # Also verify the OptionList is populated with config data
        option_list = app.screen.query_one("#negative-list")
        assert option_list.option_count > 0

    # Verify the logging function itself works correctly
    # (this is the same code path triggered by the modal's after_input callback)
    ok, msg = toggl.neg.log_activity_direct("Procrastination", "negative")
    assert ok

    with open(toggl.const.NEGATIVES_CSV_FILE) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Negative"] == "Procrastination"


@pytest.mark.asyncio
async def test_log_positive_via_tui(tui_data, monkeypatch):
    """Opening the positive modal shows an OptionList; confirming writes to CSV."""
    import csv
    import toggl.const
    import toggl.neg

    monkeypatch.setattr(toggl.neg, "POSITIVES_CSV_FILE", toggl.const.POSITIVES_CSV_FILE)

    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Open PositiveInputScreen
        app.action_add_positive()
        await pilot.pause()

        from toggl.tui import PositiveInputScreen
        assert isinstance(app.screen, PositiveInputScreen)

        # OptionList populated
        option_list = app.screen.query_one("#positive-list")
        assert option_list.option_count > 0

    # Verify the logging function works (same code path as modal callback)
    ok, msg = toggl.neg.log_activity_direct("Exercise", "positive")
    assert ok

    with open(toggl.const.POSITIVES_CSV_FILE) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Positive"] == "Exercise"
