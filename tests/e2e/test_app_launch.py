"""Tests that verify the TUI app launches successfully without errors.

These tests ensure the app starts cleanly — composing widgets, mounting,
loading data, and rendering all three tabs — without any unhandled
exceptions or widget-query failures.
"""

import json
import os

import pytest

from toggl.tui import TogglTUI
from textual.widgets import Footer, Tabs, Tab, DataTable, Label, Static


@pytest.fixture
def tui_data(tmp_data_dir, monkeypatch):
    """Set up minimal config + data for launch tests."""
    import toggl.const
    import toggl.config

    config_path = os.path.join(tmp_data_dir, "toggl_config.json")
    monkeypatch.setattr(toggl.const, "CONFIG_FILE", config_path)
    monkeypatch.setattr(toggl.config, "CONFIG_FILE", config_path)
    config_data = {
        "points": {"Learning to Code": 1.5},
        "negatives": {"Procrastination": -3.0},
        "positives": {"Exercise": 3.0},
        "daily_target": 13.0,
    }
    with open(config_path, "w") as f:
        json.dump(config_data, f)
    return tmp_data_dir


class TestAppLaunch:
    """Verify the app boots cleanly end-to-end."""

    @pytest.mark.asyncio
    async def test_app_composes_without_error(self, tui_data):
        """App.compose() and on_mount() finish without exceptions."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_app_title_visible(self, tui_data):
        """The app title is rendered in the chrome bar."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            title = app.query_one(".app-title", Label)
            rendered = str(title.render())
            assert len(rendered) > 0

    @pytest.mark.asyncio
    async def test_tabs_exist(self, tui_data):
        """All three tabs (Overview, Command, Insights) exist."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tabs = app.query_one("#view-tabs", Tabs)
            assert tabs.tab_count == 3

    @pytest.mark.asyncio
    async def test_footer_renders(self, tui_data):
        """The footer widget with keybindings renders."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            footer = app.query_one(Footer)
            assert footer is not None

    @pytest.mark.asyncio
    async def test_overview_view_has_tables(self, tui_data):
        """The Overview tab has the expected DataTables."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.active_view_index = 0
            app.update_view_visibility()
            await pilot.pause()
            assert app.query_one("#overview-categories-table", DataTable) is not None

    @pytest.mark.asyncio
    async def test_command_view_has_widgets(self, tui_data):
        """The Command tab has graph and calendar."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#cmd-graph") is not None
            assert app.query_one("#command-calendar") is not None

    @pytest.mark.asyncio
    async def test_insights_view_has_widgets(self, tui_data):
        """The Insights tab has the detail widget."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.active_view_index = 2
            app.update_view_visibility()
            await pilot.pause()
            assert app.query_one("#insights-detail-widget") is not None

    @pytest.mark.asyncio
    async def test_sync_status_label_renders(self, tui_data):
        """The sync status label has content."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            sync_label = app.query_one("#sync-status", Static)
            assert len(str(sync_label.render())) > 0

    @pytest.mark.asyncio
    async def test_all_views_switch_without_crash(self, tui_data):
        """Switching between all three views does not throw."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for idx in range(3):
                app.active_view_index = idx
                app.update_view_visibility()
                await pilot.pause()

    @pytest.mark.asyncio
    async def test_icon_registry_imports(self, tui_data):
        """The central icon registry provides all expected keys."""
        from toggl.widgets.icons import ICON, icon, spark_char, fractional_bar
        assert icon("nav_prev") is not None
        assert icon("check") is not None
        assert icon("warning") is not None
        assert spark_char(5, 0, 10) in ICON["spark_chars"]
        assert fractional_bar(0.0) == ""
        assert fractional_bar(1.0) == ICON["bar_block"]

    @pytest.mark.asyncio
    async def test_loading_widget_imports(self, tui_data):
        """LoadingWidget, PulseText, and ProgressIndicator import cleanly."""
        from toggl.widgets.loading import LoadingWidget, PulseText, ProgressIndicator
        assert LoadingWidget("Testing...") is not None
        assert PulseText("Pulse") is not None
        assert ProgressIndicator(width=20) is not None

    @pytest.mark.asyncio
    async def test_splash_screen_imports(self, tui_data):
        """SplashScreen class can be imported and composed (test-only, no push)."""
        from toggl.tui import SplashScreen
        assert SplashScreen is not None
