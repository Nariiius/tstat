"""Unit tests for MetricsService business logic.

MetricsService composes DataCache queries into higher-level metrics.
These tests verify each method independently using CSV fixtures.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from toggl.cache import DataCache
from toggl.services.metrics import MetricsService


def _make_svc() -> MetricsService:
    """Create MetricsService with loaded cache using current config globals."""
    import toggl.config
    return MetricsService(
        DataCache.load(),
        dict(toggl.config.POINTS),
        dict(toggl.config.NEGATIVES),
        dict(toggl.config.POSITIVES),
        list(toggl.config.RECOVERY_IGNORE or []),
        toggl.config.get_daily_target,
    )


class TestMetricsServiceDayMetrics:
    """Tests for MetricsService.get_day_metrics."""

    def test_get_day_metrics(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns complete day metrics dict with expected structure."""
        svc = _make_svc()
        metrics = svc.get_day_metrics("2023-01-02")

        assert metrics["label"] == "2023-01-02"
        assert metrics["total_hours"] == pytest.approx(2.1, abs=0.01)  # 1.5 + 0.6
        assert "net" in metrics
        assert "delta" in metrics
        assert "earned" in metrics
        assert "tracked_negative" in metrics
        assert "logged_negative" in metrics
        assert "logged_positive" in metrics
        assert "projects" in metrics
        assert "results" in metrics
        assert "negative_results" in metrics
        assert "positive_results" in metrics

    def test_get_day_metrics_empty(self, tmp_data_dir, sample_config):
        """Handles day with no data gracefully."""
        svc = _make_svc()
        metrics = svc.get_day_metrics("2099-01-01")

        assert metrics["total_hours"] == 0.0
        assert metrics["net"] == 0.0
        assert metrics["earned"] == 0.0
        assert metrics["tracked_negative"] == 0.0
        assert metrics["delta"] == pytest.approx(-13.0, abs=0.01)  # 0 - daily_target(13)

    def test_get_day_metrics_with_negatives(self, tmp_data_dir, sample_config):
        """Includes logged negatives in metrics."""
        import toggl.const

        with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
            f.write("Date,Negative,Points\n")
            f.write("2023-01-02,Bad Habit,5.0\n")

        svc = _make_svc()
        metrics = svc.get_day_metrics("2023-01-02")

        assert metrics["logged_negative"] == 5.0

    def test_get_day_metrics_with_positives(self, tmp_data_dir, sample_config):
        """Includes logged positives in metrics."""
        import toggl.const

        with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
            f.write("Date,Positive,Points\n")
            f.write("2023-01-02,Exercise,3.0\n")

        svc = _make_svc()
        metrics = svc.get_day_metrics("2023-01-02")

        assert metrics["logged_positive"] == 3.0


