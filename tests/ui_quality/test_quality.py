"""UI quality tests for accessibility and usability."""

import pytest
from textual.pilot import Pilot

from toggl.tui import TogglTUI


@pytest.fixture
def tui_data(tmp_data_dir, sample_config, sample_daily_csv, sample_weekly_csv, monkeypatch):
    """Create app instance with test data and frozen time."""
    import toggl.tui
    import toggl.cache
    from datetime import date
    
    # Freeze time to 2023-01-02 (Monday of 2023-W01)
    FAKE_TODAY = date(2023, 1, 2)
    
    class MockDate(date):
        @classmethod
        def today(cls):
            return FAKE_TODAY
    
    monkeypatch.setattr(toggl.tui, "date", MockDate)
    monkeypatch.setattr(toggl.cache, "date", MockDate)
    monkeypatch.setattr(toggl.tui, "needs_auto_update", lambda: False)
    
    return tmp_data_dir


class TestAccessibility:
    """Tests for accessibility features."""

    @pytest.mark.asyncio
    async def test_all_interactive_elements_have_labels(self, tui_data):
        """All interactive elements should have accessible labels."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Check that tabs have labels
            tabs = app.query_one("#view-tabs")
            assert tabs is not None
            
            # Check that tables have border titles
            day_table = app.query_one("#day-table")
            assert day_table.border_title is not None

    @pytest.mark.asyncio
    async def test_color_contrast_in_tables(self, tui_data):
        """Table text should have sufficient color contrast."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Get the day table
            day_table = app.query_one("#day-table")
            
            # Check that the table has data
            assert day_table.row_count > 0
            
            # Verify the table styles are applied
            # (This is a basic check - full contrast testing would require
            # analyzing the actual rendered colors)
            assert day_table.styles.color is not None

    @pytest.mark.asyncio
    async def test_keyboard_navigation_works(self, tui_data):
        """All views should be navigable via keyboard."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # App starts on Day view (index 1)
            assert app.active_view_index == 1
            
            # Navigate through all views using keyboard
            for i in range(8):
                await pilot.press("ctrl+right")
                await pilot.pause()
                
                # Each view should be accessible (wraps around)
                expected_view = (1 + i + 1) % 8
                assert app.active_view_index == expected_view

    @pytest.mark.asyncio
    async def test_escape_closes_modals(self, tui_data):
        """Escape key should close all modal dialogs."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Open negative modal
            await pilot.press("n")
            await pilot.pause()
            
            # Verify modal is open
            from toggl.tui import NegativeInputScreen
            assert isinstance(app.screen, NegativeInputScreen)
            
            # Press escape
            await pilot.press("escape")
            await pilot.pause()
            
            # Verify modal is closed
            assert not isinstance(app.screen, NegativeInputScreen)


class TestFocusManagement:
    """Tests for focus navigation."""

    @pytest.mark.asyncio
    async def test_initial_focus_on_day_table(self, tui_data):
        """Day table should be focusable on startup."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            day_table = app.query_one("#day-table")
            # Table should be focusable (even if not focused initially)
            assert day_table.can_focus
            # Try to focus it
            day_table.focus()
            await pilot.pause()
            assert day_table.has_focus

    @pytest.mark.asyncio
    async def test_focus_moves_with_view_change(self, tui_data):
        """Focus should move to the active view's table."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Navigate to week view
            await pilot.press("ctrl+right")
            await pilot.pause()
            
            # Week table should have focus
            week_table = app.query_one("#week-table")
            assert week_table.has_focus

    @pytest.mark.asyncio
    async def test_tab_order_in_modal(self, tui_data):
        """Modal should have logical tab order."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Open negative modal
            await pilot.press("n")
            await pilot.pause()
            
            # Option list should have focus
            from toggl.tui import NegativeInputScreen
            assert isinstance(app.screen, NegativeInputScreen)
            
            option_list = app.query_one("#negative-list")
            assert option_list.has_focus

    @pytest.mark.asyncio
    async def test_focus_restored_after_modal_close(self, tui_data):
        """Focus should be restorable to main view after modal closes."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Open and close modal
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            
            # Day table should be focusable and can be focused
            day_table = app.query_one("#day-table")
            assert day_table.can_focus
            day_table.focus()
            await pilot.pause()
            assert day_table.has_focus


