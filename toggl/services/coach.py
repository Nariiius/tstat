"""Coach — statistically-gated behavioural findings from all-time data.

Produces exactly 3 high-signal cards:
  1. Biggest positive driver (lift + prevalence in top days)
  2. Biggest negative driver (presence on bad days vs good days)
  3. Largest gap from best period (activity whose frequency has dropped)

Every finding requires ≥10 data points and a meaningful effect size.
No recent-day commentary — only system-level patterns that survive statistical gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from toggl.activity_rules import ActivityRules
from toggl.cache import DataCache
from toggl.category import CategoryRegistry
from toggl.services.metrics import MetricsService

MIN_SAMPLES = 10          # absolute floor for any finding
MIN_LIFT_PTS = 5.0        # minimum avg net difference to be worth reporting
TOP_N = 20                 # how many best/worst days to analyze for prevalence


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
        activity_rules: ActivityRules,
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._points = points
        self._positives = positives
        self._categories = category_registry
        self._rules = activity_rules

    def compute(self) -> CoachReport:
        daily = self._active_daily_history()
        if len(daily) < 4:
            return CoachReport()

        findings: list[CoachFinding] = []

        f = self._biggest_positive_driver(daily)
        if f:
            findings.append(f)

        f = self._biggest_negative_driver(daily)
        if f:
            findings.append(f)

        f = self._largest_gap(daily)
        if f:
            findings.append(f)

        return CoachReport(findings=findings)

    # ────────────────────────────────────────
    # Data helpers
    # ────────────────────────────────────────

    def _active_daily_history(self) -> list[dict[str, Any]]:
        today = date.today()
        start = today - timedelta(days=365)
        return [
            d for d in self._metrics.get_daily_data_for_range(start, today)
            if d.get("has_data")
        ]

    def _split_days_by_habit(
        self, daily: list[dict[str, Any]], habit_name: str
    ) -> tuple[list[float], list[float]]:
        """Return (nets_with_habit, nets_without_habit) for *habit_name* across *daily*."""
        with_pts: list[float] = []
        without_pts: list[float] = []
        for d in daily:
            has = any(
                e["name"] == habit_name
                for e in self._cache.positives_raw.get(d["date"], [])
            )
            if has:
                with_pts.append(d["net"])
            else:
                without_pts.append(d["net"])
        return with_pts, without_pts

    # ────────────────────────────────────────
    # Card 1 — biggest positive driver
    # ────────────────────────────────────────

    def _biggest_positive_driver(
        self, daily: list[dict[str, Any]]
    ) -> CoachFinding | None:
        """Habit whose presence most strongly predicts high-net days."""

        best_lift = -999.0
        best_info: tuple | None = None

        for name in self._positives:
            mode = self._rules.get_coach_mode(name)
            if mode == "observe_only":
                continue
            with_pts, without_pts = self._split_days_by_habit(daily, name)
            n_with = len(with_pts)
            if n_with < MIN_SAMPLES:
                continue
            avg_with = sum(with_pts) / n_with
            avg_without = sum(without_pts) / max(len(without_pts), 1)
            lift = avg_with - avg_without
            if lift < MIN_LIFT_PTS:
                continue

            # Prevalence in the best TOP_N days
            top_days = sorted(daily, key=lambda d: d["net"], reverse=True)[:TOP_N]
            top_with = sum(
                1 for d in top_days
                if any(e["name"] == name
                       for e in self._cache.positives_raw.get(d["date"], []))
            )
            top_pct = round(top_with / len(top_days) * 100)

            if lift > best_lift:
                best_lift = lift
                best_info = (name, lift, avg_with, avg_without, n_with, top_pct)

        if best_info is None:
            return None
        name, lift, avg_with, avg_without, n_with, top_pct = best_info

        text = (
            f"[bold]#1 BIGGEST POSITIVE DRIVER[/]\n"
            f"  {name} — days average [bold]{avg_with:+.1f}[/] pts "
            f"vs {avg_without:+.1f} without\n"
            f"  Across {n_with} days. "
            f"Found in {top_pct}% of your best {TOP_N} days."
        )
        return CoachFinding(
            analyzer="biggest_positive_driver",
            text=text,
            confidence=min(0.95, max(0.50, lift / 20)),
            evidence={"name": name, "lift": lift, "n_with": n_with},
        )

    # ────────────────────────────────────────
    # Card 2 — biggest negative driver
    # ────────────────────────────────────────

    def _biggest_negative_driver(
        self, daily: list[dict[str, Any]]
    ) -> CoachFinding | None:
        """Drain activity most strongly associated with negative-net days."""

        # Collect negative names from dates in the daily range
        daily_dates = {d["date"] for d in daily}
        all_negatives: set[str] = set()
        for d_str, entries in self._cache.negatives_raw.items():
            if d_str not in daily_dates:
                continue
            for e in entries:
                all_negatives.add(e["name"])

        # Count negative-net days and per-activity frequencies
        bad_days = [d for d in daily if d["net"] < 0]
        good_days = [d for d in daily if d["net"] >= 0]
        n_bad = len(bad_days)
        if n_bad < MIN_SAMPLES:
            return None

        best_ratio = 0.0
        best_name = ""
        best_total = 0
        best_good_pct = 0

        for name in all_negatives:
            bad_with = sum(
                1 for d in bad_days
                if any(e["name"] == name
                       for e in self._cache.negatives_raw.get(d["date"], []))
            )
            total_occurrences = sum(
                1 for d_str in daily_dates
                for e in self._cache.negatives_raw.get(d_str, [])
                if e["name"] == name
            )
            if total_occurrences < MIN_SAMPLES:
                continue
            ratio = bad_with / n_bad

            good_with = sum(
                1 for d in good_days
                if any(e["name"] == name
                       for e in self._cache.negatives_raw.get(d["date"], []))
            )
            good_pct = round(good_with / max(len(good_days), 1) * 100)

            if ratio > best_ratio:
                best_ratio = ratio
                best_name = name
                best_total = total_occurrences
                best_good_pct = good_pct

        if not best_name or best_ratio < 0.30:
            return None

        text = (
            f"[bold]#2 BIGGEST NEGATIVE DRIVER[/]\n"
            f"  {best_name} — present on {best_ratio:.0%} of negative days "
            f"vs {best_good_pct}% of positive days\n"
            f"  {best_total} occurrences total. "
            f"Breaking this pattern gives you the largest expected turnaround."
        )
        return CoachFinding(
            analyzer="biggest_negative_driver",
            text=text,
            confidence=min(0.95, best_ratio + 0.15),
            evidence={"name": best_name, "bad_pct": best_ratio, "n": best_total},
        )

    # ────────────────────────────────────────
    # Card 3 — largest gap from best period
    # ────────────────────────────────────────

    def _largest_gap(
        self, daily: list[dict[str, Any]]
    ) -> CoachFinding | None:
        """Activity whose current frequency has dropped most vs its best period."""

        today = date.today()
        current_month = today.strftime("%Y-%m")

        largest_gap = -999.0
        best_info: tuple | None = None

        for name in self._positives:
            # Build per-month counts from all-time positive data
            monthly: dict[str, int] = {}       # YYYY-MM → days logged
            month_total_days: dict[str, int] = {}  # YYYY-MM → total days with data
            known_dates = {d["date"] for d in daily}

            for d_str, entries in self._cache.positives_raw.items():
                if d_str not in known_dates:
                    continue
                month_key = d_str[:7]
                if any(e["name"] == name for e in entries):
                    monthly[month_key] = monthly.get(month_key, 0) + 1
                month_total_days[month_key] = month_total_days.get(month_key, 0) + 1

            total_points = sum(monthly.values())
            if total_points < MIN_SAMPLES:
                continue
            if len(monthly) < 2:
                continue

            # Best month frequency
            best_month = ""
            best_freq = 0.0
            for m, count in monthly.items():
                total = month_total_days.get(m, count)
                freq = count / max(total, 1)
                if freq > best_freq:
                    best_freq = freq
                    best_month = m

            # Current month frequency
            curr_count = monthly.get(current_month, 0)
            curr_total = month_total_days.get(current_month, curr_count)
            curr_freq = curr_count / max(curr_total, 1)

            # Must have a meaningful current-month sample
            if curr_total < 4:
                continue

            gap = best_freq - curr_freq
            if gap > largest_gap and gap > 0.10:
                largest_gap = gap
                best_info = (name, best_month, best_freq, curr_freq, total_points)

        if best_info is None:
            return None
        name, best_month, best_freq, curr_freq, n_total = best_info

        text = (
            f"[bold]#3 LARGEST GAP[/]\n"
            f"  {name} — best period {best_month} at {best_freq:.0%} "
            f"→ current month {curr_freq:.0%}\n"
            f"  {n_total} data points over {len(monthly)} months. "
            f"This is the biggest drop-off worth recovering."
        )
        return CoachFinding(
            analyzer="largest_gap",
            text=text,
            confidence=min(0.90, 0.40 + gap),
            evidence={"name": name, "best_month": best_month, "gap": gap},
        )
