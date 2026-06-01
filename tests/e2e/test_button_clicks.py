"""Button click tests for TogglTUI — tests all interactive button elements.

Covers:
  - OverviewPanel: Log Neg, Log Pos buttons
  - CommandTab: prev/next nav, period/scale/metric cycle buttons
  - CalendarWidget: prev/next month buttons
  - Dialogs: confirm/cancel buttons in ConfirmScreen, NegativeInputScreen,
    PositiveInputScreen
"""

import json
import os
from datetime import date, timedelta

import pytest

from toggl.tui import TogglTUI


@pytest.fixture
def tui_data(tmp_data_dir, monkeypatch):
    """Set up test data, config, and frozen time for button click tests."""
    import toggl.const
    import toggl.cache
    import toggl.config
    import toggl.tui
    import toggl.state.period
    from toggl.cache import get_week_dates

    config_path = os.path.join(tmp_data_dir, "toggl_config.json")
    monkeypatch.setattr(toggl.const, "CONFIG_FILE", config_path)
    monkeypatch.setattr(toggl.config, "CONFIG_FILE", config_path)
    config_data = {
        "points": {"Learning to Code": 1.5, "Building Projects": 2.0},
        "negatives": {"Procrastination": -3.0, "Junk Food": -2.0},
        "positives": {"Exercise": 3.0, "Reading": 2.0},
        "daily_target": 13.0,
    }
    with open(config_path, "w") as f:
        json.dump(config_data, f)

    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("Week,Project,Hours\n")
        f.write("2023-W01,Learning to Code,10.5\n")
        f.write("2023-W01,Building Projects,4.2\n")

    start_d, _ = get_week_dates("2023-W01")
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("Date,Project,Hours\n")
        for i in range(7):
            d = (start_d + timedelta(days=i)).strftime("%Y-%m-%d")
            f.write(f"{d},Learning to Code,1.5\n")
            f.write(f"{d},Building Projects,0.6\n")

    with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
        f.write("Date,Negative,Points\n")
    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")
    with open(toggl.const.HISTORY_FILE, "w") as f:
        json.dump({"last_updated": None}, f)

    FAKE_TODAY = date(2023, 1, 2)

    class MockDate(date):
        @classmethod
        def today(cls):
            return FAKE_TODAY

    monkeypatch.setattr(toggl.tui, "date", MockDate)
    monkeypatch.setattr(toggl.cache, "date", MockDate)
    monkeypatch.setattr(toggl.state.period, "date", MockDate)
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: False)

    return tmp_data_dir


class TestOverviewButtons:
    """Test Log Neg / Log Pos buttons in OverviewPanel."""

    @pytest.mark.asyncio
    async def test_neg_log_button_opens_negative_modal(self, tui_data):
        """Clicking Log Neg opens the NegativeInputScreen modal."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await pilot.click("#btn-neg-log")
            await pilot.pause()

            from toggl.screens.dialogs import NegativeInputScreen
            assert isinstance(app.screen, NegativeInputScreen)

    @pytest.mark.asyncio
    async def test_pos_log_button_opens_positive_modal(self, tui_data):
        """Clicking Log Pos opens the PositiveInputScreen modal."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await pilot.click("#btn-pos-log")
            await pilot.pause()

            from toggl.screens.dialogs import PositiveInputScreen
            assert isinstance(app.screen, PositiveInputScreen)


