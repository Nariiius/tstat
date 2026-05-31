"""DataCache — reads all CSVs once per refresh cycle, serves queries from memory."""

import logging
import os
from typing import Any

logger = logging.getLogger("TStat")
import csv
import io
from datetime import datetime, date, timedelta

from toggl.const import (
    CSV_FILE, DAILY_CSV_FILE, NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE,
    HISTORY_FILE,
)
from toggl.config import POINTS, NEGATIVES, POSITIVES, RECOVERY_IGNORE, get_daily_target
from toggl.calc import calculate, calculate_logged_activity_totals


def parse_iso(s: str) -> datetime | None:
    """Parse ISO-8601 datetime string robustly, handling Z suffix and missing timezone."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                return datetime.strptime(s, "%Y-%m-%d")
            except ValueError:
                return None


# ──────────────────────────────────────────────
# DATE & WEEK HELPERS
# ──────────────────────────────────────────────
def get_sunday_of_week(d: date) -> date:
    days_since_sun = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sun)


def _year_first_sunday(year: int) -> date:
    """Sunday on or before Jan 1 of *year*."""
    jan1 = date(year, 1, 1)
    return jan1 - timedelta(days=(jan1.weekday() + 1) % 7)


def get_week_str(d: date) -> str:
    """Return the week label for date *d*.

    Weeks are Sunday-Saturday.  W01 starts on the Sunday on or before Jan 1.
    ``get_week_str`` and ``get_week_dates`` are bijective.
    """
    week_num = (get_sunday_of_week(d) - _year_first_sunday(d.year)).days // 7 + 1
    return f"{d.year}-W{week_num:02d}"


def get_current_week() -> str:
    return get_week_str(date.today())


def get_week_dates(week_str: str) -> tuple[date, date]:
    year, week = week_str.split("-W")
    week_num = int(week)
    start_date = _year_first_sunday(int(year)) + timedelta(weeks=week_num - 1)
    end_date = start_date + timedelta(days=6)
    return start_date, end_date


def get_iso_format(d: date, is_end: bool = False) -> str:
    """Return UTC RFC3339 string for date *d* (Toggl API requires Z suffix)."""
    from datetime import time, timezone

    if is_end:
        dt = datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)
    else:
        dt = datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)
    # RFC3339 with Z suffix — no timezone offset
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────
# LAST-UPDATED HELPERS
# ──────────────────────────────────────────────
import json

# Imported from services.sync for backward compatibility
from toggl.services.sync import _load_history, _save_history, _atomic_write  # noqa: E402, F401


def get_last_updated_str() -> str:
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return "Never"
    dt = parse_iso(ts)
    if dt is None:
        return "Never"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    rem = mins % 60
    return f"{hrs}h {rem}m ago" if rem else f"{hrs}h ago"


def needs_auto_update() -> bool:
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return True
    dt = parse_iso(ts)
    if dt is None:
        return True
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt
    return diff.total_seconds() > 1800


# ──────────────────────────────────────────────
# DATA CACHE
# ──────────────────────────────────────────────
class DataCache:
    """Parses all 4 CSV files into memory once, then serves queries from dicts."""

    def __init__(self) -> None:
        self.weekly_data: dict[str, dict[str, float]] = {}
        self.daily_data: dict[str, dict[str, float]] = {}
        self.negatives_raw: dict[str, list[dict[str, Any]]] = {}
        self.positives_raw: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def load(cls) -> "DataCache":
        cache = cls()
        cache._load_weekly()
        cache._load_daily()
        cache._load_negatives()
        cache._load_positives()
        return cache

    def _load_weekly(self) -> None:
        if not os.path.exists(CSV_FILE):
            return
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    wk = row["Week"]
                    proj = row["Project"]
                    hrs = float(row["Hours"])
                    self.weekly_data.setdefault(wk, {})
                    self.weekly_data[wk][proj] = self.weekly_data[wk].get(proj, 0.0) + hrs
                except (KeyError, ValueError):
                    continue

    def _load_daily(self) -> None:
        if not os.path.exists(DAILY_CSV_FILE):
            return
        with open(DAILY_CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    d = row["Date"]
                    proj = row["Project"]
                    hrs = float(row["Hours"])
                    self.daily_data.setdefault(d, {})
                    self.daily_data[d][proj] = self.daily_data[d].get(proj, 0.0) + hrs
                except (KeyError, ValueError):
                    continue

    def _load_negatives(self) -> None:
        if not os.path.exists(NEGATIVES_CSV_FILE):
            return
        with open(NEGATIVES_CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    d = row["Date"]
                    name = row.get("Negative") or row.get("Penalty") or "Unknown"
                    pts = float(row["Points"])
                    self.negatives_raw.setdefault(d, []).append({"name": name, "points": pts})
                except (KeyError, ValueError):
                    continue

    def _load_positives(self) -> None:
        if not os.path.exists(POSITIVES_CSV_FILE):
            return
        with open(POSITIVES_CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    d = row["Date"]
                    name = row.get("Positive") or row.get("Bonus") or "Unknown"
                    pts = float(row["Points"])
                    self.positives_raw.setdefault(d, []).append({"name": name, "points": pts})
                except (KeyError, ValueError):
                    continue

    # ── Query methods ──

    def get_week_projects(self, week_str: str) -> dict[str, float] | None:
        return dict(self.weekly_data.get(week_str, {})) or None

    def get_day_projects(self, day_str: str) -> dict[str, float] | None:
        return dict(self.daily_data.get(day_str, {})) or None

    def get_all_time_projects(self) -> dict[str, float] | None:
        if not self.weekly_data:
            return None
        projects: dict[str, float] = {}
        for wk_projs in self.weekly_data.values():
            for proj, hrs in wk_projs.items():
                projects[proj] = projects.get(proj, 0.0) + hrs
        return projects

    def get_negatives_for_context(self, label: str, context_type: str) -> list[tuple[str, int, float, float]]:
        """Return logged negatives as (name, count, points_per_event, total_points).

        Filters entries by context (DAY / WEEK / ALL), then delegates aggregation
        to calculate_logged_activity_totals so the UI receives count and total.
        """
        filtered_entries: list[dict] = []
        start_d, end_d = None, None
        if context_type == "WEEK":
            start_d, end_d = get_week_dates(label)
        for d_str, entries in self.negatives_raw.items():
            include = False
            if context_type == "ALL":
                include = True
            elif context_type == "DAY" and d_str == label:
                include = True
            elif context_type == "WEEK" and start_d and end_d:
                try:
                    r_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                    if start_d <= r_date <= end_d:
                        include = True
                except ValueError:
                    pass
            if include:
                filtered_entries.extend(entries)
        return calculate_logged_activity_totals(filtered_entries, NEGATIVES, sign=-1)

    def get_positives_for_context(self, label: str, context_type: str) -> list[tuple[str, int, float, float]]:
        """Return logged positives as (name, count, points_per_event, total_points).

        Filters entries by context (DAY / WEEK / ALL), then delegates aggregation
        to calculate_logged_activity_totals so the UI receives count and total.
        """
        filtered_entries: list[dict] = []
        start_d, end_d = None, None
        if context_type == "WEEK":
            start_d, end_d = get_week_dates(label)
        for d_str, entries in self.positives_raw.items():
            include = False
            if context_type == "ALL":
                include = True
            elif context_type == "DAY" and d_str == label:
                include = True
            elif context_type == "WEEK" and start_d and end_d:
                try:
                    r_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                    if start_d <= r_date <= end_d:
                        include = True
                except ValueError:
                    pass
            if include:
                filtered_entries.extend(entries)
        return calculate_logged_activity_totals(filtered_entries, POSITIVES)

    def get_negative_log_rows(self, limit: int = 30) -> list[dict[str, str | float]]:
        rows = []
        for d_str, entries in self.negatives_raw.items():
            for e in entries:
                rows.append({"date": d_str, "name": e["name"], "points": e["points"]})
        rows.sort(key=lambda item: item["date"], reverse=True)
        return rows[:limit]

    def get_positive_log_rows(self, limit: int = 30) -> list[dict[str, str | float]]:
        rows = []
        for d_str, entries in self.positives_raw.items():
            for e in entries:
                rows.append({"date": d_str, "name": e["name"], "points": e["points"]})
        rows.sort(key=lambda item: item["date"], reverse=True)
        return rows[:limit]

    def get_week_neg_breakdown(self, week_str: str) -> tuple[float, float]:
        tracked = 0.0
        wk_projs = self.weekly_data.get(week_str, {})
        for proj, hrs in wk_projs.items():
            rate = POINTS.get(proj)
            if rate is not None and rate < 0:
                tracked += abs(hrs * rate)
        logged = 0.0
        start_d, end_d = get_week_dates(week_str)
        for d_str, entries in self.negatives_raw.items():
            try:
                r_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                if start_d <= r_date <= end_d:
                    for e in entries:
                        logged += e["points"]
            except ValueError:
                pass
        return round(tracked, 1), round(logged, 1)

    def get_week_pos_breakdown(self, week_str: str) -> float:
        logged = 0.0
        start_d, end_d = get_week_dates(week_str)
        for d_str, entries in self.positives_raw.items():
            try:
                r_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                if start_d <= r_date <= end_d:
                    for e in entries:
                        logged += e["points"]
            except ValueError:
                pass
        return round(logged, 1)

    def get_day_metrics(self, day_str: str) -> dict[str, Any]:
        from toggl.services.metrics import MetricsService
        return MetricsService(self).get_day_metrics(day_str)

    def get_week_dashboard_rows(self, label: str) -> dict[str, Any]:
        from toggl.services.metrics import MetricsService
        return MetricsService(self).get_week_dashboard_rows(label)

    def get_report_sections(self, label: str, context_type: str) -> dict[str, Any]:
        from toggl.services.metrics import MetricsService
        return MetricsService(self).get_report_sections(label, context_type)

    def get_yearly_day_net_map(self, year: int) -> dict[str, float]:
        if not hasattr(self, "_yearly_day_net"):
            self._yearly_day_net: dict[int, dict[str, float]] = {}

        if year in self._yearly_day_net:
            return self._yearly_day_net[year]

        result: dict[str, float] = {}
        start_d = date(year, 1, 1)
        end_d = date(year, 12, 31)
        d = start_d
        while d <= end_d:
            d_str = d.strftime("%Y-%m-%d")
            projs = self.daily_data.get(d_str, {})
            if projs:
                res = calculate(projs)
                earned = sum(r[3] for r in res if r[3] is not None and r[3] > 0)
                tracked_neg = sum(abs(r[3]) for r in res if r[3] is not None and r[3] < 0)
            else:
                earned = 0.0
                tracked_neg = 0.0

            neg_entries = self.negatives_raw.get(d_str, [])
            pos_entries = self.positives_raw.get(d_str, [])
            logged_neg = sum(e["points"] for e in neg_entries)
            logged_pos = sum(e["points"] for e in pos_entries)

            net = round(earned - tracked_neg - logged_neg + logged_pos, 1)
            if projs or neg_entries or pos_entries:
                result[d_str] = net
            d += timedelta(days=1)

        self._yearly_day_net[year] = result
        return result

    def get_monthly_aggregates(self, last_n_months: int = 12) -> list[dict[str, Any]]:
        if not hasattr(self, "_monthly_aggregates"):
            self._monthly_aggregates: dict[int, list[dict]] = {}

        if last_n_months in self._monthly_aggregates:
            return self._monthly_aggregates[last_n_months]

        today = date.today()
        result = []
        year = today.year
        month = today.month

        for _ in range(last_n_months):
            month_str = f"{year}-{month:02d}"
            hours = 0.0
            net = 0.0

            first_day = date(year, month, 1)
            if month == 12:
                last_day = date(year, 12, 31)
            else:
                last_day = date(year, month + 1, 1) - timedelta(days=1)

            d = first_day
            while d <= last_day:
                d_str = d.strftime("%Y-%m-%d")
                projs = self.daily_data.get(d_str, {})
                if projs:
                    res = calculate(projs)
                    earned = sum(r[3] for r in res if r[3] is not None and r[3] > 0)
                    tracked_neg = sum(abs(r[3]) for r in res if r[3] is not None and r[3] < 0)
                    hours += sum(projs.values())
                else:
                    earned = 0.0
                    tracked_neg = 0.0

                neg_entries = self.negatives_raw.get(d_str, [])
                pos_entries = self.positives_raw.get(d_str, [])
                logged_neg = sum(e["points"] for e in neg_entries)
                logged_pos = sum(e["points"] for e in pos_entries)
                net += round(earned - tracked_neg - logged_neg + logged_pos, 1)
                d += timedelta(days=1)

            result.insert(0, {
                "month": month_str,
                "hours": round(hours, 1),
                "net": round(net, 1),
            })

            month -= 1
            if month < 1:
                month = 12
                year -= 1

        self._monthly_aggregates[last_n_months] = result
        return result

    def get_daily_data_for_range(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
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
            projs = self.daily_data.get(d_str, {})
            neg_entries = self.negatives_raw.get(d_str, [])
            pos_entries = self.positives_raw.get(d_str, [])
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

    def get_range_aggregate(self, start_date: date, end_date: date) -> dict[str, Any]:
        """Aggregate projects and logged activities across a date range.

        Returns (project_results, negative_results, positive_results)
        where each is structured identically to get_report_sections output.
        """
        # Aggregate project hours
        projects: dict[str, float] = {}
        d = start_date
        while d <= end_date:
            d_str = d.strftime("%Y-%m-%d")
            for proj, hrs in self.daily_data.get(d_str, {}).items():
                projects[proj] = projects.get(proj, 0.0) + hrs
            d += timedelta(days=1)

        results = calculate(projects)

        # Aggregate logged negatives
        neg_entries = []
        for d_str, entries in self.negatives_raw.items():
            try:
                dd = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            if start_date <= dd <= end_date:
                neg_entries.extend(entries)
        negative_results = calculate_logged_activity_totals(neg_entries, NEGATIVES, sign=-1)

        # Aggregate logged positives
        pos_entries = []
        for d_str, entries in self.positives_raw.items():
            try:
                dd = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            if start_date <= dd <= end_date:
                pos_entries.extend(entries)
        positive_results = calculate_logged_activity_totals(pos_entries, POSITIVES)

        return {
            "results": results,
            "positive": [r for r in results if r[3] is not None and r[3] >= 0],
            "negative": [r for r in results if r[3] is not None and r[3] < 0],
            "unscored": [r for r in results if r[3] is None],
            "positive_results": positive_results,
            "negative_results": negative_results,
        }

    def get_recovery_rows(self, label: str, context_type: str) -> dict[str, Any]:
        import math

        report = self.get_report_sections(label, context_type)
        total_pts = report["total_points"]
        if total_pts >= 0:
            return {"total_points": total_pts, "rows": []}
        deficit = abs(total_pts)
        rows = []

        # Tracked projects with positive rates (hourly)
        for name, rate in sorted(
            [(name, rate) for name, rate in POINTS.items() if rate > 0], key=lambda item: -item[1]
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
        if POSITIVES:
            for name, points in sorted(
                [(name, v) for name, v in POSITIVES.items() if v > 0 and name not in RECOVERY_IGNORE],
                key=lambda item: -item[1],
            ):
                occurrences_needed = math.ceil(deficit / points)
                rows.append({
                    "category": name,
                    "rate": points,
                    "hours_needed": f"×{occurrences_needed}",
                })

        return {"total_points": total_pts, "rows": rows}


# ──────────────────────────────────────────────
# CACHE SINGLETON
# ──────────────────────────────────────────────
_cache: DataCache | None = None


def get_cache() -> DataCache:
    """Lazy-initialised DataCache singleton for CLI paths."""
    global _cache
    if _cache is None:
        _cache = DataCache.load()
    return _cache


def reset_cache() -> None:
    """Force cache reload after sync."""
    global _cache
    _cache = DataCache.load()


# Backward-compatible aliases for moved sync functions
from toggl.services.sync import (  # noqa: E402, F401
    _patch_daily_csv,
    _patch_weekly_csv,
    fetch_week_data,
    sync_api_to_csv,
    sync_current_week_light,
)