class TestMetricsServiceWeekDashboard:
    """Tests for MetricsService.get_week_dashboard_rows."""

    def test_get_week_dashboard_structure(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns 7 rows plus summary dict."""
        svc = _make_svc()
        result = svc.get_week_dashboard_rows("2023-W01")

        assert "rows" in result
        assert "summary" in result
        assert len(result["rows"]) == 7

        # Check row structure
        row = result["rows"][0]
        assert "day" in row
        assert "date" in row
        assert "hours" in row
        assert "net" in row
        assert "is_today" in row
        assert "has_activity" in row

        # Check summary structure
        summary = result["summary"]
        assert "days_counted" in summary
        assert "expected" in summary
        assert "actual" in summary
        assert "delta" in summary

    def test_get_week_dashboard_values(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Net values are reasonable for sample project data."""
        svc = _make_svc()
        result = svc.get_week_dashboard_rows("2023-W01")

        for row in result["rows"]:
            # Learning to Code at 1.5/hr × ? hours, Building Projects at 2.0/hr
            assert isinstance(row["net"], float)


class TestMetricsServiceReportSections:
    """Tests for MetricsService.get_report_sections."""

    def test_report_sections_week(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """Returns categorized sections for a week."""
        svc = _make_svc()
        report = svc.get_report_sections("2023-W01", "WEEK")

        assert "positive" in report
        assert "negative" in report
        assert "unscored" in report
        assert "results" in report
        assert "positive_results" in report
        assert "negative_results" in report
        assert "total_points" in report
        assert "total_hours" in report
        assert len(report["results"]) > 0

    def test_report_sections_all(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """Returns all-time sections across weeks."""
        svc = _make_svc()
        report = svc.get_report_sections("ALL_TIME", "ALL")

        assert report["total_hours"] > 0
        assert len(report["results"]) > 0

    def test_report_sections_day(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns sections for a specific day."""
        svc = _make_svc()
        report = svc.get_report_sections("2023-01-02", "DAY")

        assert report["total_hours"] > 0

    def test_report_sections_cache(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Same key returns cached result (identity check)."""
        svc = _make_svc()
        r1 = svc.get_report_sections("2023-W01", "WEEK")
        r2 = svc.get_report_sections("2023-W01", "WEEK")
        assert r1 is r2, "Second call should return cached object"

    def test_report_sections_cache_key_differentiates(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """Different keys produce different cached entries."""
        svc = _make_svc()
        r1 = svc.get_report_sections("2023-W01", "WEEK")
        r2 = svc.get_report_sections("2023-W02", "WEEK")
        assert r1 is not r2
        assert r1["total_hours"] != r2["total_hours"]


class TestMetricsServiceGraphData:
    """Tests for MetricsService.get_graph_data."""

    def test_get_graph_data_net_mode(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Computes lifetime cumulative net within the slice."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        dates, values, raw, avg = svc.get_graph_data(dashboard["rows"], "net")

        assert len(dates) == 7
        assert len(values) == 7
        assert len(raw) == 7
        assert values[-1] == round(sum(raw), 1)

    def test_get_graph_data_net_lifetime_baseline(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Baseline seeds cumulative net from prior days plus report alignment."""
        from toggl.cache import get_week_dates

        svc = _make_svc()
        w1_start, w1_end = get_week_dates("2023-W01")
        w2_start, _ = get_week_dates("2023-W02")
        w1_net = svc._daily_net_sum(w1_start, w1_end)
        baseline = svc.get_cumulative_before(w2_start, "net")
        assert baseline == round(w1_net + svc.get_net_graph_adjustment(), 1)

        w2_data = svc.get_daily_data_for_range(w2_start, w2_start + timedelta(days=6))
        _, values, _, _ = svc.get_graph_data(w2_data, "net", baseline=baseline)
        assert values[0] == round(baseline + float(w2_data[0]["net"]), 1)

    def test_get_cumulative_before_empty(self, tmp_data_dir, sample_config):
        """No data yields zero baseline."""
        svc = _make_svc()
        assert svc.get_cumulative_before(date(2023, 1, 1), "net") == 0.0

    def test_lifetime_net_matches_report(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Lifetime net uses the same total as ALL_TIME report sections."""
        svc = _make_svc()
        report = svc.get_report_sections("ALL_TIME", "ALL")
        assert svc.get_lifetime_net() == report["total_points"]

    def test_net_graph_adjustment_aligns_today(
        self, tmp_data_dir, sample_daily_csv, sample_config
    ):
        """Adjusted cumulative net at today equals lifetime report total."""
        from toggl.cache import get_week_dates

        svc = _make_svc()
        earliest = svc._earliest_data_date()
        assert earliest is not None
        today = date.today()
        if today < earliest:
            pytest.skip("fixture dates are in the past relative to today")
        daily = svc.get_daily_data_for_range(earliest, today)
        baseline = svc.get_cumulative_before(earliest, "net")
        _, values, _, _ = svc.get_graph_data(daily, "net", baseline=baseline)
        assert values[-1] == pytest.approx(svc.get_lifetime_net(), abs=0.05)

    def test_get_graph_data_negative_mode(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns lifetime cumulative negative (all <= 0)."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        dates, values, raw, avg = svc.get_graph_data(dashboard["rows"], "negative")

        assert len(values) == 7
        for v in values:
            assert v <= 0

    def test_graph_x_labels_week(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Week view labels are Wk N per day without reducing points."""
        from toggl.cache import get_week_dates

        svc = _make_svc()
        start, end = get_week_dates("2023-W01")
        end = start + timedelta(days=13)
        daily = svc.get_daily_data_for_range(start, end)
        dates, values, _, _ = svc.get_graph_data(daily, "net")
        labels = svc.graph_x_labels(dates, "week")

        assert len(labels) == len(dates) == len(values)
        assert all(lbl.startswith("Wk ") for lbl in labels)
        assert labels[0] != labels[-1]

    def test_graph_x_labels_month(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Month view labels are Mon YYYY per day without reducing points."""
        svc = _make_svc()
        start = date(2023, 1, 1)
        end = date(2023, 2, 5)
        daily = svc.get_daily_data_for_range(start, end)
        dates, values, _, _ = svc.get_graph_data(daily, "net")
        labels = svc.graph_x_labels(dates, "month")

        assert len(labels) == len(dates) == len(values)
        assert labels[0] == "Jan 2023"
        assert labels[-1] == "Feb 2023"

    def test_get_graph_data_positive_mode(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Positive mode returns lifetime cumulative positive."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        dates, values, raw, avg = svc.get_graph_data(dashboard["rows"], "positive")

        assert len(values) == 7
        for v in values:
            assert v >= 0


class TestMetricsServiceDailyBreakdown:
    """Tests for MetricsService.get_daily_breakdown."""

    def test_daily_breakdown_day(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Day mode returns individual day entries."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        breakdown = svc.get_daily_breakdown(dashboard["rows"], "day")

        assert len(breakdown) > 0
        for entry in breakdown:
            assert "label" in entry
            assert "positive" in entry
            assert "negative" in entry
            assert "net" in entry

    def test_daily_breakdown_week(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Week mode groups entries by week."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        breakdown = svc.get_daily_breakdown(dashboard["rows"], "week")

        assert len(breakdown) > 0
        for entry in breakdown:
            assert "label" in entry
            assert entry["label"].startswith("Wk")

    def test_daily_breakdown_month(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Month mode groups by month."""
        svc = _make_svc()
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        breakdown = svc.get_daily_breakdown(dashboard["rows"], "month")

        assert len(breakdown) > 0
        for entry in breakdown:
            assert "label" in entry


class TestMetricsServicePeriodNets:
    """Tests for MetricsService.compute_period_nets."""

    def test_compute_period_nets_day(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Day mode returns daily_net and weekly_net."""
        svc = _make_svc()
        result = svc.compute_period_nets(date(2023, 1, 2), date(2023, 1, 2), "day")

        assert "daily_net" in result
        assert "weekly_net" in result

    def test_compute_period_nets_week(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Week mode returns weekly_net and monthly_net."""
        svc = _make_svc()
        result = svc.compute_period_nets(date(2023, 1, 1), date(2023, 1, 7), "week")

        assert "weekly_net" in result
        assert "monthly_net" in result

    def test_compute_period_nets_unknown(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Unknown mode returns empty dict."""
        svc = _make_svc()
        result = svc.compute_period_nets(date(2023, 1, 1), date(2023, 1, 7), "unknown")

        assert result == {}
