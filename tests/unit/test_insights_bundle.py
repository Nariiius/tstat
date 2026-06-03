"""Tests for InsightsBundleService cache."""

import toggl.const
from toggl.cache import DataCache
from toggl.config import Config
from toggl.services.insights_bundle import InsightsBundleService
from toggl.services.metrics import MetricsService


def test_cache_roundtrip(tmp_data_dir, sample_daily_csv, sample_config, monkeypatch):
    from pathlib import Path
    cache_path = str(Path(tmp_data_dir) / "toggl_insights_bundle.json")
    monkeypatch.setattr(toggl.const, "PLAYBOOK_CACHE_FILE", cache_path)
    cache = DataCache.load()
    import toggl.config as cfg_mod
    metrics = MetricsService(
        cache,
        cfg_mod.POINTS,
        cfg_mod.NEGATIVES,
        cfg_mod.POSITIVES,
        [],
        lambda: 13.0,
    )
    cfg = Config(
        cfg_mod.POINTS,
        cfg_mod.NEGATIVES,
        cfg_mod.POSITIVES,
        13.0,
        cfg_mod.RATE_COLORS,
        cfg_mod.CATEGORY_REGISTRY,
        [],
        list(cfg_mod.PLAYBOOK_IGNORE),
    )
    svc = InsightsBundleService(metrics, cache, cfg, lambda: 13.0, cache_path=cache_path)
    bundle = svc.compute()
    svc.save_cache(bundle)
    loaded = svc.try_load_cache()
    assert loaded is not None
    assert loaded.playbook.goal == bundle.playbook.goal
