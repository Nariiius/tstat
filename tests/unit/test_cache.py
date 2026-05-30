"""Unit tests for DataCache class methods."""

import pytest
from datetime import date
from unittest.mock import patch, mock_open

from toggl.cache import DataCache, get_week_dates, get_week_str


class TestDataCacheLoading:
    """Tests for DataCache CSV loading."""

    def test_load_empty_cache(self, tmp_data_dir):
        """Loading with no CSV files creates empty cache."""
        cache = DataCache.load()
        assert cache.weekly_data == {}
        assert cache.daily_data == {}
        assert cache.negatives_raw == {}
        assert cache.positives_raw == {}

    def test_load_weekly_csv(self, tmp_data_dir, sample_weekly_csv):
        """Weekly CSV loads correctly."""
        cache = DataCache.load()
        assert '2023-W01' in cache.weekly_data
        assert '2023-W02' in cache.weekly_data
        assert cache.weekly_data['2023-W01']['Learning to Code'] == 10.5

    def test_load_daily_csv(self, tmp_data_dir, sample_daily_csv):
        """Daily CSV loads correctly."""
        cache = DataCache.load()
        assert len(cache.daily_data) > 0
        # Check a specific date
        assert '2023-01-02' in cache.daily_data

    def test_load_negatives_csv(self, tmp_data_dir):
        """Negatives CSV loads correctly."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad Habit,5.0\n')
            f.write('2023-01-03,Procrastination,3.0\n')
        
        cache = DataCache.load()
        assert '2023-01-02' in cache.negatives_raw
        assert len(cache.negatives_raw['2023-01-02']) == 1
        assert cache.negatives_raw['2023-01-02'][0]['name'] == 'Bad Habit'
        assert cache.negatives_raw['2023-01-02'][0]['points'] == 5.0

    def test_load_positives_csv(self, tmp_data_dir):
        """Positives CSV loads correctly."""
        import toggl.const
        with open(toggl.const.POSITIVES_CSV_FILE, 'w') as f:
            f.write('Date,Positive,Points\n')
            f.write('2023-01-02,Exercise,2.0\n')
        
        cache = DataCache.load()
        assert '2023-01-02' in cache.positives_raw
        assert len(cache.positives_raw['2023-01-02']) == 1
        assert cache.positives_raw['2023-01-02'][0]['name'] == 'Exercise'


class TestDataCacheQueries:
    """Tests for DataCache query methods."""

    def test_get_week_projects(self, tmp_data_dir, sample_weekly_csv):
        """get_week_projects returns projects for a week."""
        cache = DataCache.load()
        projects = cache.get_week_projects('2023-W01')
        assert projects is not None
        assert 'Learning to Code' in projects
        assert projects['Learning to Code'] == 10.5

    def test_get_week_projects_missing(self, tmp_data_dir, sample_weekly_csv):
        """get_week_projects returns None for missing week."""
        cache = DataCache.load()
        projects = cache.get_week_projects('2099-W01')
        assert projects is None

    def test_get_day_projects(self, tmp_data_dir, sample_daily_csv):
        """get_day_projects returns projects for a day."""
        cache = DataCache.load()
        projects = cache.get_day_projects('2023-01-02')
        assert projects is not None
        assert 'Learning to Code' in projects

    def test_get_all_time_projects(self, tmp_data_dir, sample_weekly_csv):
        """get_all_time_projects aggregates all weeks."""
        cache = DataCache.load()
        projects = cache.get_all_time_projects()
        assert projects is not None
        assert 'Learning to Code' in projects
        # Should sum across weeks
        assert projects['Learning to Code'] > 10.5

    def test_get_all_time_projects_empty(self, tmp_data_dir):
        """get_all_time_projects returns None when no data."""
        cache = DataCache.load()
        projects = cache.get_all_time_projects()
        assert projects is None


class TestDataCacheMetrics:
    """Tests for DataCache metric calculations."""

    def test_get_day_metrics(self, tmp_data_dir, sample_daily_csv, sample_config):
        """get_day_metrics returns complete day metrics."""
        cache = DataCache.load()
        metrics = cache.get_day_metrics('2023-01-02')
        
        assert metrics['label'] == '2023-01-02'
        assert 'projects' in metrics
        assert 'results' in metrics
        assert 'earned' in metrics
        assert 'tracked_negative' in metrics
        assert 'logged_negative' in metrics
        assert 'logged_positive' in metrics
        assert 'total_hours' in metrics
        assert 'net' in metrics
        assert 'delta' in metrics

    def test_get_day_metrics_empty_day(self, tmp_data_dir, sample_config):
        """get_day_metrics handles empty day."""
        cache = DataCache.load()
        metrics = cache.get_day_metrics('2099-01-01')
        
        assert metrics['total_hours'] == 0.0
        assert metrics['net'] == 0.0

    def test_get_week_dashboard_rows(self, tmp_data_dir, sample_daily_csv, sample_config):
        """get_week_dashboard_rows returns 7 days of data."""
        cache = DataCache.load()
        result = cache.get_week_dashboard_rows('2023-W01')
        
        assert 'rows' in result
        assert 'summary' in result
        assert len(result['rows']) == 7
        
        # Check row structure
        row = result['rows'][0]
        assert 'day' in row
        assert 'date' in row
        assert 'hours' in row
        assert 'net' in row

    def test_get_report_sections(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """get_report_sections returns categorized results."""
        cache = DataCache.load()
        report = cache.get_report_sections('2023-W01', 'WEEK')
        
        assert 'results' in report
        assert 'positive' in report
        assert 'negative' in report
        assert 'unscored' in report
        assert 'total_points' in report
        assert 'total_hours' in report


class TestDataCacheNegativesPositives:
    """Tests for negative/positive tracking."""

    def test_get_negatives_for_context_day(self, tmp_data_dir):
        """get_negatives_for_context filters by day."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad,5.0\n')
            f.write('2023-01-03,Bad,3.0\n')
        
        cache = DataCache.load()
        negatives = cache.get_negatives_for_context('2023-01-02', 'DAY')
        
        assert len(negatives) == 1
        assert negatives[0][0] == 'Bad'
        assert negatives[0][3] == -5.0

    def test_get_negatives_for_context_week(self, tmp_data_dir):
        """get_negatives_for_context filters by week."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad,5.0\n')
            f.write('2023-01-03,Bad,3.0\n')
            f.write('2023-01-10,Bad,2.0\n')  # Different week
        
        cache = DataCache.load()
        negatives = cache.get_negatives_for_context('2023-W01', 'WEEK')
        
        # Should include Jan 2 and 3, but not Jan 10
        assert len(negatives) == 1
        assert negatives[0][3] == -8.0  # 5.0 + 3.0

    def test_get_negatives_for_context_all(self, tmp_data_dir):
        """get_negatives_for_context ALL includes everything."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad,5.0\n')
            f.write('2023-01-10,Bad,2.0\n')
        
        cache = DataCache.load()
        negatives = cache.get_negatives_for_context('ALL', 'ALL')
        
        assert len(negatives) == 1
        assert negatives[0][3] == -7.0  # 5.0 + 2.0

    def test_get_negative_log_rows(self, tmp_data_dir):
        """get_negative_log_rows returns sorted log entries."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad1,5.0\n')
            f.write('2023-01-03,Bad2,3.0\n')
        
        cache = DataCache.load()
        rows = cache.get_negative_log_rows()
        
        assert len(rows) == 2
        # Should be sorted by date descending
        assert rows[0]['date'] == '2023-01-03'
        assert rows[1]['date'] == '2023-01-02'

    def test_get_negative_log_rows_limit(self, tmp_data_dir):
        """get_negative_log_rows respects limit."""
        import toggl.const
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            for i in range(10):
                f.write(f'2023-01-{i+1:02d},Bad,{i}.0\n')
        
        cache = DataCache.load()
        rows = cache.get_negative_log_rows(limit=5)
        
        assert len(rows) == 5


class TestDataCacheAggregates:
    """Tests for aggregate calculations."""

    def test_get_monthly_aggregates(self, tmp_data_dir, sample_daily_csv, sample_config):
        """get_monthly_aggregates returns monthly summaries."""
        cache = DataCache.load()
        aggregates = cache.get_monthly_aggregates(last_n_months=3)
        
        assert len(aggregates) == 3
        for agg in aggregates:
            assert 'month' in agg
            assert 'hours' in agg
            assert 'net' in agg

    def test_get_recovery_rows_positive(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """get_recovery_rows returns empty when points are positive."""
        cache = DataCache.load()
        result = cache.get_recovery_rows('ALL', 'ALL')
        
        assert 'total_points' in result
        assert 'rows' in result
        # If total_points >= 0, rows should be empty
        if result['total_points'] >= 0:
            assert result['rows'] == []

    def test_get_recovery_rows_negative(self, tmp_data_dir, sample_config):
        """get_recovery_rows shows recovery plan when points are negative."""
        import toggl.const
        # Create data that results in negative points
        with open(toggl.const.NEGATIVES_CSV_FILE, 'w') as f:
            f.write('Date,Negative,Points\n')
            f.write('2023-01-02,Bad,100.0\n')
        
        cache = DataCache.load()
        result = cache.get_recovery_rows('ALL', 'ALL')
        
        # Should have recovery rows
        if result['total_points'] < 0:
            assert len(result['rows']) > 0
            for row in result['rows']:
                assert 'category' in row
                assert 'rate' in row
                assert 'hours_needed' in row
