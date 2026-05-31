"""Unit tests for PeriodController and Command tab data methods."""

import pytest
from datetime import date, timedelta
from unittest.mock import patch

from toggl.period import PeriodController, PeriodMode


class TestPeriodController:
    """Tests for PeriodController date navigation."""

    def test_initial_state(self):
        pc = PeriodController()
        assert pc.mode == PeriodMode.DAY
        assert pc.scale == 7
        assert pc.scale_index == 0
        assert pc.scale_label == "7d"

    def test_day_mode_range(self):
        pc = PeriodController()
        # offset=0, scale=7: range should end today
        start, end = pc.get_visible_range()
        assert end == date.today()
        assert (end - start).days == 6  # 7 days inclusive

    def test_previous_day(self):
        pc = PeriodController()
        pc.previous()  # offset = -1
        start, end = pc.get_visible_range()
        assert end == date.today() - timedelta(days=1)
        assert (end - start).days == 6

    def test_next_capped(self):
        pc = PeriodController()
        pc.next()  # should cap at 0
        start, end = pc.get_visible_range()
        assert end == date.today()  # still today

    def test_next_from_past(self):
        pc = PeriodController()
        pc.previous()
        pc.previous()  # offset = -2
        pc.next()  # offset = -1
        start, end = pc.get_visible_range()
        assert end == date.today() - timedelta(days=1)

    def test_zoom_day_scales(self):
        pc = PeriodController()
        assert pc.scale == 7
        pc.zoom_out()
        assert pc.scale == 30
        pc.zoom_out()
        assert pc.scale == 90
        pc.zoom_out()
        assert pc.scale == 365
        pc.zoom_out()  # at max, no-op
        assert pc.scale == 365
        pc.zoom_in()
        assert pc.scale == 90
        pc.zoom_in()
        pc.zoom_in()
        assert pc.scale == 7
        pc.zoom_in()  # at min, no-op
        assert pc.scale == 7

    def test_zoom_week_scales(self):
        pc = PeriodController()
        pc.mode = PeriodMode.WEEK
        assert pc.scale == 4
        pc.zoom_out()
        pc.zoom_out()
        pc.zoom_out()
        assert pc.scale == 52
        pc.zoom_in()
        pc.zoom_in()
        assert pc.scale == 13

    def test_mode_switch_resets(self):
        pc = PeriodController()
        pc.zoom_out()
        pc.zoom_out()
        assert pc.scale == 90
        pc.mode = PeriodMode.WEEK
        assert pc.scale == 4  # reset
        assert pc.scale_index == 0
        pc.mode = PeriodMode.DAY
        assert pc.scale == 7

    def test_week_mode_range(self):
        pc = PeriodController()
        pc.mode = PeriodMode.WEEK
        start, end = pc.get_visible_range()
        assert isinstance(start, date)
        assert isinstance(end, date)
        # 4 weeks = 28 days
        assert (end - start).days == 27  # 4*7-1

    def test_set_from_day(self):
        pc = PeriodController()
        target = date.today() - timedelta(days=10)
        pc.set_from_day(target)
        assert pc.mode == PeriodMode.DAY
        start, end = pc.get_visible_range()
        assert end == target

    def test_set_from_week(self):
        pc = PeriodController()
        target = date.today() - timedelta(days=10)
        pc.set_from_week(target)
        assert pc.mode == PeriodMode.WEEK
        assert pc.scale == 4  # reset

    def test_month_mode(self):
        pc = PeriodController()
        pc.mode = PeriodMode.MONTH
        assert pc.mode == PeriodMode.MONTH
        assert pc.scale == 3
        assert pc.scale_label == "3m"
        pc.zoom_out()
        assert pc.scale == 6
        assert pc.scale_label == "6m"
        pc.zoom_out()
        assert pc.scale == 12
        assert pc.scale_label == "12m"

    def test_set_scale(self):
        pc = PeriodController()
        pc.set_scale(90)
        assert pc.scale == 90
        pc.set_scale(7)
        assert pc.scale == 7
        pc.set_scale(999)  # invalid, no-op
        assert pc.scale == 7

    def test_day_period_labels(self):
        pc = PeriodController()
        assert pc.get_period_label() == "Today"
        pc.previous()
        assert pc.get_period_label() == "Yesterday"
        pc.previous()
        pc.previous()
        # Should be a formatted date
        label = pc.get_period_label()
        assert "," in label  # e.g. "May 29, 2026"

    def test_week_period_labels(self):
        pc = PeriodController()
        pc.mode = PeriodMode.WEEK
        assert pc.get_period_label() == "This Week"
        pc.previous()
        assert pc.get_period_label() == "Last Week"

    def test_scale_label(self):
        pc = PeriodController()
        assert pc.scale_label == "7d"
        pc.mode = PeriodMode.WEEK
        assert pc.scale_label == "4w"
        pc.zoom_out()
        assert pc.scale_label == "13w"


