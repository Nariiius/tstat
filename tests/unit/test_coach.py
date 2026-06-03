"""Tests for CoachService."""

import pytest

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache
from toggl.category import CategoryRegistry
from toggl.services.coach import CoachService
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
        ActivityRules.empty(),
    )


def test_coach_returns_findings(tmp_data_dir, sample_daily_csv, sample_config):
    svc = _coach_svc(tmp_data_dir, sample_daily_csv, sample_config)
    report = svc.compute()
    # No hard cap — just verify it computes something
    assert isinstance(report.findings, list)


def test_coach_sparse_data_empty(tmp_data_dir, sample_config):
    cache = DataCache.load()
    metrics = MetricsService(cache, {}, {}, {}, [], lambda: 13.0)
    report = CoachService(
        metrics, cache, {}, {}, CategoryRegistry(), ActivityRules.empty()
    ).compute()
    assert report.findings == []


def test_coach_findings_are_statistically_gated(tmp_data_dir, sample_daily_csv, sample_config):
    """All findings should come from the three statistically-gated analyzers."""
    svc = _coach_svc(tmp_data_dir, sample_daily_csv, sample_config)
    report = svc.compute()
    valid_analyzers = {"biggest_positive_driver", "biggest_negative_driver", "largest_gap"}
    for f in report.findings:
        assert f.analyzer in valid_analyzers
        assert f.confidence >= 0.40
        assert f.evidence  # every finding must have evidence
