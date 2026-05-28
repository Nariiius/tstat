"""Textual Pilot E2E tests for TogglTUI."""

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
    # Both toggl.const and toggl.config hold module-level references
    # to CONFIG_FILE, so patch both.
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
    for fp in [toggl.const.NEGATIVES_CSV_FILE, toggl.const.POSITIVES_CSV_FILE]:
        with open(fp, "w") as f:
            f.write("Date,Negative,Points\n")

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
async def test_app_launches_and_shows_default_view(tui_data):
    """App starts without crash; the default Day view is active."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        assert app.active_view_index == 1

        day_view = app.query_one("#day-view")
        assert "-active" in day_view.classes

        day_table = app.query_one("#day-table")
        assert day_table.row_count > 0

        tab = app.query_one("#view-tab-1")
        assert "-active" in tab.classes


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
        assert "-active" in app.query_one("#view-tab-2").classes
        assert "-active" not in app.query_one("#view-tab-1").classes

        app.action_prev_view()
        await pilot.pause()
        assert app.active_view_index == 1
        assert "-active" in app.query_one("#view-tab-1").classes


@pytest.mark.asyncio
async def test_day_week_sync(tui_data):
    """Highlighting a week-table row updates the Day view."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        app.action_next_view()
        await pilot.pause()
        assert app.active_view_index == 2

        week_table = app.query_one("#week-table")
        assert week_table.row_count > 0

        initial_day = app.selected_day

        await pilot.press("down")
        await pilot.pause()

        assert app.selected_day != initial_day

        app.action_prev_view()
        await pilot.pause()
        assert app.active_view_index == 1

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
async def test_sync_view_shows_backfill_status(tui_data):
    """Sync / Quota view renders a Backfill status row."""
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # 9 views: Overview(0) → Day(1) → Week(2) → Month(3) → Heatmap(4)
        # → Negatives(5) → Positives(6) → Recovery(7) → Sync/Quota(8)
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
