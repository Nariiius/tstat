"""Tests for PlaybookService."""

from datetime import date

import pytest

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache
from toggl.services.metrics import MetricsService
from toggl.services.playbook import PlaybookService


def _svc(tmp_data_dir, sample_daily_csv, sample_config):
    cache = DataCache.load()
    return MetricsService(
        cache,
        __import__("toggl.config").POINTS,
        __import__("toggl.config").NEGATIVES,
        __import__("toggl.config").POSITIVES,
        [],
        lambda: 13.0,
    ), cache


@pytest.fixture
def playbook_svc(tmp_data_dir, sample_daily_csv, sample_config):
    metrics, cache = _svc(tmp_data_dir, sample_daily_csv, sample_config)
    import toggl.config as cfg_mod
    return PlaybookService(
        metrics,
        cache,
        dict(cfg_mod.POINTS),
        dict(cfg_mod.POSITIVES),
        ActivityRules.empty(),
        lambda: 13.0,
    )


def test_start_tracking_empty(tmp_path, monkeypatch, sample_config):
    import toggl.const
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    monkeypatch.setattr(toggl.const, "DATA_DIR", str(d))
    monkeypatch.setattr(toggl.const, "DAILY_CSV_FILE", str(d / "toggl_daily.csv"))
    monkeypatch.setattr(toggl.const, "CSV_FILE", str(d / "toggl_data.csv"))
    monkeypatch.setattr(toggl.const, "NEGATIVES_CSV_FILE", str(d / "toggl_negatives.csv"))
    monkeypatch.setattr(toggl.const, "POSITIVES_CSV_FILE", str(d / "toggl_positives.csv"))
    monkeypatch.setattr(toggl.const, "HISTORY_FILE", str(d / "toggl_sync_history.json"))
    import toggl.cache as cache_mod
    for attr in ("DAILY_CSV_FILE", "CSV_FILE", "NEGATIVES_CSV_FILE", "POSITIVES_CSV_FILE", "HISTORY_FILE"):
        monkeypatch.setattr(cache_mod, attr, getattr(toggl.const, attr))
    cache = DataCache.load()
    metrics = MetricsService(cache, {}, {}, {}, [], lambda: 13.0)
    pb = PlaybookService(metrics, cache, {}, {}, ActivityRules.empty(), lambda: 13.0).compute()
    assert pb.goal == "start_tracking"


def test_hit_today_target_has_steps(playbook_svc):
    pb = playbook_svc.compute()
    assert pb.goal in ("hit_today_target", "fix_week", "on_track")
    if pb.goal == "hit_today_target":
        assert pb.steps
        assert "Need" in pb.headline or "need" in pb.headline.lower()


def test_playbook_has_lookback_with_history(
    tmp_data_dir, sample_daily_csv, sample_config, monkeypatch
):
    import toggl.const
    import toggl.cache as cache_mod
    import toggl.services.recent_context as rc_mod
    import toggl.services.playbook as pb_mod
    from datetime import date as real_date

    today = real_date(2023, 1, 8)

    class MockDate(real_date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(cache_mod, "date", MockDate)
    monkeypatch.setattr(rc_mod, "date", MockDate)
    monkeypatch.setattr(pb_mod, "date", MockDate)

    with open(toggl.const.NEGATIVES_CSV_FILE, "w") as f:
        f.write("Date,Negative,Points\n")
        f.write("2023-01-02,Procrastination,3\n")
        f.write("2023-01-03,Procrastination,3\n")
        f.write("2023-01-07,Procrastination,3\n")

    import toggl.config as cfg_mod
    cache = DataCache.load()
    metrics = MetricsService(
        cache, cfg_mod.POINTS, cfg_mod.NEGATIVES, cfg_mod.POSITIVES, [], lambda: 13.0
    )
    svc = PlaybookService(
        metrics, cache, dict(cfg_mod.POINTS), dict(cfg_mod.POSITIVES),
        ActivityRules.empty(), lambda: 13.0,
    )
    pb = svc.compute()
    assert pb.lookback or pb.focus_line


def test_playbook_ignore_not_in_steps(playbook_svc, tmp_data_dir, sample_config):
    import toggl.const
    from toggl.activity_rules import ActivityRules, ActivityRuleEntry

    # Create a rule that marks "Three" as unsuggestable
    rules = ActivityRules(
        _entries={"Three": ActivityRuleEntry()}
    )
    # Override should_suggest by putting it in the always-skip set
    # Actually, let's just test through the category_natures mechanism
    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")
        f.write(f"{date.today().isoformat()},Three,3\n")
    cache = DataCache.load()
    import toggl.config as cfg_mod
    cfg_mod.POSITIVES["Three"] = 3
    metrics = MetricsService(
        cache, cfg_mod.POINTS, cfg_mod.NEGATIVES, cfg_mod.POSITIVES, [], lambda: 13.0
    )
    # Three is a dice-roll name in _ALWAYS_SKIP, so it won't be suggested
    svc = PlaybookService(
        metrics, cache, dict(cfg_mod.POINTS), dict(cfg_mod.POSITIVES),
        ActivityRules.empty(), lambda: 13.0,
    )
    pb = svc.compute()
    labels = [s.label for s in pb.steps]
    assert "Three" not in labels


def test_once_per_day_excluded_when_logged(playbook_svc, tmp_data_dir, sample_config):
    import toggl.const
    from toggl.activity_rules import ActivityRules, ActivityRuleEntry

    today = date.today().isoformat()
    with open(toggl.const.POSITIVES_CSV_FILE, "w") as f:
        f.write("Date,Positive,Points\n")
        f.write(f"{today},GI Dailies,3\n")
    cache = DataCache.load()
    import toggl.config as cfg_mod
    cfg_mod.POSITIVES["GI Dailies"] = 3
    metrics = MetricsService(
        cache, cfg_mod.POINTS, cfg_mod.NEGATIVES, cfg_mod.POSITIVES, [], lambda: 13.0
    )
    # GI Dailies with max_per_day=1
    rules = ActivityRules(
        _entries={"GI Dailies": ActivityRuleEntry(max_per_day=1)}
    )
    svc = PlaybookService(
        metrics, cache, dict(cfg_mod.POINTS), dict(cfg_mod.POSITIVES),
        rules, lambda: 13.0,
    )
    pb = svc.compute()
    assert "GI Dailies" not in [s.label for s in pb.steps]
    if pb.goal == "hit_today_target":
        assert "GI Dailies" in pb.done_today or "GI Dailies" in str(pb.done_today)
