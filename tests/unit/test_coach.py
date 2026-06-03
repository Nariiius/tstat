"""Tests for CoachService."""

import pytest

from toggl.cache import DataCache
from toggl.category import CategoryRegistry
from toggl.services.coach import COACH_MAX_FINDINGS, CoachService
from toggl.services.metrics import MetricsService


def _coach_svc(tmp_data_dir, sample_daily_csv, sample_config):
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
    return CoachService(
        metrics,
        cache,
        dict(cfg_mod.POINTS),
        dict(cfg_mod.POSITIVES),
        CategoryRegistry(),
    )


def test_coach_max_three_findings(tmp_data_dir, sample_daily_csv, sample_config):
    svc = _coach_svc(tmp_data_dir, sample_daily_csv, sample_config)
    report = svc.compute()
    assert len(report.findings) <= COACH_MAX_FINDINGS


def test_coach_sparse_data_empty(tmp_data_dir, sample_config):
    cache = DataCache.load()
    metrics = MetricsService(cache, {}, {}, {}, [], lambda: 13.0)
    report = CoachService(metrics, cache, {}, {}, CategoryRegistry()).compute()
    assert report.findings == []


def test_coach_finding_not_banned_kind(tmp_data_dir, sample_daily_csv, sample_config):
    from toggl.services.coach import BANNED_ANALYZERS
    svc = _coach_svc(tmp_data_dir, sample_daily_csv, sample_config)
    report = svc.compute()
    for f in report.findings:
        assert f.analyzer not in BANNED_ANALYZERS
        assert "biggest booster" not in f.text.lower()
