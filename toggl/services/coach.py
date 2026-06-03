"""Coach — behavioral findings grounded in your recent days."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from toggl.cache import DataCache, get_week_str
from toggl.category import CategoryRegistry
from toggl.services.metrics import MetricsService
from toggl.services.recent_context import (
    RecentContext,
    build_recent_context,
    format_day_net,
)

COACH_MIN_DAYS_WITH = 8
COACH_MIN_DAYS_WITHOUT = 8
COACH_MIN_EFFECT_PTS = 4.0
COACH_MIN_TOP_DAYS = 8
COACH_MIN_WEEKS = 6
COACH_MIN_PROJECT_HOURS = 8.0
COACH_MIN_FOLLOW_RATE = 0.55
COACH_MIN_FOLLOW_INSTANCES = 6
COACH_MAX_FINDINGS = 4

BANNED_ANALYZERS = frozenset({"current_state", "top_project", "trend"})


@dataclass
class CoachFinding:
    analyzer: str
    text: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CoachReport:
    findings: list[CoachFinding] = field(default_factory=list)


class CoachService:
    def __init__(
        self,
        metrics: MetricsService,
        cache: DataCache,
        points: dict[str, int | float],
        positives: dict[str, int | float],
        category_registry: CategoryRegistry,
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._points = points
        self._positives = positives
        self._categories = category_registry

    def compute(self) -> CoachReport:
        daily = self._active_daily_history()
        recent = build_recent_context(self._metrics, self._cache, lookback_days=14)
        if len(daily) < 4 and not recent.days:
            return CoachReport()

        candidates: list[CoachFinding] = []
        for fn in (
            self._recent_mistake_streak,
            self._recent_best_day_recipe,
            self._yesterday_hangover,
            self._habit_lift_positive_days,
            self._drain_aftermath,
            self._underused_winning_habit,
        ):
            finding = fn(daily, recent)
            if finding and finding.analyzer not in BANNED_ANALYZERS:
                candidates.append(finding)

        candidates.sort(key=lambda f: (-f.confidence, f.analyzer))
        return CoachReport(findings=candidates[:COACH_MAX_FINDINGS])

    def _active_daily_history(self) -> list[dict[str, Any]]:
        today = date.today()
        start = today - timedelta(days=365)
        return [
            d for d in self._metrics.get_daily_data_for_range(start, today)
            if d.get("has_data")
        ]

    def _recent_mistake_streak(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        repeat = [(n, c) for n, c in recent.neg_counts_7d.items() if c >= 2]
        if not repeat:
            return None
        repeat.sort(key=lambda x: -x[1])
        name, count = repeat[0]
        bad_with = [
            s for s in recent.days if name in s.negatives and s.net < 0
        ]
        example = bad_with[-1] if bad_with else None
        extra = ""
        if example:
            extra = f" e.g. {example.label} ended at {format_day_net(example.net)}"
        text = (
            f"[#ff5f5f]{name}[/] logged {count}× in the last 7 days — "
            f"often on negative days.{extra} Cut it today."
        )
        return CoachFinding(
            analyzer="recent_mistake_streak",
            text=text,
            confidence=min(0.95, 0.5 + count * 0.1),
            evidence={"name": name, "count": count},
        )

    def _recent_best_day_recipe(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        if not recent.best_recent:
            return None
        b = recent.best_recent
        if b.net < 5:
            return None
        drivers: list[str] = []
        if b.positives:
            drivers.append(", ".join(b.positives))
        if b.top_project and b.top_project_hours >= 0.5:
            drivers.append(f"{b.top_project} {b.top_project_hours:.1f}h")
        if not drivers:
            return None
        text = (
            f"Best recent day: {b.label} at {format_day_net(b.net)} — "
            f"you had {' + '.join(drivers)}. Repeat that combo this week."
        )
        return CoachFinding(
            analyzer="recent_best_day_recipe",
            text=text,
            confidence=min(0.9, b.net / 20),
            evidence={"date": b.date_str, "net": b.net},
        )

    def _yesterday_hangover(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        if not recent.yesterday:
            return None
        y = recent.yesterday
        drain_projects = [n for n, r in self._points.items() if r is not None and r < 0]
        drain_h = 0.0
        if y.top_project in drain_projects:
            drain_h = y.top_project_hours
        elif y.top_project:
            projs = self._cache.daily_data.get(y.date_str, {}) or {}
            drain_h = sum(projs.get(p, 0) for p in drain_projects)

        parts = [f"Yesterday ({y.label}): {format_day_net(y.net)}"]
        if y.negatives:
            parts.append(f"after logging {', '.join(y.negatives)}")
        if drain_h >= 1.5:
            parts.append(f"with {drain_h:.1f}h on drain projects")
        if y.net >= 0 and not y.negatives and drain_h < 1:
            return None
        text = ". ".join(parts) + ". Name what slipped before today repeats."
        return CoachFinding(
            analyzer="yesterday_hangover",
            text=text,
            confidence=0.88,
            evidence={"net": y.net},
        )

    def _habit_lift_positive_days(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        best: CoachFinding | None = None
        for name, lift in sorted(recent.positive_lift.items(), key=lambda x: -x[1]):
            if lift < COACH_MIN_EFFECT_PTS:
                continue
            n_with = sum(1 for s in recent.days if name in s.positives)
            if n_with < 2:
                continue
            text = (
                f"Days with {name} in the last week average {lift:+.1f} pts higher "
                f"({n_with} days with it). Prioritize logging it early today."
            )
            finding = CoachFinding(
                analyzer="habit_lift_positive_days",
                text=text,
                confidence=min(0.85, lift / 12),
                evidence={"name": name, "lift": lift},
            )
            if best is None or finding.confidence > best.confidence:
                best = finding
        if best:
            return best

        for name in self._positives:
            with_pts, without_pts, n_with, n_without = self._split_days_by_habit(daily, name)
            if n_with < COACH_MIN_DAYS_WITH or n_without < COACH_MIN_DAYS_WITHOUT:
                continue
            delta = sum(with_pts) / n_with - sum(without_pts) / n_without
            if delta < COACH_MIN_EFFECT_PTS:
                continue
            text = (
                f"Historically, {name} days average {delta:+.1f} more pts "
                f"({n_with} vs {n_without} days)."
            )
            return CoachFinding(
                analyzer="habit_lift_positive_days",
                text=text,
                confidence=min(0.75, delta / 15),
                evidence={"name": name, "delta": delta},
            )
        return None

    def _drain_aftermath(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        drain_projects = [n for n, r in self._points.items() if r is not None and r < 0]
        if not drain_projects:
            return None

        by_date = {d["date"]: d for d in daily}
        dates_sorted = sorted(by_date.keys())[-30:]
        heavy_then_bad = 0
        heavy_total = 0
        last_example = ""
        for i, d_str in enumerate(dates_sorted[:-1]):
            projs = self._cache.daily_data.get(d_str, {}) or {}
            heavy = sum(projs.get(p, 0) for p in drain_projects)
            if heavy < 1.5:
                continue
            heavy_total += 1
            next_d = dates_sorted[i + 1]
            next_day = by_date.get(next_d)
            if not next_day:
                continue
            avg_net = sum(d["net"] for d in daily) / len(daily)
            if next_day["net"] < avg_net - 3:
                heavy_then_bad += 1
                try:
                    last_example = (
                        f"{date.fromisoformat(d_str).strftime('%a')} heavy drain → "
                        f"{date.fromisoformat(next_d).strftime('%a')} {format_day_net(next_day['net'])}"
                    )
                except ValueError:
                    pass

        if heavy_total < COACH_MIN_FOLLOW_INSTANCES:
            return None
        rate = heavy_then_bad / heavy_total
        if rate < COACH_MIN_FOLLOW_RATE:
            return None
        tail = f" Latest: {last_example}." if last_example else ""
        text = (
            f"After drain-heavy days, next day is weak {rate:.0%} of the time "
            f"({heavy_then_bad}/{heavy_total}).{tail}"
        )
        return CoachFinding(
            analyzer="drain_aftermath",
            text=text,
            confidence=min(0.85, rate),
            evidence={"rate": rate, "n": heavy_total},
        )

    def _underused_winning_habit(
        self, daily: list[dict[str, Any]], recent: RecentContext
    ) -> CoachFinding | None:
        if not recent.best_recent or not recent.best_recent.positives:
            return None
        win_habit = recent.best_recent.positives[0]
        if win_habit not in self._positives:
            return None
        if any(win_habit in s.positives for s in recent.days[-3:]):
            return None
        text = (
            f"{win_habit} was on your best day ({recent.best_recent.label}, "
            f"{format_day_net(recent.best_recent.net)}) but missing the last 3 days. "
            f"Log it today — it correlates with wins."
        )
        return CoachFinding(
            analyzer="underused_winning_habit",
            text=text,
            confidence=0.82,
            evidence={"habit": win_habit},
        )

    def _split_days_by_habit(
        self, daily: list[dict[str, Any]], habit_name: str
    ) -> tuple[list[float], list[float], int, int]:
        with_pts: list[float] = []
        without_pts: list[float] = []
        for d in daily:
            d_str = d["date"]
            has = any(
                e["name"] == habit_name
                for e in self._cache.positives_raw.get(d_str, [])
            )
            if has:
                with_pts.append(d["net"])
            else:
                without_pts.append(d["net"])
        return with_pts, without_pts, len(with_pts), len(without_pts)