class TestCommandTabButtons:
    """Test navigation and cycle buttons in CommandTab.

    These tests switch to the Command view (index 1) first.
    """

    @pytest.mark.asyncio
    async def test_cmd_prev_button_navigates_back(self, tui_data):
        """Clicking <<< decrements the period offset."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            from toggl.command import CommandTab
            cmd = app.query_one(CommandTab)
            assert cmd.period._offset == 0

            await pilot.click("#cmd-prev")
            await pilot.pause()

            assert cmd.period._offset == -1

    @pytest.mark.asyncio
    async def test_cmd_next_button_navigates_forward(self, tui_data):
        """Clicking >>> increments the period offset (when offset < 0)."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            from toggl.command import CommandTab
            cmd = app.query_one(CommandTab)

            await pilot.click("#cmd-prev")
            await pilot.pause()
            assert cmd.period._offset == -1

            await pilot.click("#cmd-next")
            await pilot.pause()
            assert cmd.period._offset == 0

    @pytest.mark.asyncio
    async def test_cmd_cycle_period_cycles_mode(self, tui_data):
        """Clicking View: Day ↻ cycles Day -> Week -> Month -> Day."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            period_btn = app.query_one("#cmd-cycle-period")
            assert "Day" in str(period_btn.label)

            await pilot.click("#cmd-cycle-period")
            await pilot.pause(0.15)
            assert "Week" in str(period_btn.label)

            await pilot.click("#cmd-cycle-period")
            await pilot.pause(0.15)
            assert "Month" in str(period_btn.label)

            await pilot.click("#cmd-cycle-period")
            await pilot.pause(0.15)
            assert "Day" in str(period_btn.label)

    @pytest.mark.asyncio
    async def test_cmd_cycle_scale_cycles_scale(self, tui_data):
        """Clicking Range: 7d ↻ cycles through scale options."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            scale_btn = app.query_one("#cmd-cycle-scale")
            assert "7d" in str(scale_btn.label)

            await pilot.click("#cmd-cycle-scale")
            await pilot.pause()
            assert "30d" in str(scale_btn.label)

    @pytest.mark.asyncio
    async def test_cmd_cycle_metric_cycles_metric(self, tui_data):
        """Clicking Metric: Net ↻ cycles Net -> Pos -> Neg -> Net."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            metric_btn = app.query_one("#cmd-cycle-metric")
            assert "Net" in str(metric_btn.label)

            await pilot.click("#cmd-cycle-metric")
            await pilot.pause(0.15)
            assert "Pos" in str(metric_btn.label)

            await pilot.click("#cmd-cycle-metric")
            await pilot.pause(0.15)
            assert "Neg" in str(metric_btn.label)

            await pilot.click("#cmd-cycle-metric")
            await pilot.pause(0.15)
            assert "Net" in str(metric_btn.label)


class TestCalendarButtons:
    """Test prev/next month buttons in CalendarWidget."""

    @pytest.mark.asyncio
    async def test_calendar_prev_month_button(self, tui_data):
        """Clicking << in calendar navigates to the previous month."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            from toggl.widgets.calendar import CalendarWidget
            cal = app.query_one(CalendarWidget)
            assert cal._display_month == 1

            await pilot.click("#cal-prev-month")
            await pilot.pause()
            assert cal._display_month == 12
            assert cal._display_year == 2022

    @pytest.mark.asyncio
    async def test_calendar_next_month_button(self, tui_data):
        """Clicking >> in calendar navigates to the next month."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_next_view()
            await pilot.pause()

            from toggl.widgets.calendar import CalendarWidget
            cal = app.query_one(CalendarWidget)

            await pilot.click("#cal-prev-month")
            await pilot.pause()
            assert cal._display_month == 12
            assert cal._display_year == 2022

            await pilot.click("#cal-next-month")
            await pilot.pause()
            assert cal._display_month == 1
            assert cal._display_year == 2023


class TestDialogButtons:
    """Test confirm/cancel buttons in modal dialogs."""

    @pytest.mark.asyncio
    async def test_confirm_screen_confirm_button(self, tui_data):
        """Clicking confirm on ConfirmScreen dismisses it."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            app.action_sync_current_week()
            await pilot.pause()

            from toggl.screens.dialogs import ConfirmScreen
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#btn-confirm")
            await pilot.pause()
            await pilot.pause()

            assert not isinstance(app.screen, ConfirmScreen)

    @pytest.mark.asyncio
    async def test_confirm_screen_cancel_button(self, tui_data):
        """Clicking cancel on ConfirmScreen dismisses it."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            app.action_sync_current_week()
            await pilot.pause()

            from toggl.screens.dialogs import ConfirmScreen
            assert isinstance(app.screen, ConfirmScreen)

            await pilot.click("#btn-cancel")
            await pilot.pause()

            assert not isinstance(app.screen, ConfirmScreen)

    @pytest.mark.asyncio
    async def test_negative_modal_cancel_button(self, tui_data):
        """Clicking cancel on NegativeInputScreen dismisses it."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            app.action_add_negative()
            await pilot.pause()

            from toggl.screens.dialogs import NegativeInputScreen
            assert isinstance(app.screen, NegativeInputScreen)

            await pilot.click("#btn-cancel")
            await pilot.pause()

            assert not isinstance(app.screen, NegativeInputScreen)

    @pytest.mark.asyncio
    async def test_positive_modal_cancel_button(self, tui_data):
        """Clicking cancel on PositiveInputScreen dismisses it."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            app.action_add_positive()
            await pilot.pause()

            from toggl.screens.dialogs import PositiveInputScreen
            assert isinstance(app.screen, PositiveInputScreen)

            await pilot.click("#btn-cancel")
            await pilot.pause()

            assert not isinstance(app.screen, PositiveInputScreen)
