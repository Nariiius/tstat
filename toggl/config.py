"""Configuration loading and runtime settings."""

import sys
import os
import json
from typing import Any

from toggl.activity_rules import ActivityRules
from toggl.const import CONFIG_FILE, DEFAULT_DAILY_TARGET, RED, RESET
from toggl.rate_colors import RateColors
from toggl.category import CategoryRegistry

CONFIG_EXAMPLE_FILE = CONFIG_FILE.replace(".json", ".json.example")
_REQUIRED_RATE_MAPS = ("points", "negatives", "positives")


class Config:
    """Encapsulates all runtime configuration loaded from toggl_config.json."""
    __slots__ = (
        "points", "negatives", "positives", "daily_target",
        "rate_colors", "category_registry", "recovery_ignore",
        "activity_rules", "controllability", "availability_overrides",
        "low_control_reasons", "default_hours", "discovery_lookback",
        "discovery_ignore",
    )

    def __init__(
        self,
        points: dict[str, int | float],
        negatives: dict[str, int | float],
        positives: dict[str, int | float],
        daily_target: int | float,
        rate_colors: RateColors,
        category_registry: CategoryRegistry,
        recovery_ignore: list[str],
        activity_rules: ActivityRules,
        controllability: dict[str, float] | None = None,
        availability_overrides: dict[str, dict] | None = None,
        low_control_reasons: dict[str, str] | None = None,
        default_hours: dict[str, float] | None = None,
        discovery_lookback: dict[str, int] | None = None,
        discovery_ignore: set[str] | None = None,
    ) -> None:
        self.points = points
        self.negatives = negatives
        self.positives = positives
        self.daily_target = daily_target
        self.rate_colors = rate_colors
        self.category_registry = category_registry
        self.recovery_ignore = recovery_ignore
        self.activity_rules = activity_rules
        self.controllability = controllability or {}
        self.availability_overrides = availability_overrides or {}
        self.low_control_reasons = low_control_reasons or {}
        self.default_hours = default_hours or {}
        self.discovery_lookback = discovery_lookback or {
            "drift": 60, "growth": 60, "failure": 90, "best_period": 120
        }
        self.discovery_ignore = discovery_ignore or set()

    @classmethod
    def load(cls) -> "Config":
        config = load_config()
        points = _load_rate_map(config, "points")
        negatives = _load_rate_map(config, "negatives")
        positives = _load_rate_map(config, "positives")
        daily_target = float(_coerce_number(
            config.get("daily_target", DEFAULT_DAILY_TARGET), "daily_target"
        ))
        rate_colors_raw = config.get("rate_colors")
        if rate_colors_raw is not None and not isinstance(rate_colors_raw, dict):
            _exit_config_error(
                f"Error: 'rate_colors' in {CONFIG_FILE} must be a JSON object "
                f"mapping rates to hex colors."
            )
        rate_colors = RateColors(rate_colors_raw)
        categories_raw = config.get("categories")
        if categories_raw is not None and not isinstance(categories_raw, dict):
            _exit_config_error(
                f"Error: 'categories' in {CONFIG_FILE} must be a JSON object "
                f"mapping category names to {{color, projects}}."
            )
        category_registry = CategoryRegistry(categories_raw)
        recovery_ignore_raw = config.get("recovery_ignore")
        if recovery_ignore_raw is not None and not isinstance(recovery_ignore_raw, list):
            _exit_config_error(
                f"Error: 'recovery_ignore' in {CONFIG_FILE} must be a JSON array of strings."
            )
        recovery_ignore = [str(x) for x in (recovery_ignore_raw or [])]
        activity_rules = ActivityRules.from_config(
            config.get("category_natures"),
            config.get("activity_rules"),
        )
        
        # Parse playbook section
        playbook_raw = config.get("playbook", {})
        if not isinstance(playbook_raw, dict):
            playbook_raw = {}
        
        controllability = {}
        for name, val in playbook_raw.get("controllability", {}).items():
            controllability[str(name)] = float(val)
        
        availability_overrides = playbook_raw.get("availability_overrides", {})
        low_control_reasons = {
            str(k): str(v) for k, v in playbook_raw.get("low_control_reasons", {}).items()
        }
        
        default_hours = {}
        for name, val in playbook_raw.get("default_hours", {}).items():
            default_hours[str(name)] = float(val)
        
        discovery_lookback = {
            str(k): int(v) for k, v in playbook_raw.get("discovery_lookback", {}).items()
        }
        
        discovery_ignore_raw = playbook_raw.get("discovery_ignore", [])
        discovery_ignore = set(str(x) for x in discovery_ignore_raw)
        
        return cls(points, negatives, positives, daily_target,
                   rate_colors, category_registry, recovery_ignore, activity_rules,
                   controllability, availability_overrides, low_control_reasons,
                   default_hours, discovery_lookback, discovery_ignore)


