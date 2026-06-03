"""Tests for recent day context."""

from datetime import date, timedelta

from toggl.cache import DataCache
from toggl.services.metrics import MetricsService
from toggl.services.recent_context import build_recent_context


def test_recent_context_yesterday(tmp_data_dir, sample_daily_csv, sample_config, monkeypatch):
    import toggl.const
    import toggl.cache as cache_mod
    import toggl.tui
    import toggl.state.period

    today = date(2023, 1, 8)
    yesterday = today - timedelta(days=1)

    class MockDate(date):
        @classmethod
        def today(cls):
            return today

    import toggl.services.recent_context as rc_mod
    monkeypatch.setattr(toggl.tui, "date", MockDate)
    monkeypatch.setattr(cache_mod, "date", MockDate)
    monkeypatch.setattr(toggl.state.period, "date", MockDate)
    monkeypatch.setattr(rc_mod, "date", MockDate)

    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")
        f.write(f"{yesterday.isoformat()},Exercise,3\n")

    cache = DataCache.load()
    import toggl.config as cfg_mod
    metrics = MetricsService(
        cache, cfg_mod.POINTS, cfg_mod.NEGATIVES, cfg_mod.POSITIVES, [], lambda: 13.0
    )
    ctx = build_recent_context(metrics, cache)
    assert ctx.yesterday is not None
    assert "Exercise" in ctx.yesterday.positives
