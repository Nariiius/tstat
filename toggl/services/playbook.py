"""Playbook engine — concrete daily action plans with bucket-based selection.

Uses the ActivityRules system for configurable behaviour.
Candidates are split into habit and project buckets, scored by
points_per_hour × controllability × availability × repeatability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache, get_current_week, get_week_dates
from toggl.services.metrics import MetricsService
from toggl.services.recent_context import (
    RecentContext,
    build_recent_context,
    format_day_net,
)


@dataclass
class PlaybookStep:
    action: str
    label: str
    amount: str
    points: float
    reason: str = ""


@dataclass
class Playbook:
    goal: str
    headline: str
    steps: list[PlaybookStep] = field(default_factory=list)
    alternatives: list[PlaybookStep] = field(default_factory=list)
    expected_gain: float = 0.0
    done_today: list[str] = field(default_factory=list)
    blocked_today: list[tuple[str, str]] = field(default_factory=list)
    low_control: list[tuple[str, str]] = field(default_factory=list)
    gap_note: str = ""
    lookback: list[str] = field(default_factory=list)
    focus_line: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""

    @property
    def verdict(self) -> str:
        """Short label for the current verdict / goal state."""
        return {
            "on_track": "on_track",
            "hit_today_target": "hit_today_target",
            "fix_week": "fix_week",
            "start_tracking": "start_tracking",
        }.get(self.goal, self.goal)


@dataclass
class _Candidate:
    """Internal candidate representation for bucket-based selection."""
    name: str
    action: str          # "log" or "track"
    label: str
    amount: str
    points: float
    rank_score: float    # points_per_hour × controllability × availability × repeatability
    reason: str
    is_habit: bool       # True for binary positives, False for tracked projects


class PlaybookService:
    """Builds actionable playbooks from metrics + config + activity rules."""

    MAX_STEPS = 6
    MAX_HABITS = 2
    MIN_PROJECTS = 1

    def __init__(
        self,
        metrics: MetricsService,
        cache: DataCache,
        points: dict[str, int | float],
        positives: dict[str, int | float],
        activity_rules: ActivityRules,
        get_daily_target: Callable[[], float],
        recovery_ignore: list[str] | None = None,
        controllability_map: dict[str, float] | None = None,
        availability_overrides: dict[str, dict] | None = None,
        low_control_reasons: dict[str, str] | None = None,
        default_hours: dict[str, float] | None = None,
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._points = points
        self._positives = positives
        self._rules = activity_rules
        self._get_daily_target = get_daily_target
        self._recovery_ignore = frozenset(recovery_ignore or [])
        self._controllability = controllability_map or {}
        self._availability_overrides = availability_overrides or {}
        self._low_control_reasons = low_control_reasons or {}
        self._default_hours = default_hours or {}

    # ────────────────────────────────────────
    # Main entry point
    # ────────────────────────────────────────

    def compute(self, recent: RecentContext | None = None) -> Playbook:
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        generated_at = datetime.now().isoformat(timespec="seconds")

        if not self._has_any_data():
            return Playbook(
                goal="start_tracking",
                headline="Start tracking to see your playbook",
                steps=[
                    PlaybookStep(
                        action="log",
                        label="a project or positive habit",
                        amount="\u00d71",
                        points=0.0,
                        reason="No activity data yet",
                    )
                ],
                expected_gain=0.0,
                blocked_today=[],
                low_control=[],
                generated_at=generated_at,
            )

        if recent is None:
            recent = build_recent_context(self._metrics, self._cache, lookback_days=14)
        lookback, focus_line = self._build_lookback(recent, today)

        day = self._metrics.get_day_metrics(today_str)
        today_net = day["net"]
        target = float(self._get_daily_target())
        gap = round(target - today_net, 1)
        logged_today = self._positives_logged_today(today_str)

        week = get_current_week()
        dashboard = self._metrics.get_week_dashboard_rows(week)
        summary = dashboard["summary"]
        days_left = self._days_left_in_week(today, week)

        context: dict[str, Any] = {
            "today_net": today_net,
            "daily_target": target,
            "gap": gap,
            "days_left": days_left,
            "week_delta": summary.get("delta", 0),
        }

        # Build blocked and low-control sections
        blocked_today = self._build_blocked_today(today_str, logged_today)
        low_control = self._build_low_control_section(logged_today)

        if gap > 0.5:
            steps, alternatives, expected_gain, gap_note = self._build_gap_playbook(
                gap, today_str, logged_today, recent, context
            )
            headline = f"Need {self._fmt_pts(gap)} today (at {self._fmt_pts(today_net)})"
            return Playbook(
                goal="hit_today_target",
                headline=headline,
                steps=steps,
                alternatives=alternatives,
                expected_gain=expected_gain,
                done_today=sorted(logged_today),
                blocked_today=blocked_today,
                low_control=low_control,
                gap_note=gap_note,
                lookback=lookback,
                focus_line=focus_line,
                context=context,
                generated_at=generated_at,
            )

        week_delta = summary.get("delta", 0)
        if week_delta < -0.5 and days_left > 0:
            per_day = round(abs(week_delta) / days_left, 1)
            steps, alternatives, expected_gain, gap_note = self._build_gap_playbook(
                per_day, today_str, logged_today, recent, context
            )
            headline = (
                f"Week {self._fmt_pts(summary.get('actual', 0))} "
                f"({self._fmt_pts(week_delta)} vs pace) \u2014 ~{per_day}/day for {days_left}d"
            )
            context["per_day_needed"] = per_day
            return Playbook(
                goal="fix_week",
                headline=headline,
                steps=steps,
                alternatives=alternatives,
                expected_gain=expected_gain,
                done_today=sorted(logged_today),
                blocked_today=blocked_today,
                low_control=low_control,
                gap_note=gap_note,
                lookback=lookback,
                focus_line=focus_line,
                context=context,
                generated_at=generated_at,
            )

        # On track \u2014 show stretch actions
        steps, alternatives, expected_gain = self._build_on_track_playbook(today_str, logged_today, recent)
        headline = f"On track at {self._fmt_pts(today_net)} (target {self._fmt_pts(target)})"
        return Playbook(
            goal="on_track",
            headline=headline,
            steps=steps,
            alternatives=alternatives,
            expected_gain=expected_gain,
            done_today=sorted(logged_today),
            blocked_today=blocked_today,
            low_control=low_control,
            lookback=lookback,
            focus_line=focus_line,
            context=context,
            generated_at=generated_at,
        )

    # ────────────────────────────────────────
    # Bucket-based playbook builders
    # ────────────────────────────────────────

    def _build_gap_playbook(
        self,
        gap: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
        context: dict[str, Any],
    ) -> tuple[list[PlaybookStep], list[PlaybookStep], float, str]:
        """Build playbook for gap-filling or week recovery."""
        habit_candidates = self._gather_habit_candidates(today_str, logged_today, recent)
        project_candidates = self._gather_project_candidates(today_str, logged_today, recent)

        steps, alternatives = self._select_steps(gap, habit_candidates, project_candidates)
        expected_gain = round(sum(s.points for s in steps), 1)

        # Build gap note with week pace projection
        gap_note = f"Expected gain [bold]{expected_gain:+.1f}[/] pts"
        if expected_gain > 0:
            wd = context.get("week_delta", 0)
            dl = max(context.get("days_left", 1), 1)
            cp = wd / dl
            np = (wd + expected_gain) / dl
            remainder = round(-np, 1) if np < 0 else 0
            gap_note = (
                f"Playbook adds [bold]{expected_gain:+.1f}[/] to today. "
                f"Week pace {cp:+.1f}/d \u2192 {np:+.1f}/d"
                + (f"  (still need ~{remainder}/d)" if remainder > 0 else "")
            )

        return steps, alternatives, expected_gain, gap_note

    def _build_on_track_playbook(
        self,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
    ) -> tuple[list[PlaybookStep], list[PlaybookStep], float]:
        """Build playbook for on-track days — stretch goals while ahead."""
        habit_candidates = self._gather_habit_candidates(today_str, logged_today, recent)
        project_candidates = self._gather_project_candidates(today_str, logged_today, recent)

        # Use full selection with bucket caps like gap playbook
        steps, alternatives = self._select_steps(0, habit_candidates, project_candidates)

        # Mark reasons as stretch goals if no specific reason
        for s in steps:
            if not s.reason or s.reason == "Not tracked yet today" or s.reason.startswith("Quick"):
                s.reason = "Stretch \u2014 bank extra points while ahead"
        for a in alternatives:
            if not a.reason or a.reason == "Not tracked yet today" or a.reason.startswith("Quick"):
                a.reason = "Stretch \u2014 bank extra points while ahead"

        expected_gain = round(sum(s.points for s in steps), 1)
        return steps, alternatives, expected_gain

    # ────────────────────────────────────────
    # Candidate gathering
    # ────────────────────────────────────────

    def _gather_habit_candidates(
        self, today_str: str, logged_today: set[str], recent: RecentContext | None = None
    ) -> list[_Candidate]:
        """Gather binary positive habits as candidates."""
        candidates: list[_Candidate] = []
        positive_lift = recent.positive_lift if recent else {}

        for name, pts in self._positives.items():
            if not self._rules.should_suggest(name):
                continue
            if float(pts) <= 0:
                continue
            if name in self._recovery_ignore:
                continue

            # Check if already done today (once-per-day)
            repeatability = 1.0
            if name in logged_today and self._rules.is_once_per_day(name):
                repeatability = 0.0

            controllability = self._get_controllability(name)
            availability = self._get_availability(name)

            # Skip if blocked
            if availability == 0.0 or repeatability == 0.0:
                continue

            # Effort: ~15 min for any habit
            effort_hours = 0.25
            points_per_hour = float(pts) / effort_hours
            rank_score = points_per_hour * controllability * availability * repeatability

            # Build reason
            gap_days = self._days_since_last(name)
            reason = f"Quick {float(pts):.1f} pts"
            remind = self._rules.get_remind_after_gap_days(name)
            if remind is not None:
                if gap_days >= remind:
                    reason = f"\u23f1 {gap_days}d since last \u2014 remind after {remind}d \u00b7 +{float(pts):.0f} pts"
                elif gap_days >= max(remind - 1, 1):
                    reason = f"\u23f1 {gap_days}d since last \u00b7 streak at risk \u00b7 +{float(pts):.0f} pts"
            lift = positive_lift.get(name, 0.0)
            if lift >= 2.0:
                reason += f"  (net {lift:+.1f} when you do this)"

            candidates.append(_Candidate(
                name=name,
                action="log",
                label=name,
                amount="×1",
                points=float(pts),
                rank_score=rank_score,
                reason=reason,
                is_habit=True,
            ))

        return candidates

    def _gather_project_candidates(
        self, today_str: str, logged_today: set[str], recent: RecentContext | None = None
    ) -> list[_Candidate]:
        """Gather tracked projects with positive rates as candidates."""
        candidates: list[_Candidate] = []
        positive_lift = recent.positive_lift if recent else {}
        projs = self._cache.get_day_projects(today_str) or {}

        for name, rate in self._points.items():
            if not rate or float(rate) <= 0:
                continue
            if not self._rules.should_suggest(name):
                continue

            # Skip if already tracked today
            already = projs.get(name, 0)
            if already >= 0.25:
                continue

            controllability = self._get_controllability(name)
            availability = self._get_availability(name)
            repeatability = 1.0  # Projects are always repeatable

            if availability == 0.0:
                continue

            # Use default hours from config, or 1.0
            effort_hours = self._default_hours.get(name, 1.0)
            points_per_hour = float(rate)
            display_points = round(points_per_hour * effort_hours, 1)
            rank_score = points_per_hour * controllability * availability * repeatability

            # Format amount
            h = int(effort_hours)
            m = int((effort_hours - h) * 60)
            amount = f"{h}h" if h >= 1 else (f"{m}m" if m else "30m")

            reason = "Not tracked yet today"
            lift = positive_lift.get(name, 0.0)
            if lift >= 2.0:
                reason += f"  (net {lift:+.1f} when you do this)"

            candidates.append(_Candidate(
                name=name,
                action="track",
                label=name,
                amount=amount,
                points=display_points,
                rank_score=rank_score,
                reason=reason,
                is_habit=False,
            ))

        return candidates

    # ────────────────────────────────────────
    # Selection algorithm
    # ────────────────────────────────────────

    def _select_steps(
        self,
        gap: float,
        habit_candidates: list[_Candidate],
        project_candidates: list[_Candidate],
    ) -> tuple[list[PlaybookStep], list[PlaybookStep]]:
        """Select up to MAX_STEPS with bucket constraints.
        Returns (steps, alternatives) where alternatives are the next best unused candidates."""
        habits = sorted(habit_candidates, key=lambda c: -c.rank_score)
        projects = sorted(project_candidates, key=lambda c: -c.rank_score)

        steps: list[PlaybookStep] = []
        expected_gain = 0.0
        habit_count = 0
        project_count = 0
        used_names: set[str] = set()

        # Guarantee at least MIN_PROJECTS project if available
        while len(steps) < self.MIN_PROJECTS and projects:
            best_proj = projects.pop(0)
            steps.append(PlaybookStep(
                action=best_proj.action,
                label=best_proj.name,
                amount=best_proj.amount,
                points=best_proj.points,
                reason=best_proj.reason,
            ))
            expected_gain += best_proj.points
            project_count += 1
            used_names.add(best_proj.name)

        # Fill remaining slots from merged pool, respecting caps
        remaining = sorted(
            [c for c in habits + projects if c.name not in used_names],
            key=lambda c: -c.rank_score
        )

        for candidate in remaining:
            if len(steps) >= self.MAX_STEPS:
                break
            if candidate.is_habit and habit_count >= self.MAX_HABITS:
                continue
            if candidate.name in used_names:
                continue

            steps.append(PlaybookStep(
                action=candidate.action,
                label=candidate.name,
                amount=candidate.amount,
                points=candidate.points,
                reason=candidate.reason,
            ))
            expected_gain += candidate.points
            used_names.add(candidate.name)
            if candidate.is_habit:
                habit_count += 1
            else:
                project_count += 1

        # Capture 2–3 runner-up candidates as alternatives
        alternatives: list[PlaybookStep] = []
        alt_pool = sorted(
            [c for c in habits + projects if c.name not in used_names],
            key=lambda c: -c.rank_score
        )
        for candidate in alt_pool:
            if len(alternatives) >= 3:
                break
            alternatives.append(PlaybookStep(
                action=candidate.action,
                label=candidate.name,
                amount=candidate.amount,
                points=candidate.points,
                reason=candidate.reason,
            ))
            used_names.add(candidate.name)

        return steps, alternatives

    # ────────────────────────────────────────
    # Blocked and low-control sections
    # ────────────────────────────────────────

    def _build_blocked_today(
        self, today_str: str, logged_today: set[str]
    ) -> list[tuple[str, str]]:
        """Build list of (name, reason) for truly blocked actions."""
        blocked: list[tuple[str, str]] = []

        # Once-per-day habits already done
        for name in self._positives:
            if not self._rules.should_suggest(name):
                continue
            if name in self._recovery_ignore:
                continue
            if name in logged_today and self._rules.is_once_per_day(name):
                blocked.append((name, "already done today"))

        # Time-window blocked (e.g., Sleep 8+ Hours before 9pm)
        for name in self._positives:
            if not self._rules.should_suggest(name):
                continue
            if name in self._recovery_ignore:
                continue
            if name in logged_today:
                continue  # Already in blocked above
            avail = self._get_availability(name)
            if avail == 0.0:
                override = self._availability_overrides.get(name, {})
                reason = override.get("blocked_reason", "not available now")
                blocked.append((name, reason))

        return sorted(blocked, key=lambda x: x[0])

    def _build_low_control_section(
        self, logged_today: set[str]
    ) -> list[tuple[str, str]]:
        """Build list of (name, reason) for low-control actions."""
        low_control: list[tuple[str, str]] = []

        for name, reason in self._low_control_reasons.items():
            if not self._rules.should_suggest(name):
                continue
            if name in self._recovery_ignore:
                continue
            if name in logged_today:
                continue
            low_control.append((name, reason))

        return sorted(low_control, key=lambda x: x[0])

    # ────────────────────────────────────────
    # Controllability and availability
    # ────────────────────────────────────────

    def _get_controllability(self, name: str) -> float:
        """Get controllability score (0.0-1.0), default 1.0."""
        return self._controllability.get(name, 1.0)

    def _get_availability(self, name: str) -> float:
        """Get availability score (0.0-1.0) based on time-of-day overrides."""
        override = self._availability_overrides.get(name)
        if override is None:
            return 1.0

        if override.get("type") == "time_window":
            now = datetime.now()
            available_after = override.get("available_after", "21:00")
            hour, minute = map(int, available_after.split(":"))
            if now.hour > hour or (now.hour == hour and now.minute >= minute):
                return 1.0
            return override.get("before_multiplier", 0.0)

        return 1.0

    # ────────────────────────────────────────
    # Lookback
    # ────────────────────────────────────────

    def _build_lookback(
        self, recent: RecentContext, today: date
    ) -> tuple[list[str], str]:
        lines: list[str] = []
        focus = ""

        if recent.yesterday:
            y = recent.yesterday
            y_str = f"[#8d98a7]Yesterday ({y.label}):[/] net {format_day_net(y.net)}"
            tags: list[str] = []
            if y.negatives:
                tags.append(f"[#ff5f5f]{', '.join(y.negatives)}[/]")
            if y.positives:
                tags.append(f"[#37d994]{', '.join(y.positives)}[/]")
            if tags:
                y_str += f"  {' · '.join(tags)}"
            if y.top_project and y.top_project_hours >= 0.5:
                y_str += f"  ({y.top_project} {y.top_project_hours:.1f}h)"
            lines.append(y_str)

        if recent.worst_recent and recent.best_recent:
            if recent.worst_recent.date_str != recent.best_recent.date_str:
                w, b = recent.worst_recent, recent.best_recent
                lines.append(
                    f"[#8d98a7]Last 14d low:[/] {w.label} {format_day_net(w.net)}"
                    + (f" ({', '.join(w.negatives)})" if w.negatives else "")
                )
                lines.append(
                    f"[#8d98a7]Last 14d high:[/] {b.label} {format_day_net(b.net)}"
                    + (f" ({', '.join(b.positives)})" if b.positives else "")
                )

        repeat_negs = [(n, c) for n, c in recent.neg_counts_7d.items() if c >= 2]
        if repeat_negs:
            repeat_negs.sort(key=lambda x: -x[1])
            n, c = repeat_negs[0]
            lines.append(
                f"[#ff5f5f]Mistake pattern:[/] {n} logged {c}× in the last 7 days "
                f"— cut it completely today to break the cycle."
            )
            focus = f"Don't repeat {n} today — it keeps showing up on bad days."

        if recent.best_recent and recent.best_recent.positives:
            win = recent.best_recent
            habit = win.positives[0]
            if habit not in focus:
                focus = (
                    f"Your best recent day ({win.label}, {format_day_net(win.net)}) "
                    f"included {habit} — do that again first."
                )

        if not focus and recent.yesterday and recent.yesterday.net < 0:
            focus = (
                f"Yesterday was {format_day_net(recent.yesterday.net)} — "
                f"front-load one high-value log before you get distracted."
            )

        return lines[:4], focus

    def _has_any_data(self) -> bool:
        return bool(
            self._cache.daily_data
            or self._cache.negatives_raw
            or self._cache.positives_raw
        )

    # ────────────────────────────────────────
    # Logging / date helpers
    # ────────────────────────────────────────

    def _positives_logged_today(self, today_str: str) -> set[str]:
        names: set[str] = set()
        for entry in self._cache.positives_raw.get(today_str, []):
            names.add(entry["name"])
        return names

    def _positives_log_count_today(self, today_str: str, name: str) -> int:
        return sum(
            1 for e in self._cache.positives_raw.get(today_str, [])
            if e["name"] == name
        )

    def _days_left_in_week(self, today: date, week: str) -> int:
        _, end = get_week_dates(week)
        if today > end:
            return 0
        return (end - today).days + 1

    def _consecutive_days_with(self, name: str, lookback_days: int = 14) -> int:
        """How many consecutive recent days have *name* been logged?"""
        count = 0
        today = date.today()
        for d in range(1, lookback_days + 1):
            d_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            if any(e["name"] == name for e in self._cache.positives_raw.get(d_str, [])):
                count += 1
            else:
                break
        return count

    def _days_since_last(self, name: str) -> int:
        """Days since *name* was last logged as a positive."""
        today = date.today()
        for d in range(1, 31):
            d_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            if any(
                e["name"] == name for e in self._cache.positives_raw.get(d_str, [])
            ):
                return d
        return 999

    @staticmethod
    def _fmt_pts(value: float) -> str:
        if value >= 0:
            return f"+{value:.1f}"
        return f"{value:.1f}"
