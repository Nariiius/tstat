"""Activity rules — configurable behaviour for playbook suggestions and coach analysis.

Replaces the old hardcoded constants (ONCE_PER_DAY_POSITIVES, ABSCINEMA_NAME,
DEFAULT_PLAYBOOK_IGNORE, abs_cinema_mode flag) with a unified, user-configurable
rule system driven by two new toggl_config.json sections:

    category_natures  → per-category defaults  (pursue / neutral / avoid)
    activity_rules    → per-activity overrides  (limits, streak, combos, …)

If neither section exists in the config, every activity defaults to ``pursue``
(always suggest, normal coach mode) — fully backward-compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────
# Category nature
# ──────────────────────────────────────────────


@dataclass(frozen=True)
class CategoryNature:
    """Default behavioural profile for a category."""
    nature: str = "pursue"  # "pursue" | "neutral" | "avoid"

    @property
    def suggests(self) -> bool:
        """Should linked activities appear in playbook suggestions?"""
        if self.nature == "avoid":
            return False
        if self.nature == "neutral":
            return True  # suggested, but at lower priority
        return True  # pursue

    @property
    def coach_mode(self) -> str:
        """How the coach talks about linked activities.

        ``"normal"`` — full prompting (e.g. "Log it today").
        ``"observe_only"`` — acknowledges patterns without urging action.
        """
        return "observe_only" if self.nature == "avoid" else "normal"

    @property
    def coach_confidence_mod(self) -> float:
        """Offset applied to coach finding confidence for linked activities."""
        if self.nature == "avoid":
            return -0.15
        if self.nature == "neutral":
            return -0.05
        return 0.0

    @property
    def priority_mod(self) -> float:
        """Sort bias applied to playbook suggestion ranking."""
        if self.nature == "avoid":
            return -999.0  # effectively removes from candidates
        if self.nature == "neutral":
            return -8.0
        return 0.0  # pursue


# ──────────────────────────────────────────────
# Activity rule entry
# ──────────────────────────────────────────────


@dataclass
class ActivityRuleEntry:
    """Per-activity behavioural rule.

    Every field is optional — missing fields inherit from the linked category's
    ``CategoryNature`` default.
    """
    category: str | None = None           # link to a category → inherit nature
    coach_mode: str | None = None          # "normal" | "observe_only"
    coach_confidence_mod: float | None = None
    max_per_day: int | None = None
    max_per_week: int | None = None
    remind_after_gap_days: int | None = None
    throttle_after_days: int | None = None
    combo_pairs: list[str] = field(default_factory=list)
    combo_conflicts: list[str] = field(default_factory=list)
    combo_boost: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActivityRuleEntry:
        limits = d.get("limits") or {}
        streak = d.get("streak") or {}
        combos = d.get("combos") or {}
        return cls(
            category=d.get("category"),
            coach_mode=d.get("coach_mode"),
            coach_confidence_mod=d.get("coach_confidence_mod"),
            max_per_day=limits.get("max_per_day"),
            max_per_week=limits.get("max_per_week"),
            remind_after_gap_days=streak.get("remind_after_gap_days"),
            throttle_after_days=streak.get("throttle_after_days"),
            combo_pairs=list(combos.get("pairs_with", [])),
            combo_conflicts=list(combos.get("conflicts_with", [])),
            combo_boost=float(combos.get("boost", 0)),
        )


# ──────────────────────────────────────────────
# Aggregate rule set
# ──────────────────────────────────────────────


_FALLBACK_NATURE = CategoryNature("pursue")
_FALLBACK_ENTRY = ActivityRuleEntry()


# Names that must never appear as suggestions (dice-roll placeholders).
_ALWAYS_SKIP: frozenset[str] = frozenset({
    "One", "Two", "Three", "Four", "Five", "Six", "Seven",
    "Eight", "Nine", "Ten", "Eleven", "Twelve",
})


@dataclass
class ActivityRules:
    """Unified activity rule engine.

    Usage::

        rules = ActivityRules.from_config(config.get("category_natures"),
                                         config.get("activity_rules"))

        if rules.should_suggest("Meditation"):
            ...
        if rules.is_once_per_day("Care"):
            ...
        mode = rules.get_coach_mode("Abs Cinema")  # → "observe_only" (avoid)
    """

    _natures: dict[str, CategoryNature] = field(default_factory=dict)
    _entries: dict[str, ActivityRuleEntry] = field(default_factory=dict)

    # ── Private helpers ──

    def _entry_for(self, name: str) -> ActivityRuleEntry:
        return self._entries.get(name, _FALLBACK_ENTRY)

    def _nature_for(self, name: str) -> CategoryNature:
        entry = self._entry_for(name)
        if entry.category:
            return self._natures.get(entry.category, _FALLBACK_NATURE)
        return _FALLBACK_NATURE

    # ── Public query API ──

    def should_suggest(self, name: str) -> bool:
        """Should *name* appear in playbook step suggestions?

        Returns ``False`` for dice-roll placeholders, activities in an *avoid*
        category, or any name explicitly filtered out.
        """
        if name in _ALWAYS_SKIP:
            return False
        return self._nature_for(name).suggests

    def get_coach_mode(self, name: str) -> str:
        """Coach mode for a specific activity: ``"normal"`` or ``"observe_only"``."""
        entry = self._entry_for(name)
        if entry.coach_mode is not None:
            return entry.coach_mode
        return self._nature_for(name).coach_mode

    def get_coach_confidence_mod(self, name: str) -> float:
        """Confidence delta to add to coach findings about *name*."""
        entry = self._entry_for(name)
        if entry.coach_confidence_mod is not None:
            return entry.coach_confidence_mod
        return self._nature_for(name).coach_confidence_mod

    def get_priority_mod(self, name: str) -> float:
        """Sort bias for playbook candidate ranking."""
        return self._nature_for(name).priority_mod

    def is_once_per_day(self, name: str) -> bool:
        """Can *name* be logged at most once per calendar day?"""
        entry = self._entry_for(name)
        if entry.max_per_day is not None:
            return entry.max_per_day <= 1
        return False

    def max_logs_today(self, name: str, already_logged: int) -> bool:
        """Has *name* reached its daily logging limit?"""
        entry = self._entry_for(name)
        if entry.max_per_day is None:
            return False
        return already_logged >= entry.max_per_day

    def get_remind_after_gap_days(self, name: str) -> int | None:
        """If set, escalate urgency when *name* hasn't been logged for N days."""
        entry = self._entry_for(name)
        return entry.remind_after_gap_days

    def get_throttle_after_days(self, name: str) -> int | None:
        """If set, reduce urgency when *name* has been logged too many days in a row."""
        entry = self._entry_for(name)
        return entry.throttle_after_days

    def get_combo_pairs(self, name: str) -> list[str]:
        """Activities that pair well with *name*."""
        entry = self._entry_for(name)
        return entry.combo_pairs

    def get_combo_boost(self, name: str) -> float:
        """Extra priority when *name* is suggested alongside its combo pair."""
        entry = self._entry_for(name)
        return entry.combo_boost

    def get_combo_conflicts(self, name: str) -> list[str]:
        """Activities that conflict with *name* on the same day."""
        entry = self._entry_for(name)
        return entry.combo_conflicts

    # ── Loaders ──

    @classmethod
    def from_config(
        cls,
        category_natures_raw: dict[str, Any] | None,
        activity_rules_raw: dict[str, Any] | None,
    ) -> ActivityRules:
        """Build an ActivityRules instance from the config JSON sections."""
        natures: dict[str, CategoryNature] = {}

        if category_natures_raw:
            for cat_name, cat_data in category_natures_raw.items():
                if isinstance(cat_data, dict):
                    nature_val = str(cat_data.get("nature", "pursue"))
                else:
                    nature_val = str(cat_data)
                if nature_val in ("pursue", "neutral", "avoid"):
                    natures[str(cat_name)] = CategoryNature(nature=nature_val)

        entries: dict[str, ActivityRuleEntry] = {}
        if activity_rules_raw:
            for name, rule_data in activity_rules_raw.items():
                if isinstance(rule_data, dict):
                    entries[str(name)] = ActivityRuleEntry.from_dict(rule_data)

        return cls(_natures=natures, _entries=entries)

    def to_stable_dict(self) -> dict[str, Any]:
        """Stable dict for cache fingerprint — sorted keys, no runtime state."""
        natures = {
            str(k): {"nature": str(v.nature)}
            for k, v in sorted(self._natures.items())
        }
        entries = {}
        for k, v in sorted(self._entries.items()):
            entries[str(k)] = {
                "category": v.category,
                "coach_mode": v.coach_mode,
                "coach_confidence_mod": v.coach_confidence_mod,
                "max_per_day": v.max_per_day,
                "max_per_week": v.max_per_week,
                "remind_after_gap_days": v.remind_after_gap_days,
                "throttle_after_days": v.throttle_after_days,
                "combo_pairs": sorted(v.combo_pairs),
                "combo_conflicts": sorted(v.combo_conflicts),
                "combo_boost": v.combo_boost,
            }
        return {"natures": natures, "entries": entries}

    @classmethod
    def empty(cls) -> ActivityRules:
        """Fallback: every activity is *pursue* with no overrides."""
        return cls()