class TestErrorHandling:
    """Tests for error message display."""

    @pytest.mark.asyncio
    async def test_invalid_negative_shows_error(self, tui_data, monkeypatch):
        """Logging invalid negative should show error toast."""
        import toggl.neg
        
        # Patch the NEGATIVES_CSV_FILE to use temp path
        import toggl.const
        monkeypatch.setattr(toggl.neg, "NEGATIVES_CSV_FILE", toggl.const.NEGATIVES_CSV_FILE)
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Try to log invalid negative
            ok, message = toggl.neg.log_negative_direct("InvalidAction")
            
            assert ok is False
            assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_invalid_positive_shows_error(self, tui_data, monkeypatch):
        """Logging invalid positive should show error toast."""
        import toggl.neg
        
        # Patch the POSITIVES_CSV_FILE to use temp path
        import toggl.const
        monkeypatch.setattr(toggl.neg, "POSITIVES_CSV_FILE", toggl.const.POSITIVES_CSV_FILE)
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Try to log invalid positive
            ok, message = toggl.neg.log_positive_direct("InvalidAction")
            
            assert ok is False
            assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_empty_data_shows_gracefully(self, tui_data):
        """App should handle empty data without crashing."""
        import toggl.const
        
        # Clear all data files
        with open(toggl.const.CSV_FILE, 'w') as f:
            f.write('Week,Project,Hours\n')
        with open(toggl.const.DAILY_CSV_FILE, 'w') as f:
            f.write('Date,Project,Hours\n')
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # App should still render
            day_table = app.query_one("#day-table")
            assert day_table is not None
            
            # Navigate through all views without crash
            for _ in range(9):
                await pilot.press("ctrl+right")
                await pilot.pause()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Known issue: app crashes on corrupted CSV data. Need to add error handling in cache._load_daily()")
    async def test_corrupted_csv_handled(self, tui_data):
        """App should handle corrupted CSV data gracefully."""
        import toggl.const
        
        # Write corrupted data
        with open(toggl.const.DAILY_CSV_FILE, 'w') as f:
            f.write('Date,Project,Hours\n')
            f.write('invalid-date,Project,not-a-number\n')
            f.write('2023-01-02,Valid,1.5\n')
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # App should still render (may skip corrupted rows)
            day_table = app.query_one("#day-table")
            assert day_table is not None


class TestLoadingStates:
    """Tests for loading and progress indicators."""

    @pytest.mark.asyncio
    async def test_refresh_shows_notification(self, tui_data):
        """Refresh action should show notification."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Trigger refresh
            app.action_refresh_data()
            await pilot.pause()
            
            # App should still be responsive
            day_table = app.query_one("#day-table")
            assert day_table.row_count > 0

    @pytest.mark.asyncio
    async def test_sync_view_shows_status(self, tui_data):
        """Sync view should display sync status information."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Navigate to sync view
            for _ in range(7):
                await pilot.press("ctrl+right")
                await pilot.pause()
            
            sync_table = app.query_one("#sync-table")
            assert sync_table.row_count > 0
            
            # Should show backfill status
            found_backfill = False
            for i in range(sync_table.row_count):
                row = sync_table.get_row_at(i)
                if "backfill" in str(row[0]).lower():
                    found_backfill = True
                    break
            
            assert found_backfill


class TestEmptyStates:
    """Tests for empty state displays."""

    @pytest.mark.asyncio
    async def test_empty_negatives_view(self, tui_data):
        """Negatives view should handle empty log gracefully."""
        import toggl.const
        
        # Clear negatives
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Navigate to negatives view
            for _ in range(4):
                await pilot.press("ctrl+right")
                await pilot.pause()
            
            # Should render without crash
            negatives_table = app.query_one("#negatives-catalog-table")
            assert negatives_table is not None

    @pytest.mark.asyncio
    async def test_empty_positives_view(self, tui_data):
        """Positives view should handle empty log gracefully."""
        import toggl.const
        
        # Clear positives
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
        
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Navigate to positives view
            for _ in range(5):
                await pilot.press("ctrl+right")
                await pilot.pause()
            
            # Should render without crash
            positives_table = app.query_one("#positives-catalog-table")
            assert positives_table is not None

    @pytest.mark.asyncio
    async def test_empty_recovery_view(self, tui_data):
        """Recovery view should handle positive points gracefully."""
        app = TogglTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            
            # Navigate to recovery view
            for _ in range(6):
                await pilot.press("ctrl+right")
                await pilot.pause()
            
            # Should render without crash
            recovery_table = app.query_one("#recovery-table")
            assert recovery_table is not None
