"""Playbook engine — concrete daily/weekly action plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from toggl.cache import DataCache, get_current_week, get_week_dates
from toggl.const import ONCE_PER_DAY_POSITIVES
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
    done_today: list[str] = field(default_factory=list)
    gap_note: str = ""
    lookback: list[str] = field(default_factory=list)
    focus_line: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""


class PlaybookService:
    """Builds actionable playbooks from metrics + config."""

    def __init__(
        self,
        metrics: MetricsService,
        cache: DataCache,
        points: dict[str, int | float],
        positives: dict[str, int | float],
        playbook_ignore: list[str],
        get_daily_target: Callable[[], float],
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._points = points
        self._positives = positives
        self._ignore = set(playbook_ignore)
        self._get_daily_target = get_daily_target

    def compute(self) -> Playbook:
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
                        label="any project or positive",
                        amount="×1",
                        points=0.0,
                        reason="No activity data yet",
                    )
                ],
                generated_at=generated_at,
            )

        recent = build_recent_context(self._metrics, self._cache, lookback_days=14)
        lookback, focus_line = self._build_lookback(recent, today)

        day = self._metrics.get_day_metrics(today_str)
        today_net = day["net"]
        target = float(self._get_daily_target())
        gap = round(target - today_net, 1)
        logged_today = self._positives_logged_today(today_str)
        done_once = [n for n in logged_today if n in ONCE_PER_DAY_POSITIVES]

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
                gap, today_str, logged_today, recent, max_steps=4
            )
            headline = f"Need {self._fmt_pts(gap)} today (at {self._fmt_pts(today_net)})"
            return Playbook(
                goal="hit_today_target",
                headline=headline,
                steps=steps,
                done_today=done_once,
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
            headline = (
                f"Week {self._fmt_pts(summary.get('actual', 0))} "
                f"({self._fmt_pts(week_delta)} vs pace) — ~{per_day}/day for {days_left}d"
            )
            context["per_day_needed"] = per_day
            return Playbook(
                goal="fix_week",
                headline=headline,
                steps=steps,
                done_today=done_once,
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
            done_today=done_once,
            lookback=lookback,
            focus_line=focus_line,
            context=context,
            generated_at=generated_at,
        )

    def _build_lookback(self, recent: RecentContext, today: date) -> tuple[list[str], str]:
        lines: list[str] = []
        focus = ""

        if recent.yesterday:
            y = recent.yesterday
            lines.append(
                f"[#8d98a7]Yesterday ({y.label}):[/] net {format_day_net(y.net)}"
            )
            tags: list[str] = []
            if y.negatives:
                tags.append(f"[#ff5f5f]{', '.join(y.negatives)}[/]")
            if y.positives:
                tags.append(f"[#37d994]{', '.join(y.positives)}[/]")
            if tags:
                lines.append(f"  {' · '.join(tags)}")
            if y.top_project and y.top_project_hours >= 0.5:
                lines.append(f"  {y.top_project} {y.top_project_hours:.1f}h")

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

        repeat_negs = [
            (n, c) for n, c in recent.neg_counts_7d.items() if c >= 2
        ]
        if repeat_negs:
            repeat_negs.sort(key=lambda x: -x[1])
            n, c = repeat_negs[0]
            lines.append(
                f"[#ff5f5f]Mistake pattern:[/] {n} logged {c}× in the last 7 days"
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
                f"front-load one high-value log before distractions."
            )

        return lines[:4], focus

    def _has_any_data(self) -> bool:
        return bool(
            self._cache.daily_data
            or self._cache.negatives_raw
            or self._cache.positives_raw
        )

    def _positives_logged_today(self, today_str: str) -> set[str]:
        names: set[str] = set()
        for entry in self._cache.positives_raw.get(today_str, []):
            names.add(entry["name"])
        return names

    def _days_left_in_week(self, today: date, week: str) -> int:
        _, end = get_week_dates(week)
        if today > end:
            return 0
        return (end - today).days + 1

    def _build_steps_for_gap(
        self,
        gap: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
        max_steps: int = 4,
    ) -> tuple[list[PlaybookStep], str]:
        candidates = self._gather_candidates(gap, today_str, logged_today, recent)
        candidates.sort(
            key=lambda c: (
                -c.get("history_score", 0),
                -c["efficiency"],
                c["effort"],
            )
        )
        steps: list[PlaybookStep] = []
        covered = 0.0
        used_labels: set[str] = set()

        for c in candidates:
            if len(steps) >= max_steps:
                break
            if c["label"] in used_labels:
                continue
            pts = c["points"]
            if pts <= 0:
                continue
            steps.append(
                PlaybookStep(
                    action=c["action"],
                    label=c["label"],
                    amount=c["amount"],
                    points=pts,
                    reason=c.get("reason", ""),
                )
            )
            used_labels.add(c["label"])
            covered += pts
            if covered >= gap * 0.95:
                break

        gap_note = ""
        if steps and covered < gap * 0.8:
            short = round(gap - covered, 1)
            gap_note = (
                f"{self._fmt_pts(covered)} of {self._fmt_pts(gap)} from steps "
                f"— still need {self._fmt_pts(short)}"
            )
        elif steps:
            gap_note = f"Steps total {self._fmt_pts(covered)} toward {self._fmt_pts(gap)}"

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
        for row in rows[:3]:
            cat = row.get("category", "")
            if cat in self._ignore:
                continue
            amt = str(row.get("hours_needed", ""))
            if amt.startswith("×"):
                if cat in logged_today:
                    continue
                if cat in ONCE_PER_DAY_POSITIVES and cat in logged_today:
                    continue
                pts = self._positives.get(cat, 0)
                if pts <= 0:
                    continue
                reason = self._history_reason_for_label(cat, recent) or "Closes week deficit"
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
                rate = row.get("rate", 0)
                if not rate:
                    continue
                hours = max(per_day / rate, 0.25)
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
                        reason=f"~{per_day:.1f} pts/day pace",
                    )
                )
        gap_note = f"Aim for ~{per_day:.1f} net per day remaining this week"
        return steps[:5], gap_note

    def _history_reason_for_label(self, label: str, recent: RecentContext) -> str:
        if recent.best_recent and label in recent.best_recent.positives:
            b = recent.best_recent
            return f"On {b.label} ({format_day_net(b.net)}) this helped"
        lift = recent.positive_lift.get(label)
        if lift is not None and lift >= 3:
            return f"Your last 7d average +{lift:.0f} pts higher on days you log this"
        if label in recent.neg_counts_7d and recent.neg_counts_7d[label] >= 2:
            return "Break the recent mistake streak"
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
        return score

    def _gather_candidates(
        self,
        gap: float,
        today_str: str,
        logged_today: set[str],
        recent: RecentContext,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        for name, pts in sorted(
            self._positives.items(), key=lambda x: -float(x[1])
        ):
            if name in self._ignore or pts <= 0:
                continue
            if name in logged_today:
                continue
            if name in ONCE_PER_DAY_POSITIVES and name in logged_today:
                continue
            reason = self._history_reason_for_label(name, recent) or "Fast points"
            out.append({
                "action": "log",
                "label": name,
                "amount": "×1",
                "points": float(pts),
                "efficiency": float(pts),
                "effort": 1,
                "reason": reason,
                "history_score": self._history_score(name, recent),
            })

        week = get_current_week()
        recovery = self._metrics.get_recovery_rows(week, "WEEK")
        for row in recovery.get("rows", [])[:5]:
            cat = row.get("category", "")
            if cat in self._ignore:
                continue
            amt = str(row.get("hours_needed", ""))
            if amt.startswith("×"):
                if cat in logged_today:
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
                reason = self._history_reason_for_label(cat, recent) or "High rate"
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

        projs = self._cache.get_day_projects(today_str) or {}
        for name, rate in sorted(
            [(n, r) for n, r in self._points.items() if r and r > 0],
            key=lambda x: -x[1],
        ):
            if name in self._ignore:
                continue
            already = projs.get(name, 0)
            if already >= 0.25:
                continue
            hours = min(gap / rate, 1.5)
            hours = max(hours, 0.25)
            h = int(hours)
            m = int((hours - h) * 60)
            amount = f"{h}h" if h >= 1 else f"{m}m"
            pts = round(hours * rate, 1)
            reason = self._history_reason_for_label(name, recent)
            if not reason and recent.yesterday and recent.yesterday.net < 0:
                reason = "Yesterday slipped — start with tracked work"
            out.append({
                "action": "track",
                "label": name,
                "amount": amount,
                "points": pts,
                "efficiency": rate,
                "effort": hours,
                "reason": reason or "Not tracked today",
                "history_score": self._history_score(name, recent),
            })

        return out

    def _stretch_step(
        self, today_str: str, logged_today: set[str], recent: RecentContext
    ) -> PlaybookStep | None:
        best_name = None
        best_pts = 0.0
        for name, pts in self._positives.items():
            if name in self._ignore or pts <= best_pts:
                continue
            if name in logged_today:
                continue
            if name in ONCE_PER_DAY_POSITIVES and name in logged_today:
                continue
            best_pts = float(pts)
            best_name = name
        if best_name:
            reason = self._history_reason_for_label(best_name, recent) or "Bank extra points"
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
            if rate and rate > 0 and name not in self._ignore:
                return PlaybookStep(
                    action="track",
                    label=name,
                    amount="30m",
                    points=round(0.5 * rate, 1),
                    reason="Stretch — top-rate project",
                )
        return None

    @staticmethod
    def _fmt_pts(value: float) -> str:
        if value >= 0:
            return f"+{value:.1f}"
        return f"{value:.1f}"
