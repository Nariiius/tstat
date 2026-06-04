"""DataCache — reads all CSVs once per refresh cycle, serves queries from memory."""

import os
import csv
from typing import Any
import io
from datetime import datetime, date, timedelta

from toggl.const import (
    CSV_FILE, DAILY_CSV_FILE, NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE,
    HISTORY_FILE,
)
from toggl.config import POINTS, NEGATIVES, POSITIVES
from toggl.calc import calculate_logged_activity_totals



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
from toggl.services.sync import _load_history


def get_last_updated_str() -> str:
    dt = get_last_api_sync_time()
    if dt is None:
        return "Never"
    return format_time_ago(dt)


def format_time_ago(dt: datetime | None) -> str:
    """Human-readable age string from a datetime (e.g. ``3s ago``)."""
    short = format_time_ago_short(dt)
    if short == "--":
        return "never"
    return f"{short} ago"


def format_time_ago_short(dt: datetime | None) -> str:
    """Compact age string for status chrome (e.g. ``3s``, ``1m``, ``2h``)."""
    if dt is None:
        return "--"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    secs = int((now - dt).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    rem = mins % 60
    return f"{hrs}h{rem}m" if rem else f"{hrs}h"


def get_last_api_sync_time() -> datetime | None:
    """Return the last API sync timestamp from history, if recorded."""
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return None
    return parse_iso(ts)


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