class TestDailyDataForRange:
    """Tests for DataCache.get_daily_data_for_range()."""

    def test_empty_range(self, tmp_data_dir, sample_config):
        from toggl.cache import DataCache
        cache = DataCache.load()
        today = date.today()
        data = cache.get_daily_data_for_range(today, today)
        assert len(data) == 1
        assert data[0]["date"] == today.strftime("%Y-%m-%d")
        assert data[0]["has_data"] is False
        assert data[0]["net"] == 0.0

    def test_with_daily_data(self, tmp_data_dir, sample_daily_csv, sample_config):
        from toggl.cache import DataCache
        cache = DataCache.load()
        # 2023-W01 dates from fixture
        from toggl.cache import get_week_dates
        start, end = get_week_dates("2023-W01")
        data = cache.get_daily_data_for_range(start, end)
        # Should have 7 entries
        assert len(data) == 7
        # Each should have all fields
        for d in data:
            assert "date" in d
            assert "net" in d
            assert "positive" in d
            assert "negative" in d
            assert "logged_pos" in d
            assert "logged_neg" in d
            assert "has_data" in d
        # First day should have data
        assert data[0]["has_data"] is True

    def test_future_days_zero(self, tmp_data_dir, sample_config):
        from toggl.cache import DataCache
        cache = DataCache.load()
        today = date.today()
        future = today + timedelta(days=5)
        data = cache.get_daily_data_for_range(today, future)
        assert len(data) == 6
        for d in data:
            assert d["has_data"] is False
            assert d["net"] == 0.0
            assert d["positive"] == 0.0
            assert d["negative"] == 0.0

    def test_with_logged_positives(self, tmp_data_dir, sample_config):
        from toggl.cache import DataCache
        import toggl.const
        with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
            f.write("Date,Positive,Points\n")
            f.write("2023-01-02,Exercise,3.0\n")
            f.write("2023-01-02,Reading,2.0\n")
        cache = DataCache.load()
        data = cache.get_daily_data_for_range(
            date(2023, 1, 1), date(2023, 1, 3)
        )
        assert data[1]["logged_pos"] == 5.0  # 3.0 + 2.0
        assert data[1]["has_data"] is True

    def test_net_computation(self, tmp_data_dir, sample_daily_csv, sample_config):
        from toggl.cache import DataCache
        cache = DataCache.load()
        # Get a single day with known data
        data = cache.get_daily_data_for_range(
            date(2023, 1, 1), date(2023, 1, 1)
        )
        d = data[0]
        # net = earned - tracked_neg - logged_neg + logged_pos
        expected = d["positive"] - d["negative"]
        assert d["net"] == pytest.approx(expected, rel=1e-2)


class TestGraphScalingAndTicks:
    """Tests for nice yticks and cumulative average logic."""

    def test_nice_yticks_positive_free_floating(self):
        from toggl.graph import _nice_yticks
        ymin, ymax, ticks = _nice_yticks(12.5, 45.2)
        # Should start <= 12.5 and end >= 45.2
        assert ymin <= 12.5
        assert ymax >= 45.2
        # Ticks should be evenly spaced and nice integers/decimals
        assert len(ticks) >= 3
        for i in range(len(ticks) - 1):
            assert pytest.approx(ticks[i+1] - ticks[i]) == ticks[1] - ticks[0]

    def test_nice_yticks_negative_to_positive(self):
        from toggl.graph import _nice_yticks
        ymin, ymax, ticks = _nice_yticks(-796, 69)
        assert ymin <= -796
        assert ymax >= 69
        assert len(ticks) >= 3
        # Should include nice round intervals (like multiples of 100 or 200)
        assert ticks[1] - ticks[0] in [100, 200, 250, 500]

    def test_nice_yticks_degenerate(self):
        from toggl.graph import _nice_yticks
        ymin, ymax, ticks = _nice_yticks(0.0, 0.0)
        assert ymin < ymax
        assert len(ticks) >= 3
        assert 0.0 in ticks

    def test_nice_yticks_degenerate_nonzero(self):
        from toggl.graph import _nice_yticks
        ymin, ymax, ticks = _nice_yticks(10.0, 10.0)
        assert ymin < 10.0
        assert ymax > 10.0
        assert len(ticks) >= 3

