"""Visual regression tests using pytest-textual-snapshot.

These tests capture SVG screenshots of each view and compare against baselines.
Run with --snapshot-update to generate/update baselines.
"""

import pytest
from textual.pilot import Pilot

from toggl.tui import TogglTUI


@pytest.fixture
def app_with_data(tmp_data_dir, sample_config, sample_daily_csv, sample_weekly_csv):
    """Create app instance with test data."""
    return TogglTUI()


class TestViewSnapshots:
    """Snapshot tests for each view."""

    def test_day_view_snapshot(self, snap_compare, app_with_data):
        """Day view renders correctly."""
        assert snap_compare(app_with_data, terminal_size=(120, 40))

    def test_week_view_snapshot(self, snap_compare, app_with_data):
        """Week view renders correctly."""
        async def navigate_to_week(pilot: Pilot):
            await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_week,
            terminal_size=(120, 40)
        )

    def test_overview_view_snapshot(self, snap_compare, app_with_data):
        """Overview view renders correctly."""
        async def navigate_to_overview(pilot: Pilot):
            await pilot.press("ctrl+left")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_overview,
            terminal_size=(120, 40)
        )

    def test_month_view_snapshot(self, snap_compare, app_with_data):
        """Month view renders correctly."""
        async def navigate_to_month(pilot: Pilot):
            # Navigate to month view (3rd view)
            await pilot.press("ctrl+right")
            await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_month,
            terminal_size=(120, 40)
        )

    def test_heatmap_view_snapshot(self, snap_compare, app_with_data):
        """Heatmap view renders correctly."""
        async def navigate_to_heatmap(pilot: Pilot):
            # Navigate to heatmap view (4th view)
            for _ in range(3):
                await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_heatmap,
            terminal_size=(120, 40)
        )

    def test_negatives_view_snapshot(self, snap_compare, app_with_data):
        """Negatives view renders correctly."""
        async def navigate_to_negatives(pilot: Pilot):
            # Navigate to negatives view (5th view)
            for _ in range(4):
                await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_negatives,
            terminal_size=(120, 40)
        )

    def test_positives_view_snapshot(self, snap_compare, app_with_data):
        """Positives view renders correctly."""
        async def navigate_to_positives(pilot: Pilot):
            # Navigate to positives view (6th view)
            for _ in range(5):
                await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_positives,
            terminal_size=(120, 40)
        )

    def test_recovery_view_snapshot(self, snap_compare, app_with_data):
        """Recovery view renders correctly."""
        async def navigate_to_recovery(pilot: Pilot):
            # Navigate to recovery view (7th view)
            for _ in range(6):
                await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_recovery,
            terminal_size=(120, 40)
        )

    def test_sync_view_snapshot(self, snap_compare, app_with_data):
        """Sync view renders correctly."""
        async def navigate_to_sync(pilot: Pilot):
            # Navigate to sync view (8th view)
            for _ in range(7):
                await pilot.press("ctrl+right")
        
        assert snap_compare(
            app_with_data,
            run_before=navigate_to_sync,
            terminal_size=(120, 40)
        )


class TestInteractionSnapshots:
    """Snapshot tests for user interactions."""

    def test_negative_modal_snapshot(self, snap_compare, app_with_data):
        """Negative input modal renders correctly."""
        async def open_negative_modal(pilot: Pilot):
            await pilot.press("n")
        
        assert snap_compare(
            app_with_data,
            run_before=open_negative_modal,
            terminal_size=(120, 40)
        )

    def test_positive_modal_snapshot(self, snap_compare, app_with_data):
        """Positive input modal renders correctly."""
        async def open_positive_modal(pilot: Pilot):
            await pilot.press("p")
        
        assert snap_compare(
            app_with_data,
            run_before=open_positive_modal,
            terminal_size=(120, 40)
        )

    def test_week_row_highlighted_snapshot(self, snap_compare, app_with_data):
        """Week view with highlighted row renders correctly."""
        async def highlight_week_row(pilot: Pilot):
            await pilot.press("ctrl+right")  # Go to week view
            await pilot.press("down")  # Highlight a row
        
        assert snap_compare(
            app_with_data,
            run_before=highlight_week_row,
            terminal_size=(120, 40)
        )


class TestResponsiveSnapshots:
    """Snapshot tests at different terminal sizes."""

    def test_small_terminal_snapshot(self, snap_compare, app_with_data):
        """App renders correctly at 80x24."""
        assert snap_compare(app_with_data, terminal_size=(80, 24))

    def test_large_terminal_snapshot(self, snap_compare, app_with_data):
        """App renders correctly at 200x60."""
        assert snap_compare(app_with_data, terminal_size=(200, 60))

    def test_wide_terminal_snapshot(self, snap_compare, app_with_data):
        """App renders correctly at 160x40."""
        assert snap_compare(app_with_data, terminal_size=(160, 40))


class TestEmptyStateSnapshots:
    """Snapshot tests for empty data states."""

    def test_empty_day_view_snapshot(self, snap_compare, tmp_data_dir, sample_config):
        """Day view with no data renders gracefully."""
        import toggl.const
        
        # Clear daily data
        with open(toggl.const.DAILY_CSV_FILE, 'w') as f:
            f.write('Date,Project,Hours\n')
        
        app = TogglTUI()
        assert snap_compare(app, terminal_size=(120, 40))

    def test_empty_week_view_snapshot(self, snap_compare, tmp_data_dir, sample_config):
        """Week view with no data renders gracefully."""
        import toggl.const
        
        # Clear weekly data
        with open(toggl.const.CSV_FILE, 'w') as f:
            f.write('Week,Project,Hours\n')
        
        app = TogglTUI()
        
        async def navigate_to_week(pilot: Pilot):
            await pilot.press("ctrl+right")
        
        assert snap_compare(
            app,
            run_before=navigate_to_week,
            terminal_size=(120, 40)
        )
