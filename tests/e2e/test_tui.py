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
        json.dump({
            "last_updated": "2023-01-02T10:00:00",
            "synced_weeks": {"2023-W01": "ok"},
            "synced_days": {},
        }, f)

    # -- Freeze time to Monday 2023-01-02 (2023-W01) --
    FAKE_TODAY = date(2023, 1, 2)

    class MockDate(date):
        @classmethod
        def today(cls):
            return FAKE_TODAY

    monkeypatch.setattr(toggl.tui, "date", MockDate)
    monkeypatch.setattr(toggl.cache, "date", MockDate)
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: False)

    return tmp_data_dir


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mount_shows_day_view_with_data(tui_data):
    """[REWRITTEN] Day view is active after mount and shows project data rows."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Day view container is active
        day_view = app.query_one("#day-view")
        assert "-active" in day_view.classes

        # Tab indicator matches Day
        tabs = app.query_one("#view-tabs")
        assert tabs.active == "tab-1"

        # Day table has project data (header + at least one project row)
        day_table = app.query_one("#day-table")
        assert day_table.row_count >= 2

        # A test project name appears in the data rows (sorted by rate desc)
        row1 = day_table.get_row_at(1)
        assert "Learning to Code" in str(row1[0]) or "Building Projects" in str(row1[0])


@pytest.mark.asyncio
async def test_app_launches_and_shows_default_view(tui_data):
    """[REWRITTEN] App starts without crash; the default Day view renders data."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        day_view = app.query_one("#day-view")
        assert "-active" in day_view.classes

        table = app.query_one("#day-table")
        assert table.row_count > 0

        # Spark rail also renders (right-side weeks/days/catchup)
        spark_weeks = app.query_one("#spark-weeks-table")
        assert spark_weeks.row_count > 0


@pytest.mark.asyncio
async def test_view_switching(tui_data):
    """Left / Right cycles through views; tab indicators update."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        assert app.active_view_index == 1

        app.action_next_view()
        await pilot.pause()
        assert app.active_view_index == 2
        tabs = app.query_one("#view-tabs")
        assert tabs.active == "tab-2"

        app.action_prev_view()
        await pilot.pause()
        assert app.active_view_index == 1
        assert tabs.active == "tab-1"


@pytest.mark.asyncio
async def test_view_navigation_wraps_around(tui_data):
    """Pressing right through all 9 views wraps back to Day (view 1)."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for _ in range(9):
            app.action_next_view()
            await pilot.pause()

        # Back at Day view after wrap-around
        assert app.active_view_index == 1
        day_view = app.query_one("#day-view")
        assert "-active" in day_view.classes


@pytest.mark.asyncio
async def test_day_week_sync(tui_data):
    """[REWRITTEN] Highlighting a week-table row updates the Day view data."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        initial_day = app.selected_day

        # Navigate to Week view (index 2)
        app.action_next_view()
        await pilot.pause()

        week_table = app.query_one("#week-table")
        assert week_table.row_count > 0

        # Highlight a different row
        await pilot.press("down")
        await pilot.pause()

        # The selected day should change (different date highlighted)
        assert app.selected_day != initial_day

        # Navigate back to Day view — still shows data for the new day
        app.action_prev_view()
        await pilot.pause()

        day_table = app.query_one("#day-table")
        assert day_table.row_count > 0


@pytest.mark.asyncio
async def test_week_navigation(tui_data):
    """Up / Down arrows move the cursor inside the week table."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_next_view()
        await pilot.pause()
        assert app.active_view_index == 2

        week_table = app.query_one("#week-table")
        assert week_table.row_count >= 2

        cursor_before = week_table.cursor_row

        await pilot.press("down")
        await pilot.pause()
        assert week_table.cursor_row != cursor_before

        await pilot.press("up")
        await pilot.pause()
        assert week_table.cursor_row == cursor_before


@pytest.mark.asyncio
async def test_refresh_reloads_data(tui_data):
    """Pressing r refreshes all views without error."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_refresh_data()
        await pilot.pause()

        # Day table still renders with data after refresh
        day_table = app.query_one("#day-table")
        assert day_table.row_count > 0


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
    """All 9 views can be switched to without throwing exceptions."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        for i in range(9):
            app.active_view_index = i
            app._refresh_view_by_index(i)
            app.update_view_visibility()
            await pilot.pause()

        # No exception means success


@pytest.mark.asyncio
async def test_sync_view_shows_backfill_status(tui_data):
    """Sync / Quota view renders a Backfill status row."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # 7 right-presses from Day(1) → Sync/Quota(8)
        for _ in range(7):
            app.action_next_view()
            await pilot.pause()
        assert app.active_view_index == 8

        sync_table = app.query_one("#sync-table")
        assert sync_table.row_count > 0

        found = any(
            "backfill" in sync_table.get_row_at(i)[0].lower()
            for i in range(sync_table.row_count)
        )
        assert found


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
    ok, msg = toggl.neg.log_negative_direct("Procrastination")
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
    ok, msg = toggl.neg.log_positive_direct("Exercise")
    assert ok

    with open(toggl.const.POSITIVES_CSV_FILE) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["Positive"] == "Exercise"




