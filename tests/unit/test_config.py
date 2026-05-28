"""Config loading behavior."""

import json
import os
import sys

import pytest

import toggl.config as config_mod


def test_load_config_missing_file_exits(tmp_path, monkeypatch):
    """Missing toggl_config.json must exit with a clear error (not a vague points error)."""
    missing = tmp_path / "toggl_config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(missing))
    with pytest.raises(SystemExit):
        config_mod.load_config()


def test_load_config_missing_points_exits(tmp_path, monkeypatch):
    path = tmp_path / "toggl_config.json"
    path.write_text(json.dumps({"negatives": {}, "positives": {}}))
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(path))
    with pytest.raises(SystemExit):
        config_mod.load_config()


def test_load_config_valid(tmp_path, monkeypatch):
    path = tmp_path / "toggl_config.json"
    path.write_text(
        json.dumps(
            {
                "points": {"Work": 1.0},
                "negatives": {"Bad": -1.0},
                "positives": {"Good": 1.0},
            }
        )
    )
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(path))
    data = config_mod.load_config()
    assert data["points"]["Work"] == 1.0
