"""Week Brief Service — strategic week-horizon guidance.

Produces imperative Focus / Protect / Skip lists that tell you what to
do, keep, or cut this week — not statistical summaries but concrete
actions rooted in your personal data and config.

Consumes:
- MetricsService (week pace, per-project hours)
- DataCache (raw positives/negatives)
- Config (points, category_natures, activity_rules)
- Discovery list + Coach findings (from InsightsBundleService)
- RecentContext (neg_counts_7d, best_recent, positive_lift)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache
from toggl.config import Config
from toggl.services.coach import CoachFinding
from toggl.widgets.icons import dot_sep
from toggl.services.discovery import Discovery
from toggl.services.metrics import MetricsService
from toggl.services.recent_context import RecentContext, build_recent_context

logger = logging.getLogger("TStat")


@dataclass
class WeekAction:
    """A single imperative action for the week."""
    name: str
    imperative: str       # "Track ~2h — neglected 21d, was 1.2h/d"
    evidence: str = ""    # optional dim supporting line


@dataclass
class WeekBrief:
    headline: str              # "Week +2.1 vs pace · 3d left · need ~1.4/d"
    focus: list[WeekAction]    # do more this week
    protect: list[WeekAction]  # habits/projects to keep
    skip: list[WeekAction]     # cut / avoid this week


class WeekBriefService:
    """Produces the week-level Focus / Protect / Skip plan."""

    NEGLECT_DAYS = 21           # days idle to trigger neglect
    NEGLECT_MIN_IMPORTANCE = 10  # minimum total_hours * rate to trigger
    RECENT_NEG_THRESHOLD = 2     # repeat negatives threshold
    MAX_FOCUS = 3
    MAX_PROTECT = 2
    MAX_SKIP = 4

    def __init__(
        self,
        cache: DataCache,
        metrics: MetricsService,
        config: Config,
        activity_rules: ActivityRules,
        recovery_ignore: frozenset[str] | None = None,
    ) -> None:
        self._cache = cache
        self._metrics = metrics
        self._config = config
        self._rules = activity_rules
        self._recovery_ignore = recovery_ignore or frozenset()

    def compute(
        self,
        discoveries: list[Discovery] | None = None,
        coach_findings: list[CoachFinding] | None = None,
        recent: RecentContext | None = None,
    ) -> WeekBrief:
        today = date.today()
        if recent is None:
            recent = build_recent_context(self._metrics, self._cache, lookback_days=7)

        # ── Headline: week pace ──
        from toggl.cache import get_current_week
        from toggl.cache import get_week_dates as _get_week_dates
        week_str = get_current_week()
        dashboard = self._metrics.get_week_dashboard_rows(week_str)
        summary = dashboard["summary"]
        delta = summary.get("delta", 0.0)
        actual = summary.get("actual", 0.0)
        days_left = self._days_left_in_week(today, week_str)
        per_day = round(abs(delta) / max(days_left, 1), 1) if delta < 0 else 0.0

        headline = (
            f"Week {actual:+.1f} ({delta:+.1f} vs pace)"
        )
        if days_left > 0:
            headline += f"{dot_sep()}{days_left}d left"
        if per_day > 0:
            headline += f"{dot_sep()}need ~{per_day}/d"

        # ── Aggregated week data ──
        week_hours = self._compute_week_project_hours(today, week_str)

        # ── Build sections ──
        focus = self._build_focus(today, recent, week_hours, discoveries, coach_findings)
        protect = self._build_protect(recent, discoveries, coach_findings)
        skip = self._build_skip(today, recent, week_hours, discoveries, coach_findings)

        # Sort by positive_lift for better prioritization
        if recent.positive_lift:
            for section in (focus, protect, skip):
                section.sort(
                    key=lambda a: (
                        recent.positive_lift.get(a.name, 0.0)
                        if a.name not in recent.neg_counts_7d
                        else -abs(recent.positive_lift.get(a.name, 0.0))
                    ),
                    reverse=True,
                )

        return WeekBrief(
            headline=headline,
            focus=focus[:self.MAX_FOCUS],
            protect=protect[:self.MAX_PROTECT],
            skip=skip[:self.MAX_SKIP],
        )

    # ── Focus: what to do more of this week ──────────────────────────────

    def _build_focus(
        self,
        today: date,
        recent: RecentContext,
        week_hours: dict[str, float],
        discoveries: list[Discovery] | None,
        coach_findings: list[CoachFinding] | None,
    ) -> list[WeekAction]:
        actions: list[WeekAction] = []
        seen: set[str] = set()

        # 1. Neglected high-value projects
        for name, rate in self._config.points.items():
            if not rate or float(rate) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue
            if name in self._config.discovery_ignore or name in self._recovery_ignore:
                continue
            days_since = self._days_since_tracked(name, today)
            if days_since is None or days_since < self.NEGLECT_DAYS:
                continue
            total_h = self._total_hours(name)
            importance = total_h * float(rate)
            if importance < self.NEGLECT_MIN_IMPORTANCE:
                continue
            hrs = self._config.default_hours.get(name, 1.0)
            h = int(hrs)
            m = int((hrs - h) * 60)
            amt = f"{h}h" if h >= 1 else f"{m}m"
            actions.append(WeekAction(
                name=name,
                imperative=f"Track {name} ~{amt} \u2014 neglected {days_since}d, was {total_h:.1f}h total history",
                evidence=f"+{float(rate):.0f}/h{dot_sep()}{days_since}d idle{dot_sep()}importance {importance:.1f}",
            ))
            seen.add(name)

        # 2. Positive-rate projects with 0h tracked this week
        for name, rate in self._config.points.items():
            if name in seen:
                continue
            if not rate or float(rate) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue
            if name in self._config.discovery_ignore or name in self._recovery_ignore:
                continue
            if float(rate) < 2.0:
                continue
            if week_hours.get(name, 0) >= 0.25:
                continue
            hrs = self._config.default_hours.get(name, 1.0)
            h = int(hrs)
            m = int((hrs - h) * 60)
            amt = f"{h}h" if h >= 1 else f"{m}m"
            actions.append(WeekAction(
                name=name,
                imperative=f"Track {name} ~{amt} \u2014 not logged this week{dot_sep()}+{float(rate):.0f}/h",
                evidence=f"+{float(rate):.0f}/h 0h logged this week",
            ))
            seen.add(name)
            if len(actions) >= self.MAX_FOCUS:
                break

        # 3. Coach frequency drops and streak gaps
        if coach_findings:
            for f in coach_findings:
                if f.subject in seen:
                    continue
                if f.kind in ("frequency_drop", "streak_gap"):
                    if not self._rules.should_suggest(f.subject):
                        continue
                    if self._rules.get_coach_mode(f.subject) == "observe_only":
                        continue
                    pts = self._config.positives.get(f.subject, 0)
                    actions.append(WeekAction(
                        name=f.subject,
                        imperative=f"Resume {f.subject} \u2014 {f.summary.split(chr(10))[0][:120]}",
                        evidence=f"Coach: {f.kind}{dot_sep()}+{float(pts):.0f} pts",
                    ))
                    seen.add(f.subject)
                    if len(actions) >= self.MAX_FOCUS:
                        break

        return actions[:self.MAX_FOCUS]

    # ── Protect: what to keep doing ──────────────────────────────────────

    def _build_protect(
        self,
        recent: RecentContext,
        discoveries: list[Discovery] | None,
        coach_findings: list[CoachFinding] | None,
    ) -> list[WeekAction]:
        actions: list[WeekAction] = []
        seen: set[str] = set()

        # 1. Discovery positive drivers
        if discoveries:
            for d in discoveries:
                if d.kind == "positive_driver" and d.subject not in seen:
                    if not self._rules.should_suggest(d.subject):
                        continue
                    if d.subject in self._recovery_ignore:
                        continue
                    actions.append(WeekAction(
                        name=d.subject,
                        imperative=f"Keep {d.subject} \u2014 correlates with your best days",
                        evidence=d.summary[:150],
                    ))
                    seen.add(d.subject)

        # 2. Coach frequency surges
        if coach_findings:
            for f in coach_findings:
                if f.subject in seen:
                    continue
                if f.kind == "frequency_surge":
                    if not self._rules.should_suggest(f.subject):
                        continue
                    if f.subject in self._recovery_ignore:
                        continue
                    pts = self._config.positives.get(f.subject, 0)
                    actions.append(WeekAction(
                        name=f.subject,
                        imperative=f"Keep {f.subject} \u2014 on a roll, above your baseline",
                        evidence=f"Coach: frequency_surge{dot_sep()}+{float(pts):.0f} pts",
                    ))
                    seen.add(f.subject)

        # 3. Best recent day positives
        if recent.best_recent and recent.best_recent.positives:
            for hab in recent.best_recent.positives:
                if hab in seen:
                    continue
                if not self._rules.should_suggest(hab):
                    continue
                if hab in self._recovery_ignore:
                    continue
                pts = self._config.positives.get(hab, 0)
                actions.append(WeekAction(
                    name=hab,
                    imperative=f"Keep {hab} \u2014 on your best recent day ({recent.best_recent.label})",
                    evidence=f"Best day net: {recent.best_recent.net:+.1f}{dot_sep()}+{float(pts):.0f} pts",
                ))
                seen.add(hab)
                if len(actions) >= self.MAX_PROTECT:
                    break

        return actions[:self.MAX_PROTECT]

    # ── Skip: what to cut / avoid this week ──────────────────────────────

    def _build_skip(
        self,
        today: date,
        recent: RecentContext,
        week_hours: dict[str, float],
        discoveries: list[Discovery] | None,
        coach_findings: list[CoachFinding] | None,
    ) -> list[WeekAction]:
        actions: list[WeekAction] = []
        seen: set[str] = set()

        # 1. Repeat negatives (2+ in last 7d)
        for name, count in recent.neg_counts_7d.items():
            if count < self.RECENT_NEG_THRESHOLD:
                continue
            if name in self._recovery_ignore:
                continue
            pts = self._config.negatives.get(name, 5)
            actions.append(WeekAction(
                name=name,
                imperative=f"Cut {name} \u2014 logged {count}\u00d7 this week",
                evidence=f"-{float(pts):.0f} pts each{dot_sep()}breaking this pattern has high impact",
            ))
            seen.add(name)
            if len(actions) >= self.MAX_SKIP:
                break

        # 2. Discovery failure_mode subjects
        if discoveries:
            for d in discoveries:
                if d.subject in seen:
                    continue
                if d.kind == "failure_mode":
                    actions.append(WeekAction(
                        name=d.subject,
                        imperative=f"Avoid {d.subject} on bad days \u2014 shows up more when net is negative",
                        evidence=d.summary[:150],
                    ))
                    seen.add(d.subject)
                    if len(actions) >= self.MAX_SKIP:
                        break

        # 3. avoid-category projects with hours this week
        if len(actions) < self.MAX_SKIP:
            week_start = today - timedelta(days=today.weekday())
            for name, hrs in week_hours.items():
                if name in seen:
                    continue
                if hrs < 0.25:
                    continue
                if name in self._recovery_ignore:
                    continue
                rate = self._config.points.get(name, 0)
                if not self._rules.should_suggest(name) or float(rate) < 0:
                    actions.append(WeekAction(
                        name=name,
                        imperative=f"Don't add {name} time \u2014 already {hrs:.1f}h this week",
                        evidence=f"{float(rate):.0f}/h \u2014 avoid-category project with active hours",
                    ))
                    seen.add(name)
                    if len(actions) >= self.MAX_SKIP:
                        break

        # 4. Coach negative_cluster
        if coach_findings and len(actions) < self.MAX_SKIP:
            for f in coach_findings:
                if f.subject in seen:
                    continue
                if f.kind == "negative_cluster":
                    pts = self._config.negatives.get(f.subject, 5)
                    actions.append(WeekAction(
                        name=f.subject,
                        imperative=f"Watch {f.subject} \u2014 appearing more than usual recently",
                        evidence=f"Coach: negative_cluster{dot_sep()}-{float(pts):.0f} pts each",
                    ))
                    seen.add(f.subject)
                    if len(actions) >= self.MAX_SKIP:
                        break

        return actions[:self.MAX_SKIP]

    # ── Week data helpers ────────────────────────────────────────────────

    def _compute_week_project_hours(
        self, today: date, week_str: str
    ) -> dict[str, float]:
        """Sum of project hours so far this week."""
        from toggl.cache import get_week_dates as _get_week_dates
        start_d, end_d = _get_week_dates(week_str)
        cutoff = min(end_d, today)
        result: dict[str, float] = {}
        d = start_d
        while d <= cutoff:
            d_str = d.strftime("%Y-%m-%d")
            for proj, hrs in self._cache.daily_data.get(d_str, {}).items():
                result[proj] = result.get(proj, 0.0) + hrs
            d += timedelta(days=1)
        return result

    def _days_since_tracked(self, name: str, today: date) -> int | None:
        """Days since *name* was last tracked (has hours logged)."""
        for delta in range(0, 366):
            d_str = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
            projs = self._cache.daily_data.get(d_str, {})
            if projs.get(name, 0) > 0:
                return delta
        return None

    def _total_hours(self, name: str) -> float:
        """Total hours ever tracked against *name*."""
        total = 0.0
        for d_str, projs in self._cache.daily_data.items():
            total += projs.get(name, 0.0)
        return total

    def _days_left_in_week(self, today: date, week_str: str) -> int:
        from toggl.cache import get_week_dates as _get_week_dates
        _, end = _get_week_dates(week_str)
        if today > end:
            return 0
        return (end - today).days + 1
