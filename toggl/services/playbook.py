"""Playbook engine — concrete daily/weekly action plans.

Uses the ActivityRules system for configurable behaviour instead of
hardcoded constants like ONCE_PER_DAY_POSITIVES or abs_cinema_mode.
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
    expected_gain: float = 0.0          # sum of top-3 step points
    done_today: list[str] = field(default_factory=list)
    blocked_today: list[str] = field(default_factory=list)
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


class PlaybookService:
    """Builds actionable playbooks from metrics + config + activity rules."""

    def __init__(
        self,
        metrics: MetricsService,
        cache: DataCache,
        points: dict[str, int | float],
        positives: dict[str, int | float],
        activity_rules: ActivityRules,
        get_daily_target: Callable[[], float],
        recovery_ignore: list[str] | None = None,
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._points = points
        self._positives = positives
        self._rules = activity_rules
        self._get_daily_target = get_daily_target
        self._recovery_ignore = frozenset(recovery_ignore or [])

    # ────────────────────────────────────────
    # Main entry point
    # ────────────────────────────────────────

    def compute(self) -> Playbook:
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        generated_at = datetime.now().isoformat(timespec="seconds")

        all_once_per_day = {n for n in self._positives if self._rules.is_once_per_day(n)}

        if not self._has_any_data():
            return Playbook(
                goal="start_tracking",
                headline="Start tracking to see your playbook",
                steps=[
                    PlaybookStep(
                        action="log",
                        label="a project or positive habit",
                        amount="×1",
                        points=0.0,
                        reason="No activity data yet",
                    )
                ],
                expected_gain=0.0,
                blocked_today=sorted(
                    n for n in all_once_per_day
                    if self._rules.should_suggest(n) and n not in self._recovery_ignore
                ) if all_once_per_day else [],
                generated_at=generated_at,
            )

        recent = build_recent_context(self._metrics, self._cache, lookback_days=14)
        lookback, focus_line = self._build_lookback(recent, today)

        day = self._metrics.get_day_metrics(today_str)
        today_net = day["net"]
        target = float(self._get_daily_target())
        gap = round(target - today_net, 1)
        logged_today = self._positives_logged_today(today_str)
        once_per_day_logged = {
            n for n in logged_today if self._rules.is_once_per_day(n)
        }
        blocked_today = sorted(
            n for n in (all_once_per_day - once_per_day_logged)
            if self._rules.should_suggest(n) and n not in self._recovery_ignore
        )

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

        if gap > 0.5:
            steps, gap_note = self._build_steps_for_gap(
                gap, today_str, logged_today, recent
            )
            expected_gain = round(sum(s.points for s in steps), 1)
            if expected_gain > 0:
                wd = context.get("week_delta", 0)
                dl = max(context.get("days_left", 1), 1)
                cp = wd / dl
                np = (wd + expected_gain) / dl
                gap_note = f"If completed: week pace {cp:+.1f}/d → {np:+.1f}/d"
            headline = f"Need {self._fmt_pts(gap)} today (at {self._fmt_pts(today_net)})"
            return Playbook(
                goal="hit_today_target",
                headline=headline,
                steps=steps,
                expected_gain=expected_gain,
                done_today=sorted(once_per_day_logged),
                blocked_today=blocked_today,
                gap_note=gap_note,
                lookback=lookback,
                focus_line=focus_line,
                context=context,
                generated_at=generated_at,
            )

        week_delta = summary.get("delta", 0)
        if week_delta < -0.5 and days_left > 0:
            per_day = round(abs(week_delta) / days_left, 1)
            recovery = self._metrics.get_recovery_rows(week, "WEEK")
            steps, gap_note = self._build_week_recovery_steps(
                recovery, per_day, today_str, logged_today, recent
            )
            expected_gain = round(sum(s.points for s in steps), 1)
            if expected_gain > 0:
                dl = max(days_left, 1)
                cp = week_delta / dl
                np = (week_delta + expected_gain) / dl
                gap_note = f"If completed: week pace {cp:+.1f}/d → {np:+.1f}/d"
            headline = (
                f"Week {self._fmt_pts(summary.get('actual', 0))} "
                f"({self._fmt_pts(week_delta)} vs pace) — ~{per_day}/day for {days_left}d"
            )
            context["per_day_needed"] = per_day
            return Playbook(
                goal="fix_week",
                headline=headline,
                steps=steps,
                expected_gain=expected_gain,
                done_today=sorted(once_per_day_logged),
                blocked_today=blocked_today,
                gap_note=gap_note,
                lookback=lookback,
                focus_line=focus_line,
                context=context,
                generated_at=generated_at,
            )

        stretch = self._stretch_step(today_str, logged_today, recent)
        steps = [stretch] if stretch else []
        headline = f"On track at {self._fmt_pts(today_net)} (target {self._fmt_pts(target)})"
        return Playbook(
            goal="on_track",
            headline=headline,
            steps=steps,
            expected_gain=round(sum(s.points for s in steps), 1),
            done_today=sorted(once_per_day_logged),
            blocked_today=blocked_today,
            lookback=lookback,
            focus_line=focus_line,
            context=context,
            generated_at=generated_at,
        )

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
                span_days = (date.fromisoformat(b.date_str) - date.fromisoformat(w.date_str)).days
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

    # ────────────────────────────────────────
    # Candidate gathering — no cap
    # ────────────────────────────────────────

    def _build_steps_for_gap(
        self,
        gap: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
    ) -> tuple[list[PlaybookStep], str]:
        candidates = self._gather_candidates(gap, today_str, logged_today, recent)
        candidates.sort(
            key=lambda c: (
                self._rules.get_priority_mod(c["label"]),
                -float(c.get("history_score", 0)),
                -float(c["efficiency"]),
                float(c.get("effort", 999)),
            )
        )
        steps: list[PlaybookStep] = []
        covered = 0.0
        used_labels: set[str] = set()

        for c in candidates:
            if c["label"] in used_labels:
                continue
            pts = float(c["points"])
            if pts <= 0:
                continue
            steps.append(
                PlaybookStep(
                    action=str(c["action"]),
                    label=str(c["label"]),
                    amount=str(c["amount"]),
                    points=pts,
                    reason=str(c.get("reason", "")),
                )
            )
            used_labels.add(str(c["label"]))
            covered += pts
            if len(steps) >= 3:
                break

        expected_gain = round(sum(s.points for s in steps), 1)
        gap_note = f"Expected gain [bold]{expected_gain:+.1f}[/] pts"

        return steps, gap_note

    def _build_week_recovery_steps(
        self,
        recovery: dict[str, Any],
        per_day: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
    ) -> tuple[list[PlaybookStep], str]:
        steps: list[PlaybookStep] = []
        rows = recovery.get("rows", [])
        for row in rows:
            if len(steps) >= 3:
                break
            cat = str(row.get("category", ""))
            if not self._rules.should_suggest(cat):
                continue
            amt = str(row.get("hours_needed", ""))
            if amt.startswith("×"):
                if cat in logged_today:
                    continue
                pts = self._positives.get(cat, 0)
                if pts <= 0:
                    continue
                reason = (
                    self._history_reason_for_label(cat, recent)
                    or f"Closes {float(pts):.1f} pts of week deficit"
                )
                steps.append(
                    PlaybookStep(
                        action="log",
                        label=cat,
                        amount=amt,
                        points=float(pts),
                        reason=reason,
                    )
                )
            else:
                rate = float(row.get("rate", 0) or 0)
                if not rate:
                    continue
                hours = max(per_day / rate, 0.25)
                hours = min(hours, 2.0)  # realistic session cap
                h = int(hours)
                m = int((hours - h) * 60)
                amount = f"{h}h" if h >= 1 else (f"{m}m" if m else "30m")
                pts = round(min(hours, per_day / rate) * rate, 1)
                steps.append(
                    PlaybookStep(
                        action="track",
                        label=cat,
                        amount=amount,
                        points=pts,
                        reason=f"~{per_day:.1f} pts/day pace needed",
                    )
                )
        expected_gain = round(sum(s.points for s in steps), 1)
        gap_note = f"Expected gain [bold]{expected_gain:+.1f}[/] pts per day"
        return steps, gap_note

    # ────────────────────────────────────────
    # History / reason helpers
    # ────────────────────────────────────────

    def _history_reason_for_label(self, label: str, recent: RecentContext) -> str:
        if recent.best_recent and label in recent.best_recent.positives:
            b = recent.best_recent
            return f"On your best recent day ({b.label}, {format_day_net(b.net)}) this was key"
        lift = recent.positive_lift.get(label)
        if lift is not None and lift >= 5:
            return (
                f"Days you log {label} average {lift:+.0f} more pts "
                f"— highest-impact habit in your data"
            )
        if lift is not None and lift >= 3:
            return f"Your last 7d average +{lift:.0f} pts higher on days you log this"
        if label in recent.neg_counts_7d and recent.neg_counts_7d[label] >= 2:
            return "Break the recent mistake streak and log something productive"
        return ""

    def _history_score(self, label: str, recent: RecentContext) -> float:
        score = 0.0
        if recent.best_recent and label in recent.best_recent.positives:
            score += 10
        lift = recent.positive_lift.get(label, 0)
        if lift >= 5:
            score += 8
        elif lift >= 3:
            score += 4
        if recent.best_recent and label == recent.best_recent.top_project:
            score += 6
        # Streak reminder boost
        remind = self._rules.get_remind_after_gap_days(label)
        if remind is not None:
            gap_days = self._days_since_last(label)
            if gap_days >= remind:
                score += 6 * min(gap_days / remind, 2.0)
        # Throttle for over-logging
        throttle = self._rules.get_throttle_after_days(label)
        if throttle is not None:
            consecutive = self._consecutive_days_with(label)
            if consecutive >= throttle:
                score -= 10
        return score

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

    # ────────────────────────────────────────
    # Candidate gatherer
    # ────────────────────────────────────────

    def _gather_candidates(
        self,
        gap: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        logged_combo_root: dict[str, str | None] = {}  # label → pair logged

        # ── Positives (habits) ──
        for name, pts in sorted(
            self._positives.items(), key=lambda x: -float(x[1])
        ):
            if not self._rules.should_suggest(name):
                continue
            if pts <= 0:
                continue
            if name in logged_today and self._rules.is_once_per_day(name):
                continue
            reason = self._history_reason_for_label(name, recent)
            if not reason:
                # Check for streak reminders
                remind = self._rules.get_remind_after_gap_days(name)
                if remind is not None:
                    gap_days = self._days_since_last(name)
                    if gap_days >= remind:
                        reason = f"{gap_days}d since last — don't let this habit drift"
                if not reason:
                    reason = f"Quick {float(pts):.1f} pts — fast way to close the gap"
            entry: dict[str, Any] = {
                "action": "log",
                "label": name,
                "amount": "×1",
                "points": float(pts),
                "efficiency": float(pts),
                "effort": 1,
                "reason": reason,
                "history_score": self._history_score(name, recent),
            }
            out.append(entry)
            # Track for combo detection
            logged_combo_root[name] = None

        # ── Recovery rows ──
        week = get_current_week()
        recovery = self._metrics.get_recovery_rows(week, "WEEK")
        for row in recovery.get("rows", []):  # all rows, no cap
            cat = str(row.get("category", ""))
            if not self._rules.should_suggest(cat):
                continue
            amt = str(row.get("hours_needed", ""))
            if amt.startswith("×"):
                if cat in logged_today and self._rules.is_once_per_day(cat):
                    continue
                p = self._positives.get(cat, 0)
                if p > 0:
                    reason = self._history_reason_for_label(cat, recent) or "Recovery"
                    out.append({
                        "action": "log",
                        "label": cat,
                        "amount": amt,
                        "points": float(p),
                        "efficiency": float(p),
                        "effort": 1,
                        "reason": reason,
                        "history_score": self._history_score(cat, recent),
                    })
                    logged_combo_root.setdefault(cat)
            else:
                rate = float(row.get("rate", 0) or 0)
                if rate <= 0:
                    continue
                hours = min(gap / rate, 2.0)
                hours = max(hours, 0.25)
                h = int(hours)
                m = int((hours - h) * 60)
                amount = f"{h}h" if h >= 1 else f"{m}m"
                pts = round(hours * rate, 1)
                reason = self._history_reason_for_label(cat, recent) or "High recovery rate"
                out.append({
                    "action": "track",
                    "label": cat,
                    "amount": amount,
                    "points": pts,
                    "efficiency": rate,
                    "effort": hours,
                    "reason": reason,
                    "history_score": self._history_score(cat, recent),
                })
                logged_combo_root.setdefault(cat)

        # ── Combo pair injection ──
        added_combo: set[str] = set()
        for entry in out:
            label = str(entry["label"])
            if label in added_combo:
                continue
            for pair_name in self._rules.get_combo_pairs(label):
                if pair_name in added_combo:
                    continue
                if pair_name in logged_today:
                    continue
                p = self._positives.get(pair_name, 0)
                if p <= 0:
                    continue
                if not self._rules.should_suggest(pair_name):
                    continue
                boost = self._rules.get_combo_boost(label)
                reason = (
                    f"Pairs well with {label}"
                    + (f" ({boost:+.1f} combo bonus)" if boost else "")
                )
                hist = self._history_score(pair_name, recent) + (boost * 10)
                out.append({
                    "action": "log",
                    "label": pair_name,
                    "amount": "×1",
                    "points": float(p) + boost,
                    "efficiency": float(p) + boost,
                    "effort": 1,
                    "reason": reason,
                    "history_score": hist,
                })
                added_combo.add(pair_name)

        # ── Projects (tracked work) ──
        projs = self._cache.get_day_projects(today_str) or {}
        for name, rate in sorted(
            [(n, r) for n, r in self._points.items() if r and float(r) > 0],
            key=lambda x: -float(x[1]),
        ):
            if not self._rules.should_suggest(name):
                continue
            already = projs.get(name, 0)
            if already >= 0.25:
                continue
            hours = min(gap / float(rate), 1.5)
            hours = max(hours, 0.25)
            h = int(hours)
            m = int((hours - h) * 60)
            amount = f"{h}h" if h >= 1 else f"{m}m"
            pts = round(hours * float(rate), 1)
            reason = self._history_reason_for_label(name, recent)
            if not reason and recent.yesterday and recent.yesterday.net < 0:
                reason = "Yesterday slipped — front-load tracked work to recover momentum"
            out.append({
                "action": "track",
                "label": name,
                "amount": amount,
                "points": pts,
                "efficiency": float(rate),
                "effort": hours,
                "reason": reason or "Not tracked yet today",
                "history_score": self._history_score(name, recent),
            })

        return out

    # ────────────────────────────────────────
    # Stretch step (on-track days)
    # ────────────────────────────────────────

    def _stretch_step(
        self, today_str: str, logged_today: set[str], recent: RecentContext
    ) -> PlaybookStep | None:
        best_name = None
        best_pts = 0.0
        for name, pts in self._positives.items():
            if not self._rules.should_suggest(name):
                continue
            if float(pts) <= best_pts:
                continue
            if name in logged_today and self._rules.is_once_per_day(name):
                continue
            best_pts = float(pts)
            best_name = name
        if best_name:
            reason = self._history_reason_for_label(best_name, recent) or (
                f"Bank {best_pts:.1f} extra points while you're ahead"
            )
            return PlaybookStep(
                action="log",
                label=best_name,
                amount="×1",
                points=best_pts,
                reason=reason,
            )
        for name, rate in sorted(
            self._points.items(), key=lambda x: -float(x[1] or 0)
        ):
            if rate and float(rate) > 0 and self._rules.should_suggest(name):
                return PlaybookStep(
                    action="track",
                    label=name,
                    amount="30m",
                    points=round(0.5 * float(rate), 1),
                    reason="Stretch — top-rate project, easy way to pad the day",
                )
        return None

    @staticmethod
    def _fmt_pts(value: float) -> str:
        if value >= 0:
            return f"+{value:.1f}"
        return f"{value:.1f}"
