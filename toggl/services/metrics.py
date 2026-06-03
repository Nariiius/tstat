"""Service layer — business logic composed from data sources."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Callable

from toggl.cache import DataCache, get_week_dates, get_current_week, get_week_str, get_sunday_of_week
from toggl.calc import calculate, calculate_logged_activity_totals


class MetricsService:
    """Business logic layer above DataCache.

    Composes DataCache query results into higher-level metrics.
    No memoization needed — DataCache handles its own caching.
    """

    def __init__(
        self,
        cache: DataCache,
        points: dict[str, int | float],
        negatives: dict[str, int | float],
        positives: dict[str, int | float],
        recovery_ignore: list[str],
        get_daily_target: Callable[[], float] | None = None,
    ):
        self._cache = cache
        self._points = points
        self._negatives = negatives
        self._positives = positives
        self._recovery_ignore = recovery_ignore
        self._get_daily_target = get_daily_target or (lambda: 13.0)
        self._report_sections_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def get_day_metrics(self, day_str: str) -> dict[str, Any]:
        projects = self._cache.get_day_projects(day_str) or {}
        results = calculate(projects)
        negatives = self._cache.get_negatives_for_context(day_str, "DAY")
        positives = self._cache.get_positives_for_context(day_str, "DAY")
        earned = round(sum(r[3] for r in results if r[3] is not None and r[3] > 0), 1)
        tracked = round(sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0), 1)
        logged = round(sum(abs(r[3]) for r in negatives), 1)
        logged_pos = round(sum(r[3] for r in positives), 1)
        total_hours = round(sum(projects.values()), 1)
        net = round(earned - tracked - logged + logged_pos, 1)
        return {
            "label": day_str,
            "projects": projects,
            "results": results,
            "negative_results": negatives,
            "positive_results": positives,
            "earned": earned,
            "tracked_negative": tracked,
            "logged_negative": logged,
            "logged_positive": logged_pos,
            "total_hours": total_hours,
            "net": net,
            "delta": round(net - self._get_daily_target(), 1),
        }

    def get_week_dashboard_rows(self, label: str) -> dict[str, Any]:
        start_d, end_d = get_week_dates(label)
        rows = []
        cutoff = min(end_d, date.today()) if label == get_current_week() else end_d
        cumulative_net = 0.0
        cumulative_days = 0
        for i in range(7):
            d = start_d + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            metrics = self.get_day_metrics(d_str)
            has_activity = bool(metrics["projects"] or metrics["negative_results"] or metrics["positive_results"])
            if d <= cutoff:
                cumulative_net += metrics["net"]
                cumulative_days += 1
            rows.append({
                "day": d.strftime("%a"),
                "date": d_str,
                "date_short": d.strftime("%d %b"),
                "hours": metrics["total_hours"],
                "earned": metrics["earned"],
                "tracked_negative": metrics["tracked_negative"],
                "logged_positive": metrics["logged_positive"],
                "positive": round(metrics["earned"] + metrics["logged_positive"], 1),
                "positive_total": round(metrics["earned"] + metrics["logged_positive"], 1),
                "logged_negative": metrics["logged_negative"],
                "negative": round(metrics["tracked_negative"] + metrics["logged_negative"], 1),
                "negative_total": round(metrics["tracked_negative"] + metrics["logged_negative"], 1),
                "goal": self._get_daily_target(),
                "delta": metrics["delta"],
                "net": metrics["net"],
                "has_activity": has_activity,
                "is_today": d == date.today(),
            })
        expected = round(self._get_daily_target() * cumulative_days, 1)
        return {
            "rows": rows,
            "summary": {
                "days_counted": cumulative_days,
                "expected": expected,
                "actual": round(cumulative_net, 1),
                "delta": round(cumulative_net - expected, 1),
            },
        }

    def get_report_sections(self, label: str, context_type: str) -> dict[str, Any]:
        key = (label, context_type)
        if key in self._report_sections_cache:
            return self._report_sections_cache[key]

        if context_type == "DAY":
            projects = self._cache.get_day_projects(label) or {}
        elif context_type == "WEEK":
            projects = self._cache.get_week_projects(label) or {}
        else:
            projects = self._cache.get_all_time_projects() or {}
        results = calculate(projects)
        negative_results = self._cache.get_negatives_for_context(label, context_type)
        positive_results = self._cache.get_positives_for_context(label, context_type)
        total_pts = round(
            sum(r[3] for r in results if r[3] is not None) + sum(r[3] for r in negative_results) + sum(r[3] for r in positive_results),
            2,
        )
        result = {
            "results": results,
            "negative_results": negative_results,
            "positive_results": positive_results,
            "positive": [r for r in results if r[3] is not None and r[3] >= 0],
            "negative": [r for r in results if r[3] is not None and r[3] < 0],
            "unscored": [r for r in results if r[3] is None],
            "total_points": total_pts,
            "total_hours": round(sum(r[1] for r in results if r[1] is not None), 2),
        }
        self._report_sections_cache[key] = result
        return result

    def _earliest_data_date(self) -> date | None:
        """First calendar day with any projects, negatives, or positives."""
        dates: list[date] = []
        for d_str in (
            *self._cache.daily_data.keys(),
            *self._cache.negatives_raw.keys(),
            *self._cache.positives_raw.keys(),
        ):
            try:
                dates.append(date.fromisoformat(d_str))
            except ValueError:
                continue
        return min(dates) if dates else None

    def get_lifetime_net(self) -> float:
        """All-time net — matches Overview ``Total … pts`` (weekly project rollup)."""
        return self.get_report_sections("ALL_TIME", "ALL")["total_points"]

    def _daily_net_sum(self, start: date, end: date) -> float:
        """Sum of per-day net values across [start, end] (daily CSV basis)."""
        if start > end:
            return 0.0
        daily = self.get_daily_data_for_range(start, end)
        return round(sum(float(d["net"]) for d in daily), 1)

    def get_net_graph_adjustment(self) -> float:
        """Offset so daily cumulative net at today equals :meth:`get_lifetime_net`."""
        earliest = self._earliest_data_date()
        if earliest is None:
            return 0.0
        daily_through_today = self._daily_net_sum(earliest, date.today())
        return round(self.get_lifetime_net() - daily_through_today, 2)

    def get_cumulative_before(self, before: date, mode: str) -> float:
        """Lifetime total for *mode* through the day before *before*."""
        earliest = self._earliest_data_date()
        if earliest is None or before <= earliest:
            base = 0.0
        else:
            end = before - timedelta(days=1)
            daily = self.get_daily_data_for_range(earliest, end)
            base = sum(float(d[mode]) for d in daily)
        if mode == "net":
            base += self.get_net_graph_adjustment()
        return round(base, 1)

    def get_graph_data(
        self,
        daily_data: list[dict[str, Any]],
        mode: str,
        *,
        baseline: float = 0.0,
    ) -> tuple[list[str], list[float], list[float], float | None]:
        dates = [d["date"] for d in daily_data]
        raw_values = [float(d[mode]) for d in daily_data]

        values: list[float] = []
        cum = baseline
        for v in raw_values:
            cum += v
            if mode == "negative":
                values.append(round(-cum, 1))
            else:
                values.append(round(cum, 1))

        avg = round(sum(raw_values) / len(raw_values), 1) if raw_values else None
        return dates, values, raw_values, avg

    def get_daily_breakdown(
        self, daily_data: list[dict[str, Any]], mode: str
    ) -> list[dict[str, Any]]:
        aggregated: list[dict[str, Any]] = []

        if mode == "week":
            current_group = None
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except Exception:
                    continue
                sunday = d - timedelta(days=(d.weekday() + 1) % 7)
                if current_group is None or current_group["start_date"] != sunday:
                    wk_num = int(get_week_str(sunday).split("W")[1])
                    current_group = {
                        "start_date": sunday,
                        "label": f"Wk {wk_num}",
                        "positive": 0.0,
                        "negative": 0.0,
                        "net": 0.0,
                        "has_data": False,
                        "contains_today": False,
                    }
                    aggregated.append(current_group)
                current_group["positive"] += day["positive"]
                current_group["negative"] += day["negative"]
                current_group["net"] += day["net"]
                if day.get("has_data", day.get("has_activity", False)):
                    current_group["has_data"] = True
                if d == date.today():
                    current_group["contains_today"] = True

        elif mode == "month":
            current_group = None
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except Exception:
                    continue
                month_key = (d.year, d.month)
                if current_group is None or current_group["month_key"] != month_key:
                    current_group = {
                        "month_key": month_key,
                        "label": d.strftime("%b %Y"),
                        "positive": 0.0,
                        "negative": 0.0,
                        "net": 0.0,
                        "has_data": False,
                        "contains_today": False,
                    }
                    aggregated.append(current_group)
                current_group["positive"] += day["positive"]
                current_group["negative"] += day["negative"]
                current_group["net"] += day["net"]
                if day.get("has_data", day.get("has_activity", False)):
                    current_group["has_data"] = True
                if d == date.today():
                    current_group["contains_today"] = True

        else:
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except Exception:
                    continue
                aggregated.append({
                    "label": f"{d.strftime('%a')} {d.strftime('%d %b')}",
                    "positive": day["positive"],
                    "negative": day["negative"],
                    "net": day["net"],
                    "has_data": day.get("has_data", day.get("has_activity", False)),
                    "contains_today": d == date.today(),
                })

        aggregated.reverse()
        return aggregated

    def _fmt_net(self, value: float) -> str:
        if value > 0:
            return f"[#37d994]+{value:.1f}[/]"
        elif value < 0:
            return f"[#ff5f5f]{value:.1f}[/]"
        else:
            return "0.0"

    # ── Ported from DataCache ─────────────────────────────────────────

    def get_daily_data_for_range(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Return daily aggregates for every day in [start_date, end_date].

        Each dict has these fields (all exist for every day in the range;
        no-data and future days get all numeric fields = 0.0):

            date (str):      "YYYY-MM-DD"
            net (float):     earned - abs(tracked_neg) - logged_neg + logged_pos
            positive (float): earned + logged_pos  (always >= 0)
            negative (float): abs(tracked_neg) + logged_neg  (always >= 0)
            logged_pos (float): sum of positive-log points (NOT count)
            logged_neg (float): sum of negative-log points (NOT count)
            has_data (bool): True if projects, negatives, or positives exist
        """
        results = []
        d = start_date
        while d <= end_date:
            d_str = d.strftime("%Y-%m-%d")
            projs = self._cache.daily_data.get(d_str, {})
            neg_entries = self._cache.negatives_raw.get(d_str, [])
            pos_entries = self._cache.positives_raw.get(d_str, [])
            has_data = bool(projs or neg_entries or pos_entries)

            if projs:
                res = calculate(projs)
                earned = sum(r[3] for r in res if r[3] is not None and r[3] > 0)
                tracked_neg = sum(abs(r[3]) for r in res if r[3] is not None and r[3] < 0)
            else:
                earned = 0.0
                tracked_neg = 0.0

            logged_neg = sum(e["points"] for e in neg_entries)
            logged_pos = sum(e["points"] for e in pos_entries)

            net = round(earned - tracked_neg - logged_neg + logged_pos, 1)
            positive = round(earned + logged_pos, 1)
            negative = round(tracked_neg + logged_neg, 1)

            results.append({
                "date": d_str,
                "net": net if has_data else 0.0,
                "positive": positive,
                "negative": negative,
                "earned": round(earned, 1),
                "tracked_neg": round(tracked_neg, 1),
                "logged_pos": round(logged_pos, 1),
                "logged_neg": round(logged_neg, 1),
                "total_hours": round(sum(projs.values()), 1) if projs else 0.0,
                "has_data": has_data,
            })
            d += timedelta(days=1)

        return results

    def get_range_aggregate(
        self, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Aggregate projects and logged activities across a date range.

        Returns (project_results, negative_results, positive_results)
        where each is structured identically to get_report_sections output.
        """
        # Aggregate project hours
        projects: dict[str, float] = {}
        d = start_date
        while d <= end_date:
            d_str = d.strftime("%Y-%m-%d")
            for proj, hrs in self._cache.daily_data.get(d_str, {}).items():
                projects[proj] = projects.get(proj, 0.0) + hrs
            d += timedelta(days=1)

        results = calculate(projects)

        # Aggregate logged negatives
        neg_entries = []
        for d_str, entries in self._cache.negatives_raw.items():
            try:
                dd = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            if start_date <= dd <= end_date:
                neg_entries.extend(entries)
        negative_results = calculate_logged_activity_totals(neg_entries, self._negatives, sign=-1)

        # Aggregate logged positives
        pos_entries = []
        for d_str, entries in self._cache.positives_raw.items():
            try:
                dd = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            if start_date <= dd <= end_date:
                pos_entries.extend(entries)
        positive_results = calculate_logged_activity_totals(pos_entries, self._positives)

        return {
            "results": results,
            "positive": [r for r in results if r[3] is not None and r[3] >= 0],
            "negative": [r for r in results if r[3] is not None and r[3] < 0],
            "unscored": [r for r in results if r[3] is None],
            "positive_results": positive_results,
            "negative_results": negative_results,
        }

    def get_recovery_rows(self, label: str, context_type: str) -> dict[str, Any]:
        report = self.get_report_sections(label, context_type)
        total_pts = report["total_points"]
        if total_pts >= 0:
            return {"total_points": total_pts, "rows": []}
        deficit = abs(total_pts)
        rows = []

        # Tracked projects with positive rates (hourly)
        for name, rate in sorted(
            [(name, rate) for name, rate in self._points.items() if rate > 0],
            key=lambda item: -item[1],
        ):
            hours_needed = deficit / rate
            h = int(hours_needed)
            m = int((hours_needed - h) * 60)
            if h >= 1:
                formatted_amount = f"{round(hours_needed)}h"
            else:
                formatted_amount = f"{m}m"
            rows.append({"category": name, "rate": rate, "hours_needed": formatted_amount})

        # Logged positive actions (one-time bonuses)
        if self._positives:
            for name, points in sorted(
                [(name, v) for name, v in self._positives.items()
                 if v > 0 and name not in self._recovery_ignore],
                key=lambda item: -item[1],
            ):
                occurrences_needed = math.ceil(deficit / points)
                rows.append({
                    "category": name,
                    "rate": points,
                    "hours_needed": f"\u00d7{occurrences_needed}",
                })

        return {"total_points": total_pts, "rows": rows}

    # ── Existing methods ────────────────────────────────────────────

    def compute_period_nets(
        self, start: date, end: date, mode: str
    ) -> dict[str, Any]:
        def _compute_net(start_d: date, end_d: date) -> float:
            total = 0.0
            for d in self.get_daily_data_for_range(start_d, end_d):
                if d["has_data"]:
                    total += d["net"]
            return total

        if mode == "day":
            daily_net = _compute_net(start, start)
            week_sunday = get_sunday_of_week(start)
            week_saturday = week_sunday + timedelta(days=6)
            weekly_net = _compute_net(week_sunday, week_saturday)
            wk = get_week_str(start)
            week_label = f"W{int(wk.split('W')[1])}"
            return {
                "daily_net": daily_net,
                "weekly_net": weekly_net,
                "subtitle": f"Daily: {self._fmt_net(daily_net)}  |  Weekly ({week_label}): {self._fmt_net(weekly_net)}",
            }
        elif mode == "week":
            weekly_net = _compute_net(start, end)
            first_day = date(start.year, start.month, 1)
            next_month = first_day.replace(day=28) + timedelta(days=4)
            last_day = next_month - timedelta(days=next_month.day)
            monthly_net = _compute_net(first_day, last_day)
            month_label = start.strftime("%b")
            return {
                "weekly_net": weekly_net,
                "monthly_net": monthly_net,
                "subtitle": f"Weekly: {self._fmt_net(weekly_net)}  |  Monthly ({month_label}): {self._fmt_net(monthly_net)}",
            }
        return {}
