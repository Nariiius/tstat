"""Service layer — business logic composed from data sources."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from toggl.cache import DataCache, get_week_dates, get_current_week, get_week_str
from toggl.calc import calculate
from toggl.config import get_daily_target as _get_daily_target


class MetricsService:
    """Business logic layer above DataCache.

    Composes DataCache query results into higher-level metrics.
    No memoization needed — DataCache handles its own caching.
    """

    def __init__(
        self,
        cache: DataCache,
        get_daily_target=_get_daily_target,
    ):
        self._cache = cache
        self._get_daily_target = get_daily_target
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

    def get_graph_data(
        self, daily_data: list[dict[str, Any]], mode: str
    ) -> tuple[list[str], list[float], list[float], float | None]:
        dates = [d["date"] for d in daily_data]
        raw_values = [float(d[mode]) for d in daily_data]

        if mode == "net":
            values: list[float] = []
            cum = 0.0
            for v in raw_values:
                cum += v
                values.append(round(cum, 1))
            avg = round(sum(values) / len(values), 1) if values else None
        elif mode == "negative":
            values = [-v for v in raw_values]
            nonzero = [v for v in raw_values if v != 0]
            avg = round(-sum(nonzero) / len(nonzero), 1) if nonzero else None
        else:
            values = raw_values
            nonzero = [v for v in raw_values if v != 0]
            avg = round(sum(nonzero) / len(nonzero), 1) if nonzero else None

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
                if day["has_activity"]:
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
                if day["has_activity"]:
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
                    "has_data": day["has_activity"],
                    "contains_today": d == date.today(),
                })

        aggregated.reverse()
        return aggregated

    def compute_period_nets(
        self, start: date, end: date, mode: str
    ) -> dict[str, Any]:
        def _compute_net(start_d: date, end_d: date) -> float:
            total = 0.0
            for d in self._cache.get_daily_data_for_range(start_d, end_d):
                if d["has_data"]:
                    total += d["net"]
            return total

        if mode == "day":
            daily_net = _compute_net(start, start)
            monday = start - timedelta(days=start.weekday())
            sunday = monday + timedelta(days=6)
            weekly_net = _compute_net(monday, sunday)
            return {
                "daily_net": daily_net,
                "weekly_net": weekly_net,
            }
        elif mode == "week":
            weekly_net = _compute_net(start, end)
            first_day = date(start.year, start.month, 1)
            next_month = first_day.replace(day=28) + timedelta(days=4)
            last_day = next_month - timedelta(days=next_month.day)
            monthly_net = _compute_net(first_day, last_day)
            return {
                "weekly_net": weekly_net,
                "monthly_net": monthly_net,
            }
        return {}