def _config_setup_hint() -> str:
    if os.path.exists(CONFIG_EXAMPLE_FILE):
        return (
            f"  Copy the template and edit your values:\n"
            f"    cp {CONFIG_EXAMPLE_FILE} {CONFIG_FILE}"
        )
    return (
        f"  Create {CONFIG_FILE} with objects: "
        f"{', '.join(_REQUIRED_RATE_MAPS)}, plus optional daily_target and api_token."
    )


def _exit_config_error(message: str) -> None:
    print(f"{RED}{message}{RESET}")
    hint = _config_setup_hint()
    if hint:
        print(hint)
    sys.exit(1)


def load_config() -> dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        _exit_config_error(f"Error: Config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        _exit_config_error(f"Error: {CONFIG_FILE} must contain a JSON object.")
    missing = [key for key in _REQUIRED_RATE_MAPS if data.get(key) is None]
    if missing:
        keys = ", ".join(f"'{k}'" for k in missing)
        _exit_config_error(
            f"Error: {CONFIG_FILE} is missing required object(s): {keys}."
        )
    return data


def _coerce_number(value: Any, label: str) -> int | float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        print(f"{RED}Error: Invalid numeric value for {label}: {value!r}{RESET}")
        sys.exit(1)
    return int(num) if num.is_integer() else num


def _load_rate_map(config: dict[str, Any], key: str) -> dict[str, int | float]:
    raw = config.get(key)
    if not isinstance(raw, dict):
        _exit_config_error(
            f"Error: '{key}' in {CONFIG_FILE} must be a JSON object mapping names to numbers."
        )
    result = {}
    for name, rate in raw.items():
        result[str(name)] = _coerce_number(rate, f"{key}.{name}")
    return result


# ── Mutable runtime globals ──
POINTS: dict[str, int | float] = {}
NEGATIVES: dict[str, int | float] = {}
POSITIVES: dict[str, int | float] = {}
RECOVERY_IGNORE: list[str] = []
DAILY_TARGET: int | float = DEFAULT_DAILY_TARGET
RATE_COLORS: RateColors = RateColors()
CATEGORY_REGISTRY: CategoryRegistry = CategoryRegistry()
ACTIVITY_RULES: ActivityRules = ActivityRules.empty()
CONTROLLABILITY: dict[str, float] = {}
AVAILABILITY_OVERRIDES: dict[str, dict] = {}
LOW_CONTROL_REASONS: dict[str, str] = {}
DEFAULT_HOURS: dict[str, float] = {}
DISCOVERY_LOOKBACK: dict[str, int] = {
    "drift": 60, "growth": 60, "failure": 90, "best_period": 120
}
DISCOVERY_IGNORE: set[str] = set()


def load_runtime_settings() -> None:
    global POINTS, NEGATIVES, POSITIVES, RECOVERY_IGNORE
    global DAILY_TARGET, RATE_COLORS, CATEGORY_REGISTRY, ACTIVITY_RULES
    global CONTROLLABILITY, AVAILABILITY_OVERRIDES, LOW_CONTROL_REASONS
    global DEFAULT_HOURS, DISCOVERY_LOOKBACK, DISCOVERY_IGNORE
    cfg = Config.load()
    POINTS.clear()
    POINTS.update(cfg.points)
    NEGATIVES.clear()
    NEGATIVES.update(cfg.negatives)
    POSITIVES.clear()
    POSITIVES.update(cfg.positives)
    RECOVERY_IGNORE.clear()
    RECOVERY_IGNORE.extend(cfg.recovery_ignore)
    DAILY_TARGET = cfg.daily_target
    RATE_COLORS.update(cfg.rate_colors)
    CATEGORY_REGISTRY.update(cfg.category_registry)
    ACTIVITY_RULES = cfg.activity_rules
    CONTROLLABILITY.clear()
    CONTROLLABILITY.update(cfg.controllability)
    AVAILABILITY_OVERRIDES.clear()
    AVAILABILITY_OVERRIDES.update(cfg.availability_overrides)
    LOW_CONTROL_REASONS.clear()
    LOW_CONTROL_REASONS.update(cfg.low_control_reasons)
    DEFAULT_HOURS.clear()
    DEFAULT_HOURS.update(cfg.default_hours)
    DISCOVERY_LOOKBACK.clear()
    DISCOVERY_LOOKBACK.update(cfg.discovery_lookback)
    DISCOVERY_IGNORE.clear()
    DISCOVERY_IGNORE.update(cfg.discovery_ignore)

def get_daily_target() -> int | float:
    return DAILY_TARGET
