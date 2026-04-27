"""Configuration loading and runtime settings."""

import sys
import os
import json

from toggl.const import CONFIG_FILE, DEFAULT_DAILY_TARGET, RED, RESET
from toggl.const import GREEN, YELLOW, CYAN, DIM


class Config:
    """Encapsulates all runtime configuration loaded from toggl_config.json."""
    __slots__ = ("points", "negatives", "positives", "daily_target")

    def __init__(self, points, negatives, positives, daily_target):
        self.points = points
        self.negatives = negatives
        self.positives = positives
        self.daily_target = daily_target

    @classmethod
    def load(cls) -> "Config":
        config = load_config()
        points = _load_rate_map(config, "points")
        negatives = _load_rate_map(config, "negatives")
        positives = _load_rate_map(config, "positives")
        daily_target = float(_coerce_number(
            config.get("daily_target", DEFAULT_DAILY_TARGET), "daily_target"
        ))
        return cls(points, negatives, positives, daily_target)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        print(f"{RED}Error: {CONFIG_FILE} must contain a JSON object.{RESET}")
        sys.exit(1)
    return data


def _coerce_number(value, label):
    try:
        num = float(value)
    except (TypeError, ValueError):
        print(f"{RED}Error: Invalid numeric value for {label}: {value!r}{RESET}")
        sys.exit(1)
    return int(num) if num.is_integer() else num


def _load_rate_map(config, key):
    raw = config.get(key)
    if raw is None:
        print(f"{RED}Error: Missing required '{key}' object in {CONFIG_FILE}.{RESET}")
        sys.exit(1)
    if not isinstance(raw, dict):
        print(f"{RED}Error: '{key}' in {CONFIG_FILE} must be an object.{RESET}")
        sys.exit(1)
    result = {}
    for name, rate in raw.items():
        result[str(name)] = _coerce_number(rate, f"{key}.{name}")
    return result


# ── Mutable runtime globals ──
POINTS = {}
NEGATIVES = {}
POSITIVES = {}
DAILY_TARGET = DEFAULT_DAILY_TARGET


def load_runtime_settings():
    global POINTS, NEGATIVES, POSITIVES, DAILY_TARGET
    cfg = Config.load()
    POINTS.clear()
    POINTS.update(cfg.points)
    NEGATIVES.clear()
    NEGATIVES.update(cfg.negatives)
    POSITIVES.clear()
    POSITIVES.update(cfg.positives)
    DAILY_TARGET = cfg.daily_target

def get_daily_target():
    return DAILY_TARGET
