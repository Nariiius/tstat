"""Coach Service — personal baseline analysis and pattern detection.

Analyses how your current behaviour compares to your *own* recent history
(rather than comparing you to others or to absolute thresholds).

Coach findings surface things like:
  - 🟢 On a roll — a positive habit is happening more often than usual
  - 🔴 Falling off — a positive habit has dropped below your personal norm
  - ⚠ Pattern emerging — a negative is appearing more frequently
  - ⏱ Gap reminder — it's been a while since you did X

Every finding respects ``activity_rules.get_coach_mode()`` and
``activity_rules.get_coach_confidence_mod()`` so that *avoid* category
activities are observe-only and low-confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache
from toggl.config import Config
from toggl.services.metrics import MetricsService
from toggl.services.recent_context import RecentContext, build_recent_context

logger = logging.getLogger("TStat")

MIN_CONFIDENCE = 0.50


@dataclass
class CoachFinding:
    """A single coach observation — always a comparison to personal history."""

    kind: str  # frequency_drop | frequency_surge | streak_gap | negative_cluster | positive_lift
    title: str
    summary: str
    confidence: float
    impact: float
    subject: str


class CoachService:
    """Compares recent behaviour against personal baselines.

    Personal baselines are computed from the last 28 days.  Recent
    behaviour is the last 7 days.  The coach only surfaces deltas
    that exceed the noise floor for each individual activity.
    """

    LOOKBACK_LONG = 35  # days for personal baseline
    LOOKBACK_SHORT = 7  # days for "recent"
    MIN_OCCURRENCES_LONG = 3  # minimum total occurrences to establish baseline

    def __init__(
        self,
        cache: DataCache,
        metrics: MetricsService,
        config: Config,
        activity_rules: ActivityRules,
    ) -> None:
        self._cache = cache
        self._metrics = metrics
        self._config = config
        self._rules = activity_rules

    # ── Main pipeline ───────────────────────────────────────────────────

    def compute(self) -> list[CoachFinding]:
        """Run all coach analyzers and return ranked findings."""
        today = date.today()
        findings: list[CoachFinding] = []

        # Build recent context (7-day lookback with positive_lift)
        recent = build_recent_context(
            self._metrics, self._cache, lookback_days=self.LOOKBACK_SHORT
        )

        # Build personal baselines over the longer lookback
        baseline = self._compute_baselines(today)

        findings.extend(self._analyze_frequency_drops(baseline, recent, today))
        findings.extend(self._analyze_frequency_surges(baseline, recent, today))
        findings.extend(self._analyze_streak_gaps(today, recent))
        findings.extend(self._analyze_negative_clusters(baseline, recent))

        # Sort by confidence descending, cap at 4
        findings.sort(key=lambda f: -f.confidence)
        return findings[:4]

    # ── Personal baseline computation ───────────────────────────────────

    def _compute_baselines(
        self, today: date
    ) -> dict[str, dict[str, float]]:
        """Compute per-activity personal baselines from the last 28-35 days.

        Returns a dict of ``{name: {"count": ..., "rate_per_day": ...}}``
        for both positives and negatives.
        """
        baseline: dict[str, dict[str, float]] = {}
        start = today - timedelta(days=self.LOOKBACK_LONG)

        # Aggregate positives
        pos_counts: dict[str, int] = {}
        for d_str, entries in self._cache.positives_raw.items():
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if start <= d < today:
                for e in entries:
                    name = e["name"]
                    pos_counts[name] = pos_counts.get(name, 0) + 1

        # Aggregate negatives
        neg_counts: dict[str, int] = {}
        for d_str, entries in self._cache.negatives_raw.items():
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if start <= d < today:
                for e in entries:
                    name = e["name"]
                    neg_counts[name] = neg_counts.get(name, 0) + 1

        total_days = (today - start).days or 1

        for name, count in pos_counts.items():
            baseline[name] = {
                "count": count,
                "rate_per_day": count / total_days,
            }
        for name, count in neg_counts.items():
            baseline[name] = {
                "count": count,
                "rate_per_day": count / total_days,
            }

        return baseline

    # ── Analyzer 1: Frequency drops (falling off) ───────────────────────

    def _analyze_frequency_drops(
        self,
        baseline: dict[str, dict[str, float]],
        recent: RecentContext,
        today: date,
    ) -> list[CoachFinding]:
        """A positive habit is happening less often than your personal norm."""
        findings: list[CoachFinding] = []
        if not recent.days:
            return findings
        short_days = self.LOOKBACK_SHORT

        for name, pts in self._config.positives.items():
            if float(pts) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue
            bl = baseline.get(name)
            if bl is None or bl["count"] < self.MIN_OCCURRENCES_LONG:
                continue

            recent_count = recent.pos_counts_7d.get(name, 0)
            recent_rate = recent_count / short_days
            baseline_rate = bl["rate_per_day"]

            # Need a meaningful baseline (> 1/week) to detect drops
            if baseline_rate < 0.12:
                continue

            drop_ratio = recent_rate / baseline_rate if baseline_rate > 0 else 0
            if drop_ratio > 0.0 and drop_ratio >= 0.50:
                continue  # not a significant drop

            # Confidence scales with how far below baseline
            confidence = min(0.55 + (1.0 - min(drop_ratio, 1.0)) * 0.35, 0.90)
            confidence += self._rules.get_coach_confidence_mod(name)

            coach_mode = self._rules.get_coach_mode(name)
            if coach_mode == "observe_only":
                confidence *= 0.5  # dampen for avoid/neutral

            if confidence < MIN_CONFIDENCE:
                continue

            impact = min(0.3 + (float(pts) / 8.0) * 0.5, 0.85)

            if recent_count == 0:
                summary = (
                    f"You haven't logged {name} at all in the last {short_days}d. "
                    f"Your personal average is ~{baseline_rate:.1f}×/day."
                )
            else:
                summary = (
                    f"{name} logged {recent_count}× in {short_days}d "
                    f"(vs your baseline ~{baseline_rate:.1f}×/day). "
                    f"That's about {int((1 - drop_ratio) * 100)}% below your norm."
                )

            findings.append(CoachFinding(
                kind="frequency_drop",
                title=f"{name} Frequency Dropped",
                summary=summary,
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                subject=name,
            ))

        return findings

    # ── Analyzer 2: Frequency surges (on a roll) ────────────────────────

    def _analyze_frequency_surges(
        self,
        baseline: dict[str, dict[str, float]],
        recent: RecentContext,
        today: date,
    ) -> list[CoachFinding]:
        """A positive habit is happening more often than usual — reinforce it."""
        findings: list[CoachFinding] = []
        if not recent.days:
            return findings
        short_days = self.LOOKBACK_SHORT

        for name, pts in self._config.positives.items():
            if float(pts) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue
            bl = baseline.get(name)
            if bl is None or bl["count"] < self.MIN_OCCURRENCES_LONG:
                continue

            recent_count = recent.pos_counts_7d.get(name, 0)
            recent_rate = recent_count / short_days
            baseline_rate = bl["rate_per_day"]

            if baseline_rate < 0.05 or recent_rate < 0.15:
                continue

            surge_ratio = recent_rate / baseline_rate if baseline_rate > 0 else 1.0
            if surge_ratio < 1.5:
                continue  # not a meaningful surge

            confidence = min(0.50 + min(surge_ratio / 5.0, 0.35), 0.85)
            confidence += self._rules.get_coach_confidence_mod(name)

            coach_mode = self._rules.get_coach_mode(name)
            if coach_mode == "observe_only":
                confidence *= 0.5

            if confidence < MIN_CONFIDENCE:
                continue

            impact = min(0.25 + (float(pts) / 8.0) * 0.4, 0.80)

            summary = (
                f"{name} logged {recent_count}× in {short_days}d "
                f"(vs your baseline ~{baseline_rate:.1f}×/day). "
                f"That's about {int((surge_ratio - 1) * 100)}% above normal — keep it up."
            )

            findings.append(CoachFinding(
                kind="frequency_surge",
                title=f"{name} On a Roll",
                summary=summary,
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                subject=name,
            ))

        return findings

    # ── Analyzer 3: Streak gaps (reminder) ──────────────────────────────

    def _analyze_streak_gaps(
        self,
        today: date,
        recent: RecentContext,
    ) -> list[CoachFinding]:
        """Activities with a configured remind_after_gap_days that have been missed."""
        findings: list[CoachFinding] = []

        for name, pts in self._config.positives.items():
            if float(pts) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue

            remind_after = self._rules.get_remind_after_gap_days(name)
            if remind_after is None:
                continue

            # Find days since last occurrence
            days_since = self._days_since_last(name, today)
            if days_since is None or days_since < remind_after:
                continue

            # Gap exceeds threshold
            confidence = min(0.60 + (days_since - remind_after) / 30 * 0.25, 0.90)
            confidence += self._rules.get_coach_confidence_mod(name)

            coach_mode = self._rules.get_coach_mode(name)
            if coach_mode == "observe_only":
                confidence *= 0.5

            if confidence < MIN_CONFIDENCE:
                continue

            impact = min(0.3 + (float(pts) / 8.0) * 0.4, 0.80)

            summary = (
                f"It's been {days_since}d since your last {name} "
                f"(reminder configured after {remind_after}d gap). "
                f"This habit earns {float(pts):.1f} pts when logged."
            )

            findings.append(CoachFinding(
                kind="streak_gap",
                title=f"{name} Gap Reminder",
                summary=summary,
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                subject=name,
            ))

        return findings

    # ── Analyzer 4: Negative clusters ───────────────────────────────────

    def _analyze_negative_clusters(
        self,
        baseline: dict[str, dict[str, float]],
        recent: RecentContext,
    ) -> list[CoachFinding]:
        """A negative is appearing more frequently in recent days."""
        findings: list[CoachFinding] = []
        short_days = self.LOOKBACK_SHORT

        for name, pts in self._config.negatives.items():
            if float(pts) <= 0:
                continue

            bl = baseline.get(name)
            if bl is None or bl["count"] < self.MIN_OCCURRENCES_LONG:
                continue

            recent_count = recent.neg_counts_7d.get(name, 0)
            if recent_count < 2:
                continue  # not a pattern yet

            recent_rate = recent_count / short_days
            baseline_rate = bl["rate_per_day"]

            if baseline_rate < 0.02:
                continue

            surge_ratio = recent_rate / baseline_rate if baseline_rate > 0 else 1.0
            if surge_ratio < 2.0:
                continue

            confidence = min(0.55 + min(surge_ratio / 8.0, 0.30), 0.85)
            if confidence < MIN_CONFIDENCE:
                continue

            impact = min(0.35 + (float(pts) / 20.0) * 0.40, 0.90)

            summary = (
                f"{name} logged {recent_count}× in the last {short_days}d "
                f"(vs your baseline ~{baseline_rate:.1f}×/day). "
                f"That's {int((surge_ratio - 1) * 100)}% above normal — "
                f"watch for a developing pattern."
            )

            findings.append(CoachFinding(
                kind="negative_cluster",
                title=f"{name} Emerging Pattern",
                summary=summary,
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                subject=name,
            ))

        return findings

    # ── Helpers ─────────────────────────────────────────────────────────

    def _days_since_last(self, name: str, today: date) -> int | None:
        """Days since *name* was last logged as a positive (or None if never)."""
        for delta in range(1, 366):
            d_str = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
            entries = self._cache.positives_raw.get(d_str, [])
            if any(e.get("name") == name for e in entries):
                return delta
        return None
