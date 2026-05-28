"""Shared pytest fixtures for backfill tests."""

import os
import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Create a temp data dir, monkeypatch all path constants."""
    import toggl.const
    import toggl.cache
    import toggl.backfill

    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(toggl.const, "DATA_DIR", str(d))
    monkeypatch.setattr(toggl.const, "BACKFILL_DB", str(d / "toggl_backfill.db"))
    monkeypatch.setattr(toggl.const, "CSV_FILE", str(d / "toggl_data.csv"))
    monkeypatch.setattr(toggl.const, "DAILY_CSV_FILE", str(d / "toggl_daily.csv"))
    monkeypatch.setattr(toggl.const, "NEGATIVES_CSV_FILE", str(d / "toggl_negatives.csv"))
    monkeypatch.setattr(toggl.const, "POSITIVES_CSV_FILE", str(d / "toggl_positives.csv"))
    monkeypatch.setattr(toggl.const, "HISTORY_FILE", str(d / "toggl_sync_history.json"))
    monkeypatch.setattr(toggl.const, "PROJECTS_FILE", str(d / "toggl_projects.json"))
    # Also patch cache & backfill module-level references
    monkeypatch.setattr(toggl.cache, "CSV_FILE", toggl.const.CSV_FILE)
    monkeypatch.setattr(toggl.cache, "DAILY_CSV_FILE", toggl.const.DAILY_CSV_FILE)
    monkeypatch.setattr(toggl.backfill, "BACKFILL_DB", toggl.const.BACKFILL_DB)
    return str(d)


@pytest.fixture
def sample_weekly_csv(tmp_data_dir):
    """Write a minimal weekly CSV with two weeks of data."""
    import toggl.const

    lines = ["Week,Project,Hours"]
    lines.append("2023-W01,Learning to Code,10.5")
    lines.append("2023-W01,Building Projects,4.2")
    lines.append("2023-W02,Learning to Code,8.0")
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    return toggl.const.CSV_FILE


@pytest.fixture
def sample_daily_csv(tmp_data_dir):
    """Write a minimal daily CSV for two weeks."""
    import toggl.const
    from toggl.cache import get_week_dates
    from datetime import timedelta

    lines = ["Date,Project,Hours"]
    for week_str in ("2023-W01", "2023-W02"):
        start_d, end_d = get_week_dates(week_str)
        for i in range(7):
            d = start_d + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            lines.append(f"{d_str},Learning to Code,1.5")
            lines.append(f"{d_str},Building Projects,0.6")
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    return toggl.const.DAILY_CSV_FILE


@pytest.fixture
def stub_api(monkeypatch):
    """Monkeypatch fetch_week_data to return canned data."""

    def _fake_fetch(week_str, token, projects_map):
        weekly = {}
        daily = {}
        if week_str == "2023-W01":
            weekly = {"Learning to Code": 10.5, "Building Projects": 4.2}
            for d_off in range(7):
                ds = f"2023-01-{d_off + 1:02d}"
                daily[ds] = {"Learning to Code": 1.5, "Building Projects": 0.6}
        elif week_str == "2023-W02":
            weekly = {"Learning to Code": 8.0}
            for d_off in range(7):
                ds = f"2023-01-{d_off + 8:02d}"
                daily[ds] = {"Learning to Code": 1.2}
        elif week_str == "2023-W03":
            weekly = {"Fitness": 5.0}
            for d_off in range(7):
                ds = f"2023-01-{d_off + 15:02d}"
                daily[ds] = {"Fitness": 0.7}
        return weekly, daily

    import toggl.cache
    monkeypatch.setattr(toggl.cache, "fetch_week_data", _fake_fetch)
    return _fake_fetch


@pytest.fixture
def sample_config(tmp_data_dir, monkeypatch):
    """Set up a minimal points config so calculate() works."""
    import toggl.config
    import toggl.calc
    import toggl.cache

    points = {
        "Learning to Code": 1.5,
        "Building Projects": 2.0,
        "Fitness": 1.0,
    }
    monkeypatch.setattr(toggl.config, "POINTS", points)
    monkeypatch.setattr(toggl.calc, "POINTS", points)
    monkeypatch.setattr(toggl.cache, "POINTS", points)
    monkeypatch.setattr(toggl.config, "DAILY_TARGET", 13.0)
