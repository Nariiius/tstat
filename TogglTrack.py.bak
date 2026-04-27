#!/usr/bin/env python3
"""
TogglTrack.py — Toggl Track API → Life Points Calculator

Usage:
  python3 TogglTrack.py                 # Show lifetime total points
  python3 TogglTrack.py --update        # Sync current week only (uses cached projects)
  python3 TogglTrack.py --update-all    # Full sync: refresh projects + last 4 weeks
  python3 TogglTrack.py --update-all 8  # Full sync: refresh projects + last 8 weeks

  # Weekly Views (reads toggl_data.csv - Weeks start on SUNDAY)
  python3 TogglTrack.py --week          # Show detailed dashboard for the CURRENT week
  python3 TogglTrack.py --week YYNN     # Show specific week (e.g. 2616)

  # Daily Views (reads toggl_daily.csv - current week only)
  python3 TogglTrack.py --today         # Show today's points
  python3 TogglTrack.py --yesterday     # Show yesterday's points
  python3 TogglTrack.py --day mon       # Show specific day (sun, mon, tue, etc.)

  # Negatives System
  python3 TogglTrack.py --negatives       # View the catalog of negative actions
  python3 TogglTrack.py --negative        # Pick a negative action interactively
  python3 TogglTrack.py --negative "Name" # Log a negative action by name
  python3 TogglTrack.py --neg-log         # Show negatives log grouped by week (default)
  python3 TogglTrack.py --neg-log month   # Show negatives log grouped by month

  # API Quota
  python3 TogglTrack.py --quota           # Show remaining API requests & time until reset
"""

import sys
import os
import re
import json
import csv
import threading
import urllib.request
import urllib.parse
import urllib.error
import base64
import argparse
import io
from datetime import datetime, date, timedelta, timezone

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static, OptionList
from textual.worker import Worker, get_current_worker
from textual._work_decorator import work


def parse_iso(s):
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
# CUSTOM EXCEPTIONS
# ──────────────────────────────────────────────
class TogglRateLimitError(Exception):
    """Raised when Toggl API returns 402/429 rate limit."""
    def __init__(self, message="", limit=None, remaining=None, resets_in=None):
        super().__init__(message)
        self.limit = limit
        self.remaining = remaining
        self.resets_in = resets_in


class TogglAPIError(Exception):
    """Raised on non-rate-limit API errors from Toggl."""
    def __init__(self, message="", status_code=None):
        super().__init__(message)
        self.status_code = status_code


# ──────────────────────────────────────────────
# TASK SHORT NAMES (for catchup block)
# ──────────────────────────────────────────────
TASK_SHORT_NAMES = {
    "Building Projects": "Build",
    "Finance / Markets": "Finance",
    "Learning to Code": "Code",
    "Fitness": "Fitness",
    "Learning Japanese": "Japanese",
    "Obligations / Social": "Social",
    "Personal Development": "Personal Dev",
    "Acads / Study": "Acads",
    "Plan / Org / Review": "Plan/Org",
    "Focus Thoughts": "Focus",
    "Chores / Waste": "Chores",
}

# ──────────────────────────────────────────────
# ANSI COLOURS
# ──────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ──────────────────────────────────────────────
# VISUAL WIDTH HELPERS
# ──────────────────────────────────────────────
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s):
    return _ANSI_RE.sub("", s)


def vlen(s):
    """Visual length of a string (ignores ANSI escape codes)."""
    return len(strip_ansi(s))


def pad_ansi(s, width):
    """Right-pad an ANSI string so its visual length equals `width`."""
    vis = vlen(s)
    if vis >= width:
        return s
    return s + " " * (width - vis)


# ──────────────────────────────────────────────
# LAYOUT CONSTANTS
# ──────────────────────────────────────────────
# Main table columns (visual widths)
COL1, COL2, COL3, COL4 = 23, 8, 8, 10
# TABLE_W = 2 (indent) + COL1 + 1 + COL2 + 1 + COL3 + 1 + COL4
TABLE_W = 2 + COL1 + 1 + COL2 + 1 + COL3 + 1 + COL4  # = 54

# Sparkbar columns
SPARK_PTS_W = 5  # e.g. "-100.5"
SPARK_BAR_W = 3  # max blocks on each side of day axis
BLAME_W = 3  # blocks in tracked/logged neg blame bar

# SPARK_W = full panel width (axis + blame bar)
SPARK_W = (
    SPARK_PTS_W
    + 1
    + SPARK_BAR_W
    + 1
    + 3
    + 1
    + SPARK_BAR_W
    + 1
    + SPARK_PTS_W
    + 2
    + BLAME_W
)  # = 28

TABLE_SPARK_GAP = 1  # spaces between table and sparkbar panel
SPARK_START_ROW = 1  # which table-lines[] index the sparkbar header aligns with

# ──────────────────────────────────────────────
# FILE PATHS
# ──────────────────────────────────────────────
DIR_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR_PATH, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
CSV_FILE = os.path.join(DATA_DIR, "toggl_data.csv")
DAILY_CSV_FILE = os.path.join(DATA_DIR, "toggl_daily.csv")
NEGATIVES_CSV_FILE = os.path.join(DATA_DIR, "toggl_negatives.csv")
POSITIVES_CSV_FILE = os.path.join(DATA_DIR, "toggl_positives.csv")
HISTORY_FILE = os.path.join(DATA_DIR, "toggl_sync_history.json")
CONFIG_FILE = os.path.join(DIR_PATH, "toggl_config.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "toggl_projects.json")

DEFAULT_DAILY_TARGET = 13.0
LOW_QUOTA_WARNING = 5
PROJECTS_CACHE_MAX_AGE_DAYS = 7

# ──────────────────────────────────────────────
# DATA CACHE — reads all CSVs once per refresh cycle
# ──────────────────────────────────────────────
class DataCache:
    """Parses all 4 CSV files into memory once, then serves queries from dicts."""

    def __init__(self):
        # weekly_data: {week_str: {project: hours}}
        self.weekly_data: dict[str, dict[str, float]] = {}
        # daily_data: {date_str: {project: hours}}
        self.daily_data: dict[str, dict[str, float]] = {}
        # negatives_raw: {date_str: [{name, points}]}
        self.negatives_raw: dict[str, list[dict]] = {}
        # positives_raw: {date_str: [{name, points}]}
        self.positives_raw: dict[str, list[dict]] = {}

    @classmethod
    def load(cls) -> "DataCache":
        cache = cls()
        cache._load_weekly()
        cache._load_daily()
        cache._load_negatives()
        cache._load_positives()
        return cache

    def _load_weekly(self):
        if not os.path.exists(CSV_FILE):
            return
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                wk = row["Week"]
                proj = row["Project"]
                hrs = float(row["Hours"])
                self.weekly_data.setdefault(wk, {})
                self.weekly_data[wk][proj] = self.weekly_data[wk].get(proj, 0.0) + hrs

    def _load_daily(self):
        if not os.path.exists(DAILY_CSV_FILE):
            return
        with open(DAILY_CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = row["Date"]
                proj = row["Project"]
                hrs = float(row["Hours"])
                self.daily_data.setdefault(d, {})
                self.daily_data[d][proj] = self.daily_data[d].get(proj, 0.0) + hrs

    def _load_negatives(self):
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

    def _load_positives(self):
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

    def get_week_projects(self, week_str):
        return dict(self.weekly_data.get(week_str, {})) or None

    def get_day_projects(self, day_str):
        return dict(self.daily_data.get(day_str, {})) or None

    def get_all_time_projects(self):
        if not self.weekly_data:
            return None
        projects: dict[str, float] = {}
        for wk_projs in self.weekly_data.values():
            for proj, hrs in wk_projs.items():
                projects[proj] = projects.get(proj, 0.0) + hrs
        return projects

    def get_negatives_for_context(self, label, context_type):
        negatives_dict: dict[str, float] = {}
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
                for e in entries:
                    negatives_dict[e["name"]] = negatives_dict.get(e["name"], 0.0) + e["points"]
        return [(name, None, None, -pts) for name, pts in negatives_dict.items()]

    def get_positives_for_context(self, label, context_type):
        positives_dict: dict[str, float] = {}
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
                for e in entries:
                    positives_dict[e["name"]] = positives_dict.get(e["name"], 0.0) + e["points"]
        return [(name, None, None, pts) for name, pts in positives_dict.items()]

    def get_negative_log_rows(self, limit=30):
        rows = []
        for d_str, entries in self.negatives_raw.items():
            for e in entries:
                rows.append({"date": d_str, "name": e["name"], "points": e["points"]})
        rows.sort(key=lambda item: item["date"], reverse=True)
        return rows[:limit]

    def get_positive_log_rows(self, limit=30):
        rows = []
        for d_str, entries in self.positives_raw.items():
            for e in entries:
                rows.append({"date": d_str, "name": e["name"], "points": e["points"]})
        rows.sort(key=lambda item: item["date"], reverse=True)
        return rows[:limit]

    def get_week_neg_breakdown(self, week_str):
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

    def get_week_pos_breakdown(self, week_str):
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

    def get_day_metrics(self, day_str):
        projects = self.get_day_projects(day_str) or {}
        results = calculate(projects)
        negatives = self.get_negatives_for_context(day_str, "DAY")
        positives = self.get_positives_for_context(day_str, "DAY")
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
            "delta": round(net - DAILY_TARGET, 1),
        }

    def get_week_dashboard_rows(self, label):
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
            if not has_activity and d > date.today():
                continue
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
                "positive_total": round(metrics["earned"] + metrics["logged_positive"], 1),
                "logged_negative": metrics["logged_negative"],
                "negative_total": round(metrics["tracked_negative"] + metrics["logged_negative"], 1),
                "goal": DAILY_TARGET,
                "delta": metrics["delta"],
                "net": metrics["net"],
                "has_activity": has_activity,
                "is_today": d == date.today(),
            })
        expected = round(DAILY_TARGET * cumulative_days, 1)
        return {
            "rows": rows,
            "summary": {
                "days_counted": cumulative_days,
                "expected": expected,
                "actual": round(cumulative_net, 1),
                "delta": round(cumulative_net - expected, 1),
            },
        }

    def get_report_sections(self, label, context_type):
        if context_type == "DAY":
            projects = self.get_day_projects(label) or {}
        elif context_type == "WEEK":
            projects = self.get_week_projects(label) or {}
        else:
            projects = self.get_all_time_projects() or {}
        results = calculate(projects)
        negative_results = self.get_negatives_for_context(label, context_type)
        positive_results = self.get_positives_for_context(label, context_type)
        total_pts = round(
            sum(r[3] for r in results if r[3] is not None) + sum(r[3] for r in negative_results) + sum(r[3] for r in positive_results),
            2,
        )
        return {
            "results": results,
            "negative_results": negative_results,
            "positive_results": positive_results,
            "positive": [r for r in results if r[3] is not None and r[3] >= 0],
            "negative": [r for r in results if r[3] is not None and r[3] < 0],
            "unscored": [r for r in results if r[3] is None],
            "total_points": total_pts,
            "total_hours": round(sum(r[1] for r in results if r[1] is not None), 2),
        }

    def get_recovery_rows(self, label, context_type):
        report = self.get_report_sections(label, context_type)
        total_pts = report["total_points"]
        if total_pts >= 0:
            return {"total_points": total_pts, "rows": []}
        deficit = abs(total_pts)
        rows = []
        for name, rate in sorted(
            [(name, rate) for name, rate in POINTS.items() if rate > 0], key=lambda item: -item[1]
        ):
            hours_needed = deficit / rate
            h = int(hours_needed)
            m = int((hours_needed - h) * 60)
            rows.append({"category": name, "rate": rate, "hours_needed": f"{h}h {m:02d}m"})
        return {"total_points": total_pts, "rows": rows}

POINTS = {}
NEGATIVES = {}
POSITIVES = {}
DAILY_TARGET = DEFAULT_DAILY_TARGET
API_RUN_STATS = {
    "requests_made": 0,
    "remaining": None,
    "limit": None,
    "resets_in": None,
}
_api_stats_lock = threading.Lock()

_cache = None

def get_cache():
    """Lazy-initialised DataCache singleton for CLI paths."""
    global _cache
    if _cache is None:
        _cache = DataCache()
        _cache.load()
    return _cache

def reset_cache():
    """Force cache reload after sync."""
    global _cache
    if _cache is not None:
        _cache.load()


# ──────────────────────────────────────────────
# CONFIG HELPERS
# ──────────────────────────────────────────────
class Config:
    """Encapsulates all runtime configuration loaded from toggl_config.json."""
    __slots__ = ("points", "negatives", "positives", "daily_target")

    def __init__(self, points, negatives, positives, daily_target):
        self.points = points
        self.negatives = negatives
        self.positives = positives
        self.daily_target = daily_target

    @classmethod
    def load(cls) -> "Config":
        config = load_config()
        points = _load_rate_map(config, "points")
        negatives = _load_rate_map(config, "negatives")
        positives = _load_rate_map(config, "positives")
        daily_target = float(_coerce_number(
            config.get("daily_target", DEFAULT_DAILY_TARGET), "daily_target"
        ))
        return cls(points, negatives, positives, daily_target)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        print(f"{RED}Error: {CONFIG_FILE} must contain a JSON object.{RESET}")
        sys.exit(1)
    return data


def _coerce_number(value, label):
    try:
        num = float(value)
    except (TypeError, ValueError):
        print(f"{RED}Error: Invalid numeric value for {label}: {value!r}{RESET}")
        sys.exit(1)
    return int(num) if num.is_integer() else num


def _load_rate_map(config, key):
    raw = config.get(key)
    if raw is None:
        print(f"{RED}Error: Missing required '{key}' object in {CONFIG_FILE}.{RESET}")
        sys.exit(1)
    if not isinstance(raw, dict):
        print(f"{RED}Error: '{key}' in {CONFIG_FILE} must be an object.{RESET}")
        sys.exit(1)
    result = {}
    for name, rate in raw.items():
        result[str(name)] = _coerce_number(rate, f"{key}.{name}")
    return result


def load_runtime_settings():
    global POINTS, NEGATIVES, POSITIVES, DAILY_TARGET
    cfg = Config.load()
    POINTS = cfg.points
    NEGATIVES = cfg.negatives
    POSITIVES = cfg.positives
    DAILY_TARGET = cfg.daily_target


# ──────────────────────────────────────────────
# TOGGL API HELPERS
# ──────────────────────────────────────────────
def get_api_token():
    if os.environ.get("TOGGL_API_TOKEN"):
        return os.environ.get("TOGGL_API_TOKEN")
    data = load_config()
    if data.get("api_token"):
        return data["api_token"]
    print(f"{YELLOW}Toggl API Token not found.{RESET}")
    print(f"Find it here: {CYAN}https://track.toggl.com/profile{RESET}")
    token = input("Enter your Toggl API Token: ").strip()
    if not token:
        print(f"{RED}Error: API Token is required.{RESET}")
        sys.exit(1)
    data["api_token"] = token
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)
    print(f"{DIM}Token saved to {CONFIG_FILE}{RESET}\n")
    return token


def _normalize_headers(headers):
    return {k.lower(): v for k, v in headers.items()}


def _header_value(headers, *names):
    normalized = _normalize_headers(headers)
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reset_api_stats():
    with _api_stats_lock:
        API_RUN_STATS["requests_made"] = 0
        API_RUN_STATS["remaining"] = None
        API_RUN_STATS["limit"] = None
        API_RUN_STATS["resets_in"] = None


def _record_quota_headers(headers):
    remaining = _parse_int(_header_value(headers, "X-Toggl-Quota-Remaining"))
    limit = _parse_int(_header_value(headers, "X-Toggl-Quota-Limit"))
    resets_in = _parse_int(_header_value(headers, "X-Toggl-Quota-Resets-In"))
    with _api_stats_lock:
        if remaining is not None:
            API_RUN_STATS["remaining"] = remaining
        if limit is not None:
            API_RUN_STATS["limit"] = limit
        if resets_in is not None:
            API_RUN_STATS["resets_in"] = resets_in


def _format_reset_window(secs):
    if secs is None:
        return "Unknown"
    mins, s = divmod(secs, 60)
    return f"{mins}m {s:02d}s" if mins else f"{s}s"


def _print_api_usage_summary():
    print(f"\n  {BOLD}{CYAN}SYNC API USAGE{RESET}")
    print("  " + "─" * 35)
    print(f"  Requests used       {CYAN}{BOLD}{API_RUN_STATS['requests_made']}{RESET}")
    if API_RUN_STATS["remaining"] is not None:
        limit = API_RUN_STATS["limit"] if API_RUN_STATS["limit"] is not None else "?"
        print(
            f"  Quota remaining     {YELLOW}{BOLD}{API_RUN_STATS['remaining']}/{limit}{RESET}"
        )
    if API_RUN_STATS["resets_in"] is not None:
        wait = _format_reset_window(API_RUN_STATS["resets_in"])
        print(f"  Window resets in    {DIM}{wait}{RESET}")
    print()


def _make_auth_request(url, token, method="GET"):
    auth_string = f"{token}:api_token"
    b64_auth = base64.b64encode(auth_string.encode()).decode()
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Basic {b64_auth}")
    req.add_header("Content-Type", "application/json")
    with _api_stats_lock:
        API_RUN_STATS["requests_made"] += 1
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode() if method != "HEAD" else None
            headers = dict(response.headers)
            _record_quota_headers(headers)
            return body, headers, None
    except urllib.error.HTTPError as e:
        headers = dict(e.headers) if e.headers else {}
        _record_quota_headers(headers)
        return None, headers, e.code
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, {}, str(e)


def toggl_request(endpoint, token):
    url = "https://api.track.toggl.com/api/v9/" + endpoint
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        if body is None:
            raise TogglAPIError("API returned empty response", status_code=None)
        return json.loads(body)
    if err in (402, 429):
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get(
            "x-toggl-quota-resets-in"
        )
        remaining = headers.get("X-Toggl-Quota-Remaining") or headers.get(
            "x-toggl-quota-remaining", "0"
        )
        limit = headers.get("X-Toggl-Quota-Limit") or headers.get(
            "x-toggl-quota-limit", "30"
        )
        msg = f"Rate limit reached ({limit} req/hr)"
        if resets_in:
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            msg += f" — resets in {wait}"
        msg += f" (Remaining: {remaining}/{limit})"
        raise TogglRateLimitError(msg, limit=limit, remaining=remaining, resets_in=resets_in)
    raise TogglAPIError(f"API Error: {err} for endpoint {endpoint}", status_code=err)


def check_quota(token):
    url = "https://api.track.toggl.com/api/v9/me"
    print(f"\n  {BOLD}{CYAN}API QUOTA STATUS{RESET}")
    print("  " + "─" * 35)
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        remaining = headers.get("X-Toggl-Quota-Remaining") or headers.get("x-toggl-quota-remaining", "Unknown")
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get("x-toggl-quota-resets-in", "Unknown")
        print(f"  {GREEN}✓ Request successful{RESET}")
        print(f"  Requests remaining  {CYAN}{BOLD}{remaining}{RESET}")
        if resets_in != "Unknown":
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
        else:
            print(f"  Window resets in    {DIM}Unknown{RESET}")
    elif err == 429:
        print(f"  {RED}✗ HTTP 429 — Rate limit exceeded.{RESET}")
        print(f"  {DIM}Making requests too fast. Safe limit is ~1 req/sec.{RESET}")
    elif err == 402:
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get("x-toggl-quota-resets-in", "Unknown")
        print(f"  {RED}✗ HTTP 402 — Hourly quota exhausted.{RESET}")
        if resets_in != "Unknown":
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
    else:
        print(f"  {RED}✗ HTTP {err}{RESET}")
    print()


def _prompt_yes_no(prompt):
    while True:
        ans = input(prompt).strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print(f"{YELLOW}Please enter 'y' or 'n'.{RESET}")


def get_projects_cache_age_days():
    if not os.path.exists(PROJECTS_FILE):
        return None
    age_secs = datetime.now().timestamp() - os.path.getmtime(PROJECTS_FILE)
    return age_secs / 86400.0


def is_projects_cache_stale(max_age_days=PROJECTS_CACHE_MAX_AGE_DAYS):
    age_days = get_projects_cache_age_days()
    return age_days is None or age_days > max_age_days


def _confirm_sync_quota(token, estimated_requests, sync_label, prompt_on_warning=True):
    url = "https://api.track.toggl.com/api/v9/me"
    _, _, err = _make_auth_request(url, token)

    if err == 402:
        wait = _format_reset_window(API_RUN_STATS["resets_in"])
        print(f"\n  {RED}{BOLD}Cannot start {sync_label}.{RESET}")
        print(f"  {DIM}Hourly quota is already exhausted. Reset in {wait}.{RESET}\n")
        return False
    if err == 429:
        print(f"\n  {RED}{BOLD}Cannot start {sync_label}.{RESET}")
        print(f"  {DIM}Rate limited right now. Wait a moment and try again.{RESET}\n")
        return False
    if err is not None:
        print(f"\n  {RED}Failed to check quota before {sync_label}: {err}{RESET}\n")
        return False

    remaining = API_RUN_STATS["remaining"]
    if remaining is None:
        return True

    needs_warning = remaining < LOW_QUOTA_WARNING or remaining < estimated_requests
    if not needs_warning:
        return True

    limit = API_RUN_STATS["limit"] if API_RUN_STATS["limit"] is not None else "?"
    wait = _format_reset_window(API_RUN_STATS["resets_in"])
    if not prompt_on_warning:
        return False

    print(f"\n  {YELLOW}{BOLD}Low quota warning before {sync_label}{RESET}")
    print(f"  Remaining quota     {YELLOW}{BOLD}{remaining}/{limit}{RESET}")
    print(f"  Estimated requests  {CYAN}{BOLD}{estimated_requests}{RESET}")
    print(f"  Window resets in    {DIM}{wait}{RESET}")
    print(f"  {DIM}Continuing could stop mid-sync if the quota runs out.{RESET}")
    print()
    return _prompt_yes_no(f"{YELLOW}Continue sync anyway? (y/n): {RESET}")


def get_projects_map(token, use_cache=False):
    if use_cache and os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
    projects_data = toggl_request("me/projects", token)
    result = {p["id"]: p["name"] for p in projects_data if p.get("active")}
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in result.items()}, f, indent=2)
    return result


# ──────────────────────────────────────────────
# DATE & WEEK HELPERS
# ──────────────────────────────────────────────
def get_sunday_of_week(d):
    days_since_sun = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sun)


def get_week_str(d):
    return get_sunday_of_week(d).strftime("%Y-W%U")


def get_current_week():
    return get_week_str(date.today())


def get_week_dates(week_str):
    dt = datetime.strptime(f"{week_str}-0", "%Y-W%U-%w")
    start_date = dt.date()
    end_date = start_date + timedelta(days=6)
    return start_date, end_date


def get_iso_format(d, is_end=False):
    local_tz = datetime.now().astimezone().tzinfo
    if is_end:
        dt = datetime.combine(d, datetime.max.time(), tzinfo=local_tz)
    else:
        dt = datetime.combine(d, datetime.min.time(), tzinfo=local_tz)
    return urllib.parse.quote(dt.isoformat())


# ──────────────────────────────────────────────
# LAST-UPDATED HELPERS
# ──────────────────────────────────────────────
def _load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path, content_str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content_str)
    os.replace(tmp, path)


def _save_history(history):
    _atomic_write(HISTORY_FILE, json.dumps(history, indent=4))


def get_last_updated_str():
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return "never"
    dt = parse_iso(ts)
    if dt is None:
        return "never"
    diff = datetime.now() - dt
    mins = int(diff.total_seconds() / 60)
    if mins < 1:
        return "just now"
    elif mins < 60:
        return f"{mins}m ago"
    else:
        hrs = mins // 60
        rem = mins % 60
        return f"{hrs}h {rem}m ago" if rem else f"{hrs}h ago"


def needs_auto_update():
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return False
    dt = parse_iso(ts)
    if dt is None:
        return False
    diff = datetime.now() - dt
    return diff.total_seconds() > 1800


# ──────────────────────────────────────────────
# DATA SYNC LOGIC
# ──────────────────────────────────────────────
def fetch_week_data(week_str, token, projects_map):
    start_d, end_d = get_week_dates(week_str)
    start_iso = get_iso_format(start_d, is_end=False)
    end_iso = get_iso_format(end_d, is_end=True)
    endpoint = f"me/time_entries?start_date={start_iso}&end_date={end_iso}"
    entries = toggl_request(endpoint, token)
    weekly_hours = {}
    daily_hours = {}
    for entry in entries:
        duration_sec = entry.get("duration", 0)
        if duration_sec < 0:
            continue
        pid = entry.get("project_id")
        project_name = projects_map.get(pid, "No Project")
        hours = duration_sec / 3600.0
        weekly_hours[project_name] = weekly_hours.get(project_name, 0.0) + hours
        start_str = entry.get("start")
        if start_str:
            dt = parse_iso(start_str)
            if dt is not None:
                dt = dt.astimezone()
            else:
                continue
            day_str = dt.strftime("%Y-%m-%d")
            if day_str not in daily_hours:
                daily_hours[day_str] = {}
            daily_hours[day_str][project_name] = (
                daily_hours[day_str].get(project_name, 0.0) + hours
            )
    return weekly_hours, daily_hours


def _write_daily_csv(daily_data):
    rows = []
    for day_str, projs in daily_data.items():
        for proj, hours in projs.items():
            rows.append({"Date": day_str, "Project": proj, "Hours": round(hours, 4)})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(DAILY_CSV_FILE, buf.getvalue())


def _patch_weekly_csv(week_str, weekly_data):
    existing = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            existing = [row for row in csv.DictReader(f) if row["Week"] != week_str]
    for proj, hours in weekly_data.items():
        if hours > 0:
            existing.append(
                {"Week": week_str, "Project": proj, "Hours": round(hours, 4)}
            )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Week", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(existing)
    _atomic_write(CSV_FILE, buf.getvalue())


def sync_api_to_csv(weeks_back=4, prompt_on_warning=True):
    weeks_back = int(weeks_back)
    if weeks_back < 1:
        raise ValueError("--update-all expects a positive number of weeks")
    token = get_api_token()
    _reset_api_stats()
    estimated_requests = weeks_back + 2
    sync_label = f"full sync ({weeks_back} week{'s' if weeks_back != 1 else ''})"
    if not _confirm_sync_quota(
        token, estimated_requests, sync_label, prompt_on_warning=prompt_on_warning
    ):
        return {"success": False, "message": "Sync cancelled. Existing local data was left untouched."}
    projects_map = get_projects_map(token, use_cache=False)
    current_week = get_current_week()
    current_sunday = get_sunday_of_week(date.today())
    weeks_to_sync = []
    for i in range(weeks_back - 1, -1, -1):
        d = current_sunday - timedelta(days=7 * i)
        weeks_to_sync.append(get_week_str(d))
    history = _load_history()
    synced_weeks = history.get("synced_weeks", {})
    synced_days = history.get("synced_days", {})
    current_week_daily_data = {}
    weekly_payloads = {}
    for week in weeks_to_sync:
        weekly_data, daily_data = fetch_week_data(week, token, projects_map)
        weekly_payloads[week] = weekly_data
        if week == current_week:
            current_week_daily_data = daily_data
        synced_weeks[week] = datetime.now().isoformat()
    for week in weeks_to_sync:
        _patch_weekly_csv(week, weekly_payloads[week])
    today_str = date.today().strftime("%Y-%m-%d")
    synced_days[today_str] = datetime.now().isoformat()
    _write_daily_csv(current_week_daily_data)
    history["synced_weeks"] = synced_weeks
    history["synced_days"] = synced_days
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)
    return {"success": True, "message": f"Successfully synced {weeks_back} week(s)"}


def sync_current_week_light(auto_refresh=False, prompt_on_warning=True):
    token = get_api_token()
    refresh_projects = is_projects_cache_stale()
    _reset_api_stats()
    estimated_requests = 2 + (1 if refresh_projects else 0)
    sync_label = "auto-refresh" if auto_refresh else "current-week sync"
    if not _confirm_sync_quota(
        token, estimated_requests, sync_label, prompt_on_warning=prompt_on_warning
    ):
        return {"success": False, "message": "Sync cancelled. Existing local data was left untouched."}
    if refresh_projects:
        projects_map = get_projects_map(token, use_cache=False)
    else:
        projects_map = get_projects_map(token, use_cache=True)
    current_week = get_current_week()
    weekly_data, daily_data = fetch_week_data(current_week, token, projects_map)
    _patch_weekly_csv(current_week, weekly_data)
    _write_daily_csv(daily_data)
    history = _load_history()
    history.setdefault("synced_weeks", {})[current_week] = datetime.now().isoformat()
    history.setdefault("synced_days", {})[date.today().strftime("%Y-%m-%d")] = (
        datetime.now().isoformat()
    )
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)
    msg = "Auto-refreshed (data was stale >30m)" if auto_refresh else "Successfully synced current week"
    return {"success": True, "message": msg}


# ──────────────────────────────────────────────
# NEGATIVES LOGIC
# ──────────────────────────────────────────────

def pick_positive_interactive():
    names = list(POSITIVES.keys())
    if not names:
        print(f"{YELLOW}No positives configured.{RESET}")
        sys.exit(0)
    print(f"\n  {BOLD}PICK A POSITIVE{RESET}")
    print("  " + "─" * 35)
    for idx, name in enumerate(names, start=1):
        cost = POSITIVES[name]
        print(f"  {idx:>2}. {name:<22} {GREEN}+{cost} pts{RESET}")
    print()
    while True:
        raw = input(f"{YELLOW}Choose a number (blank to cancel): {RESET}").strip()
        if not raw:
            print(f"{DIM}Action cancelled.{RESET}")
            sys.exit(0)
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(names):
                return names[index - 1]
        print(f"{YELLOW}Please enter a valid number from the list.{RESET}")

def log_positive(pos_name):
    lower_map = {k.lower(): k for k in POSITIVES}
    canonical = lower_map.get(pos_name.strip().lower())
    if not canonical:
        print(f"{RED}Positive '{pos_name}' not found.{RESET}")
        sys.exit(1)
    cost = POSITIVES[canonical]
    if not _prompt_yes_no(
        f"{YELLOW}Log positive '{canonical}' for +{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    ok, message = log_positive_direct(canonical)
    if ok:
        print(f"\n{GREEN}✓ {message}{RESET}\n")
    else:
        print(f"\n{RED}✗ {message}{RESET}\n")
    sys.exit(0)

def print_pos_log(group_by="week"):
    if not os.path.exists(POSITIVES_CSV_FILE):
        print(f"{YELLOW}No positives logged yet.{RESET}")
        return
    rows = []
    with open(POSITIVES_CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                name = row.get("Positive") or row.get("Bonus") or "?"
                pts = float(row["Points"])
                rows.append((d, name, pts))
            except (KeyError, ValueError):
                continue
    if not rows:
        print(f"{YELLOW}No positives logged yet.{RESET}")
        return
    rows.sort(key=lambda x: x[0])
    groups: dict[str, list] = {}
    for d, name, pts in rows:
        key = d.strftime("%Y-%m") if group_by == "month" else get_week_str(d)
        groups.setdefault(key, []).append((d, name, pts))
    
    print(f"\n  {BOLD}{GREEN}POSITIVES LOG{RESET}  {DIM}· by {group_by}{RESET}")
    for key in sorted(groups.keys(), reverse=True):
        print(f"  {BOLD}{CYAN}{key}{RESET}")
        for d, name, pts in sorted(groups[key], key=lambda x: x[0], reverse=True):
            print(f"  {d.strftime('%Y-%m-%d')}  {name:<25} {GREEN}+{pts:>4.1f}{RESET}")
        print()

def pick_negative_interactive():
    names = list(NEGATIVES.keys())
    if not names:
        print(f"{YELLOW}No negatives configured.{RESET}")
        sys.exit(0)
    print(f"\n  {BOLD}PICK A NEGATIVE{RESET}")
    print("  " + "─" * 35)
    for idx, name in enumerate(names, start=1):
        cost = NEGATIVES[name]
        print(f"  {idx:>2}. {name:<22} {MAGENTA}-{cost} pts{RESET}")
    print()
    while True:
        raw = input(f"{YELLOW}Choose a number (blank to cancel): {RESET}").strip()
        if not raw:
            print(f"{DIM}Action cancelled.{RESET}")
            sys.exit(0)
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(names):
                return names[index - 1]
        print(f"{YELLOW}Please enter a valid number from the list.{RESET}")


def log_negative(neg_name):
    lower_map = {k.lower(): k for k in NEGATIVES}
    canonical = lower_map.get(neg_name.strip().lower())
    if not canonical:
        print(f"{RED}Negative '{neg_name}' not found.{RESET}")
        print(f"{DIM}Run --negative for the picker or -n for the catalog.{RESET}")
        sys.exit(1)
    cost = NEGATIVES[canonical]
    if not _prompt_yes_no(
        f"{YELLOW}Log negative '{canonical}' for -{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    ok, message = log_negative_direct(canonical)
    if ok:
        print(f"\n{RED}✓ {message}{RESET}\n")
    else:
        print(f"\n{RED}✗ {message}{RESET}\n")
    sys.exit(0)


def get_negatives_for_context(label, context_type):
    return get_cache().get_negatives_for_context(label, context_type)


def print_neg_log(group_by="week"):
    """Print all negatives grouped by week or month."""
    if not os.path.exists(NEGATIVES_CSV_FILE):
        print(f"{YELLOW}No negatives logged yet.{RESET}")
        return
    rows = []
    with open(NEGATIVES_CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                name = row.get("Negative") or row.get("Penalty") or "?"
                pts = float(row["Points"])
                rows.append((d, name, pts))
            except (KeyError, ValueError):
                continue
    if not rows:
        print(f"{YELLOW}No negatives logged yet.{RESET}")
        return
    rows.sort(key=lambda x: x[0])
    groups: dict[str, list] = {}
    for d, name, pts in rows:
        key = d.strftime("%Y-%m") if group_by == "month" else get_week_str(d)
        groups.setdefault(key, []).append((d, name, pts))
    print(f"\n  {BOLD}{CYAN}NEGATIVES LOG{RESET}  {DIM}· by {group_by}{RESET}")
    for key in sorted(groups.keys()):
        entries = groups[key]
        if group_by == "week":
            start_d, end_d = get_week_dates(key)
            header = f"{BOLD}{key}{RESET}  {DIM}({start_d.strftime('%d %b')} – {end_d.strftime('%d %b %Y')}){RESET}"
        else:
            header = f"{BOLD}{datetime.strptime(key, '%Y-%m').strftime('%B %Y')}{RESET}"
        group_total = sum(p for _, _, p in entries)
        print(f"\n  {header}")
        print("  " + "─" * 50)
        for d, name, pts in entries:
            date_str = d.strftime("%a %d %b")
            print(
                f"    {DIM}{date_str:<12}{RESET}  {name:<26} {MAGENTA}-{pts:.0f} pts{RESET}"
            )
        print(f"  {'':>42} {RED}{BOLD}-{group_total:.0f} pts total{RESET}")
    print()


# ──────────────────────────────────────────────
# CALCULATIONS
# ──────────────────────────────────────────────
def get_data_for_week(target_week):
    return get_cache().get_week_projects(target_week)


def get_data_for_day(target_day):
    return get_cache().get_day_projects(target_day)


def get_all_time_data():
    return get_cache().get_all_time_projects()


def calculate(projects):
    results = []
    for name, hours in projects.items():
        rate = POINTS.get(name)
        pts = round(hours * rate, 2) if rate is not None else None
        results.append((name, hours, rate, pts))

    def sort_key(r):
        if r[2] is None:
            return (1, 0, 0)
        return (0, -r[2], -(r[3] or 0))

    results.sort(key=sort_key)
    return results


def get_negative_catalog_rows():
    return [(name, NEGATIVES[name]) for name in NEGATIVES]


def get_negative_log_rows(limit=30):
    return get_cache().get_negative_log_rows(limit)


def format_signed(value):
    if abs(value) < 0.05:
        value = 0.0
    return f"+{value:.1f}" if value > 0 else (f"{value:.1f}" if value < 0 else "0.0")


def get_day_metrics(day_str):
    return get_cache().get_day_metrics(day_str)


def get_week_dashboard_rows(label):
    return get_cache().get_week_dashboard_rows(label)


def get_report_sections(label, context_type):
    return get_cache().get_report_sections(label, context_type)


def get_recovery_rows(label, context_type):
    return get_cache().get_recovery_rows(label, context_type)


def get_sync_status_data():
    history = _load_history()
    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": history.get("synced_weeks", {}),
        "synced_days": history.get("synced_days", {}),
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
    }


def get_sparkbar_text():
    return "\n".join(build_week_sparkbar_lines())



def get_positives_for_context(label, context_type):
    return get_cache().get_positives_for_context(label, context_type)

def get_positive_catalog_rows():
    return [(name, POSITIVES[name]) for name in POSITIVES]

def get_positive_log_rows(limit=30):
    return get_cache().get_positive_log_rows(limit)

def log_positive_direct(pos_name):
    lower_map = {k.lower(): k for k in POSITIVES}
    canonical = lower_map.get(pos_name.strip().lower())
    if not canonical:
        return False, f"Positive '{pos_name}' not found"
    rows = []
    if os.path.exists(POSITIVES_CSV_FILE):
        with open(POSITIVES_CSV_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    rows.append({
        "Date": date.today().strftime("%Y-%m-%d"),
        "Positive": canonical,
        "Points": POSITIVES[canonical],
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Positive", "Points"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(POSITIVES_CSV_FILE, buf.getvalue())
    return True, f"Logged {canonical} (+{POSITIVES[canonical]} pts)"


def log_negative_direct(neg_name):
    lower_map = {k.lower(): k for k in NEGATIVES}
    canonical = lower_map.get(neg_name.strip().lower())
    if not canonical:
        return False, f"Negative '{neg_name}' not found"
    rows = []
    if os.path.exists(NEGATIVES_CSV_FILE):
        with open(NEGATIVES_CSV_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    rows.append({
        "Date": date.today().strftime("%Y-%m-%d"),
        "Negative": canonical,
        "Points": NEGATIVES[canonical],
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Negative", "Points"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(NEGATIVES_CSV_FILE, buf.getvalue())
    return True, f"Logged {canonical} (-{NEGATIVES[canonical]} pts)"


# ──────────────────────────────────────────────
# SPARK TABLE CELL RENDERER
# ──────────────────────────────────────────────

def _spark_net_rich(net, max_abs, bar_w=4, dim_zero=False,
                     blame_tracked=0, blame_logged=0, blame_w=3):
    """
    Return Rich markup for a net-points cell in the interactive spark tables.
    Positive → green bar on left of value.  Negative → red value + bar on right.
    When net < 0 and blame data is provided, a blame bar (red tracked + magenta
    logged) is appended after the net bar.
    """
    if net is None or (abs(net) < 0.05 and dim_zero):
        return "[dim]—[/]"
    if abs(net) < 0.05:
        return "[dim]0.0[/]"
    bar_len = max(1, round(abs(net) / max_abs * bar_w)) if max_abs > 0 else 1
    bar = "█" * bar_len
    if net > 0:
        return f"[#37d994]{bar} +{net}[/]"
    else:
        blame_total = blame_tracked + blame_logged
        if blame_total > 0 and blame_w > 0:
            red_count = round(blame_tracked / blame_total * blame_w)
            mag_count = blame_w - red_count
            blame = f"[#ff5f5f]{'█' * red_count}[/][#ff5fff]{'█' * mag_count}[/]"
            return f"[#ff5f5f]{net} {bar}[/]{blame}"
        return f"[#ff5f5f]{net} {bar}[/]"


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("Y", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("N", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title, body):
        super().__init__()
        self.title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static(self.body, classes="dialog-body")
                yield Static("[Y/Enter] confirm   [N/Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = f"[b][#63f3ff]{self.title}[/][/]"

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class NegativeInputScreen(ModalScreen[str | None]):
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static("Select a negative action to log.", classes="dialog-body")
                yield OptionList(id="negative-list")
                yield Static("[Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = "[b][#63f3ff]Log Negative[/][/]"
        option_list = self.query_one("#negative-list", OptionList)
        for name in NEGATIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#negative-list")
    def submit_negative(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    def key_escape(self):
        self.dismiss(None)


class PositiveInputScreen(ModalScreen[str | None]):
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static("Select a positive action to log.", classes="dialog-body")
                yield OptionList(id="positive-list")
                yield Static("[Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = "[b][#37d994]Log Positive[/][/]"
        option_list = self.query_one("#positive-list", OptionList)
        for name in POSITIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#positive-list")
    def submit_positive(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    def key_escape(self):
        self.dismiss(None)

class TogglTUI(App):
    CSS = """
    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #0b1016;
        color: #d7dde8;
    }

    #root {
        height: 1fr;
    }

    #chrome {
        height: 3;
        border: solid #2e3947;
        padding: 0 1;
    }

    #view-tabs {
        height: 1;
        color: #8d98a7;
    }

    .view-tab {
        width: auto;
        margin-right: 2;
        color: #8d98a7;
    }

    .view-tab.-active {
        color: #63f3ff;
        text-style: bold;
    }

    #main {
        height: 1fr;
    }

    #content {
        width: 1fr;
        height: 1fr;
        padding: 0;
    }

    .view {
        display: none;
        height: 1fr;
    }

    .view.-active {
        display: block;
    }

    DataTable {
        height: 1fr;
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    DataTable > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-rail {
        width: 34;
        min-width: 34;
        max-width: 34;
        border: none;
        padding: 0;
        display: block;
    }

    #spark-rail.-hidden {
        display: none;
    }

    #spark-weeks-table {
        height: auto;
        min-height: 5;
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-weeks-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-weeks-table > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-days-table {
        height: 1fr;
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-days-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-days-table > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-catchup {
        height: auto;
        border: solid #2e3947;
        padding: 0 1;
    }

    #footer {
        height: auto;
        border-top: solid #2e3947;
        padding: 0 1;
    }

    #footer-main {
        color: #63f3ff;
    }

    #dialog {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #dialog-box {
        width: 60;
        height: auto;
        border: solid #2e3947;
        padding: 1 2;
        background: #0b1016;
    }

    .dialog-body {
        margin-bottom: 1;
    }

    .dialog-help {
        color: #8d98a7;
        margin-top: 1;
    }

    OptionList {
        background: #0b1016;
        color: #d7dde8;
        border: none;
        height: auto;
        max-height: 10;
    }

    OptionList > .option-list--option {
        padding: 0 1;
    }

    OptionList > .option-list--option-highlighted {
        background: #27323d;
        color: #63f3ff;
    }

    Toast {
        background: #0b1016;
        color: #d7dde8;
        border: solid #2e3947;
        padding: 0 1;
        margin: 1 1 0 0;
        height: auto;
    }
    Toast.-information {
        border: solid #37d994;
    }
    Toast.-warning {
        border: solid #e2b714;
    }
    Toast.-error {
        border: solid #ff5f5f;
    }
    """

    BINDINGS = [
        Binding("left", "prev_view", "Prev View"),
        Binding("right", "next_view", "Next View"),
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("u", "sync_current_week", "Sync Week"),
        Binding("U", "sync_full", "Full Sync"),
        Binding("n", "add_negative", "Add Negative"),
        Binding("p", "add_positive", "Add Positive"),
        Binding("s", "toggle_sparkbar", "Sparkbar"),
        Binding("question_mark", "show_help", "Help"),
    ]

    VIEWS = ["Overview", "Day", "Week", "Negatives", "Positives", "Recovery", "Sync/Quota"]

    def __init__(self):
        super().__init__()
        self.active_view_index = 1
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self.sparkbar_collapsed = False
        self.sparkbar_forced_open = True   # open by default; `s` can toggle it closed
        self._table_resize_timer = None
        self._is_syncing_cursors = False
        self._data_cache: DataCache | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Container(id="chrome"):
                with Horizontal(id="view-tabs"):
                    for index, view in enumerate(self.VIEWS):
                        yield Static(view, classes="view-tab", id=f"view-tab-{index}")
            with Horizontal(id="main"):
                with Container(id="content"):
                    with Container(id="overview-view", classes="view -active"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="overview-table")
                    with Container(id="day-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="day-table")
                    with Container(id="week-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="week-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="week-category-table")
                    with Container(id="negatives-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="negatives-catalog-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="negatives-log-table")
                    with Container(id="positives-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="positives-catalog-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="positives-log-table")
                    with Container(id="recovery-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="recovery-table")
                    with Container(id="sync-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="sync-table")
                # ── Spark rail: interactive side-panel with the same DataTable
                #    design as the main views — selectable, cursor-navigable,
                #    collapsible via `s`.
                with Vertical(id="spark-rail"):
                    yield DataTable(show_header=False, cursor_type="row", id="spark-weeks-table", zebra_stripes=False)
                    yield DataTable(show_header=False, cursor_type="row", id="spark-days-table", zebra_stripes=False)
                    yield Static(id="spark-catchup")
            with Vertical(id="footer"):
                yield Static(id="footer-main")

    def on_mount(self):
        self._setup_tables()
        load_runtime_settings()
        if needs_auto_update():
            self._do_auto_refresh()
        self.refresh_all_views()

    @work(thread=True)
    def _do_auto_refresh(self):
        try:
            result = sync_current_week_light(auto_refresh=True, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError):
            result = {"success": False, "message": "API error during auto-refresh"}
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_auto_refresh_done, ok, message)

    def _on_auto_refresh_done(self, ok, message):
        load_runtime_settings()
        self.refresh_all_views()
        if ok:
            self.notify("Auto-refreshed stale data")
        elif message:
            self.notify("Auto-refresh skipped", severity="warning")

    def _setup_tables(self):
        week_table = self.query_one("#week-table", DataTable)
        week_table.add_columns("Day", "Date", "Hours", "Earned", "Pos", "Negs", "Net")

        week_category_table = self.query_one("#week-category-table", DataTable)
        week_category_table.add_columns("Category", "Hours", "Rate", "Points")

        overview_table = self.query_one("#overview-table", DataTable)
        overview_table.add_columns("Category", "Hours", "Rate", "Points")

        day_table = self.query_one("#day-table", DataTable)
        day_table.add_columns("Category", "Hours", "Rate", "Points")

        negatives_catalog = self.query_one("#negatives-catalog-table", DataTable)
        negatives_catalog.add_columns("Negative", "Points")

        negatives_log = self.query_one("#negatives-log-table", DataTable)
        negatives_log.add_columns("Date", "Negative", "Points")

        positives_catalog = self.query_one("#positives-catalog-table", DataTable)
        positives_catalog.add_columns("Positive", "Points")

        positives_log = self.query_one("#positives-log-table", DataTable)
        positives_log.add_columns("Date", "Positive", "Points")

        recovery_table = self.query_one("#recovery-table", DataTable)
        recovery_table.add_columns("Category", "Rate", "Hours Needed")

        sync_table = self.query_one("#sync-table", DataTable)
        sync_table.add_columns("Metric", "Value")

        # Spark rail tables — no visible header, single label + net columns
        spark_weeks = self.query_one("#spark-weeks-table", DataTable)
        spark_weeks.add_columns("Label", "Net")

        spark_days = self.query_one("#spark-days-table", DataTable)
        spark_days.add_columns("Day", "Net")

    def refresh_all_views(self):
        self._data_cache = DataCache.load()
        self.update_tabs()
        self.update_status_line()
        # Always refresh spark tables (visible in rail) + week view (drives cursor)
        self.refresh_spark_tables()
        self.refresh_week_view()
        # Only refresh the currently active view
        self._refresh_view_by_index(self.active_view_index)
        self.update_view_visibility()
        self.update_sparkbar_visibility()
        self._schedule_resize()

    _VIEW_REFRESH_MAP = {
        0: "refresh_overview_view",
        1: "refresh_day_view",
        2: "refresh_week_view",
        3: "refresh_negatives_view",
        4: "refresh_positives_view",
        5: "refresh_recovery_view",
        6: "refresh_sync_view",
    }

    def _refresh_view_by_index(self, index):
        method_name = self._VIEW_REFRESH_MAP.get(index)
        if method_name and method_name != "refresh_week_view":  # week already refreshed above
            getattr(self, method_name)()

    def _schedule_resize(self):
        """Debounced resize: cancels any pending resize before scheduling a new one."""
        if self._table_resize_timer is not None:
            self._table_resize_timer.stop()
        self._table_resize_timer = self.set_timer(0.1, self._resize_tables)

    def update_tabs(self):
        for index, view in enumerate(self.VIEWS):
            tab = self.query_one(f"#view-tab-{index}", Static)
            tab.update(view)
            tab.set_class(index == self.active_view_index, "-active")

    def update_status_line(self):
        current_week = get_current_week()
        start_d, end_d = get_week_dates(current_week)
        synced = get_last_updated_str()

        chrome = self.query_one("#chrome", Container)
        chrome.border_title = "[b][#63f3ff]Toggl Stats[/][/]"
        chrome.border_subtitle = f"  | [#8d98a7]Updated {synced}[/]"

        footer_main = Text()
        footer_main.append("Views ", style="bold #63f3ff")
        footer_main.append("<- ->", style="bold #63f3ff")
        footer_main.append(" switch  •  ", style="#8d98a7")
        footer_main.append("n", style="bold #63f3ff")
        footer_main.append(" negative  •  ", style="#8d98a7")
        footer_main.append("p", style="bold #63f3ff")
        footer_main.append(" positive  •  ", style="#8d98a7")
        footer_main.append("u", style="bold #63f3ff")
        footer_main.append(" sync  •  ", style="#8d98a7")
        footer_main.append("s", style="bold #63f3ff")
        footer_main.append(" sparkbar  •  ", style="#8d98a7")
        footer_main.append("q", style="bold #63f3ff")
        footer_main.append(" quit", style="#8d98a7")

        self.query_one("#footer-main", Static).update(footer_main)

    def update_view_visibility(self):
        view_ids = [
            "#overview-view",
            "#day-view",
            "#week-view",
            "#negatives-view",
            "#positives-view",
            "#recovery-view",
            "#sync-view",
        ]
        for index, view_id in enumerate(view_ids):
            widget = self.query_one(view_id, Container)
            widget.set_class(index == self.active_view_index, "-active")

    def focus_active_view(self):
        focus_targets = {
            0: "#overview-table",
            1: "#day-table",
            2: "#week-table",
            3: "#negatives-catalog-table",
            4: "#positives-catalog-table",
            5: "#recovery-table",
            6: "#sync-table",
        }
        selector = focus_targets.get(self.active_view_index)
        if selector:
            self.query_one(selector, DataTable).focus()

    def update_sparkbar_visibility(self):
        rail = self.query_one("#spark-rail", Vertical)
        auto_collapse = self.size.width < 120
        rail.set_class(
            self.sparkbar_collapsed or (auto_collapse and not self.sparkbar_forced_open),
            "-hidden",
        )

    # ──────────────────────────────────────────────
    # SPARK TABLES — interactive side-panel
    # ──────────────────────────────────────────────

    def refresh_spark_tables(self):
        """Refresh all three spark-rail widgets."""
        self._refresh_spark_weeks()
        self._refresh_spark_days()
        self._refresh_spark_catchup()

    def _refresh_spark_weeks(self):
        """Populate the Past 3 Weeks DataTable in the spark rail."""
        cache = self._data_cache
        table = self.query_one("#spark-weeks-table", DataTable)
        table.clear(columns=False)

        current_sunday = get_sunday_of_week(date.today())
        weeks_data = []

        for i in range(3, 0, -1):
            pw_sunday = current_sunday - timedelta(days=7 * i)
            pw = get_week_str(pw_sunday)
            pw_num = pw.split("W")[1]
            pw_label = f"W{int(pw_num)}"

            pw_data = cache.get_week_projects(pw)
            if pw_data:
                pw_results = calculate(pw_data)
                pw_earned = sum(r[3] for r in pw_results if r[3] is not None and r[3] > 0)
                pw_tracked_neg = sum(abs(r[3]) for r in pw_results if r[3] is not None and r[3] < 0)
            else:
                pw_earned = 0.0
                pw_tracked_neg = 0.0

            pw_tracked, pw_logged = cache.get_week_neg_breakdown(pw)
            pw_logged_pos = cache.get_week_pos_breakdown(pw)
            pw_net = round(pw_earned - pw_tracked_neg - pw_logged + pw_logged_pos, 1)
            weeks_data.append((pw_label, pw, pw_net, pw_tracked, pw_logged))

        max_abs = max((abs(w[2]) for w in weeks_data), default=1) or 1

        for label, wk, net, tracked, logged in weeks_data:
            net_cell = _spark_net_rich(net, max_abs,
                                       blame_tracked=tracked, blame_logged=logged)
            table.add_row(label, net_cell, key=wk)

        table.border_title = "[b][#63f3ff]Past 3 Weeks[/][/]"

    def _refresh_spark_days(self):
        """Populate the This Week DataTable in the spark rail."""
        cache = self._data_cache
        table = self.query_one("#spark-days-table", DataTable)
        table.clear(columns=False)

        week_str = get_current_week()
        start_d, _ = get_week_dates(week_str)

        # Compute per-day net values for scaling (using cached data)
        day_entries = []
        for i in range(7):
            d = start_d + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            projs = cache.daily_data.get(d_str, {})
            neg_entries = cache.negatives_raw.get(d_str, [])
            pos_entries = cache.positives_raw.get(d_str, [])
            neg_cost = sum(e["points"] for e in neg_entries)
            pos_bonus = sum(e["points"] for e in pos_entries)
            results = calculate(projs)
            earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
            tracked_neg = sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0)
            net = round(earned - tracked_neg - neg_cost + pos_bonus, 1)
            has_data = bool(projs or neg_entries or pos_entries)
            logged_neg = round(neg_cost, 1)
            day_entries.append((d, d_str, net, has_data, tracked_neg, logged_neg))

        max_abs = max(
            (abs(net) for _, _, net, has, _, _ in day_entries if has and abs(net) >= 0.05),
            default=1,
        ) or 1

        cursor_row = None
        for i, (d, d_str, net, has_data, tracked_neg, logged_neg) in enumerate(day_entries):
            # Skip future days with no data
            if not has_data and d > date.today():
                continue

            day_name = d.strftime("%a")
            is_today = d == date.today()

            # Style the day label to match left-side week-table conventions
            if is_today:
                label_cell = f"[bold #e2b714]{day_name} ◀[/]"
            elif not has_data:
                label_cell = f"[dim]{day_name}[/]"
            else:
                label_cell = day_name

            net_cell = _spark_net_rich(
                net if has_data else None,
                max_abs,
                dim_zero=(not has_data),
                blame_tracked=tracked_neg if has_data and net < 0 else 0,
                blame_logged=logged_neg if has_data and net < 0 else 0,
            )

            table.add_row(label_cell, net_cell, key=d_str)

            if d_str == self.selected_day:
                cursor_row = table.row_count - 1

        # Restore cursor to the currently-selected day
        if cursor_row is not None:
            table.move_cursor(row=cursor_row)

        tw_num = week_str.split("W")[1]
        tw_label = f"W{int(tw_num)}"

        # Show logged neg/pos totals in the border subtitle
        tw_logged_neg = round(sum(e["points"] for entries in cache.negatives_raw.values() for e in entries), 1)
        tw_logged_pos = round(sum(e["points"] for entries in cache.positives_raw.values() for e in entries), 1)
        neg_s = f"[#ff5f5f]-{int(tw_logged_neg) if tw_logged_neg == int(tw_logged_neg) else tw_logged_neg}l[/]" if tw_logged_neg > 0 else "[dim]-0l[/]"
        pos_s = f"[#37d994]+{int(tw_logged_pos) if tw_logged_pos == int(tw_logged_pos) else tw_logged_pos}l[/]" if tw_logged_pos > 0 else "[dim]+0l[/]"

        table.border_title = f"[b][#63f3ff]This Week ({tw_label})[/][/]"
        table.border_subtitle = f"{pos_s} {neg_s}"

    def _refresh_spark_catchup(self):
        """Update the lifetime on-track / catch-up Static in the spark rail."""
        cache = self._data_cache
        all_time_data = cache.get_all_time_projects()
        if all_time_data:
            all_results = calculate(all_time_data)
            all_earned = sum(r[3] for r in all_results if r[3] is not None)
        else:
            all_earned = 0.0
        all_negatives = cache.get_negatives_for_context("ALL_TIME", "ALL")
        all_positives = cache.get_positives_for_context("ALL_TIME", "ALL")
        all_neg_pts = sum(r[3] for r in all_negatives)
        all_pos_pts = sum(r[3] for r in all_positives)
        lifetime_pts = round(all_earned + all_neg_pts + all_pos_pts, 1)

        catchup = self.query_one("#spark-catchup", Static)

        if lifetime_pts >= 0:
            pts_val = int(lifetime_pts) if lifetime_pts == int(lifetime_pts) else lifetime_pts
            text = Text()
            text.append(f"+{pts_val} pts", style="bold #37d994")
            catchup.update(text)
            catchup.border_title = "[b][#37d994]On Track[/][/]"
        else:
            deficit = abs(lifetime_pts)
            tl_raw = time_left_in_week()
            deficit_val = int(deficit) if deficit == int(deficit) else deficit

            # Rate group rows: ×rate hours task-names
            group_colors_rich = ["#63f3ff", "#ff5fff", "#37d994", "#5fafff", "#e2b714"]
            rate_groups: dict[float, list[str]] = {}
            for task_name, rate in POINTS.items():
                if rate >= 1:
                    rate_groups.setdefault(rate, []).append(task_name)
            rates_sorted = sorted(rate_groups.keys(), reverse=True)

            text = Text()
            for i, rate in enumerate(rates_sorted):
                tasks = rate_groups[rate]
                hours_needed = deficit / rate
                h = int(hours_needed)
                m = int((hours_needed - h) * 60)
                h_str = f"{h}h {m:02d}m"
                rate_str = f"×{int(rate) if rate == int(rate) else rate}"
                short: list[str] = [TASK_SHORT_NAMES.get(t) or t for t in tasks]
                task_str = " ".join(short)
                color = group_colors_rich[i % len(group_colors_rich)]

                if i > 0:
                    text.append("\n")
                text.append(f" {rate_str:<3}", style="dim")
                text.append(f"{h_str}", style="#e2b714")
                text.append(f" {task_str}", style=color)

            catchup.update(text)
            catchup.border_title = f"[b][#ff5f5f]Catch Up[/][/] [#ff5f5f]{deficit_val} pts[/]"
            catchup.border_subtitle = f"[#63f3ff]in {tl_raw}[/]"

    def refresh_week_view(self):
        cache = self._data_cache
        week = get_current_week()
        dashboard = cache.get_week_dashboard_rows(week)
        report = cache.get_report_sections(week, "WEEK")
        table = self.query_one("#week-table", DataTable)
        table.clear(columns=False)
        week_rows = []
        for row in dashboard["rows"]:
            neg_text = "—" if row["negative_total"] == 0 else f"[#ff5f5f]-{row['negative_total']:.1f}[/]"
            pos_text = "—" if row["logged_positive"] == 0 else f"[#37d994]+{row['logged_positive']:.1f}[/]"
            hour_text = "—" if row["hours"] == 0 else f"{row['hours']:.1f}h"
            earned_text = "—" if row["hours"] == 0 and row["earned"] == 0 else format_signed_rich(row["earned"])
            week_rows.append((
                row["day"],
                row["date_short"],
                hour_text,
                earned_text,
                pos_text,
                neg_text,
                format_signed_rich(row["net"]),
                row["date"],
            ))
        for cells in week_rows:
            key = cells[7]
            table.add_row(*cells[:7], key=key)
        if dashboard["rows"]:
            default_date = self.selected_day if any(r["date"] == self.selected_day for r in dashboard["rows"]) else dashboard["rows"][0]["date"]
            self.selected_day = default_date
            row_index = next(i for i, row in enumerate(dashboard["rows"]) if row["date"] == default_date)
            table.move_cursor(row=row_index, column=0)
        category_table = self.query_one("#week-category-table", DataTable)
        category_table.clear(columns=False)
        cat_rows = []
        for section_name in ("positive", "negative", "unscored"):
            rows = report[section_name]
            if rows:
                cat_rows.append((f"[{section_name.upper()}]", "", "", ""))
            for name, hours, rate, pts in rows:
                cat_rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if report["positive_results"]:
            cat_rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in report["positive_results"]:
                cat_rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if report["negative_results"]:
            cat_rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in report["negative_results"]:
                cat_rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        category_table.add_rows(cat_rows)
        summary = dashboard["summary"]
        week_hours = sum(r["hours"] for r in dashboard["rows"])
        wh_h = int(week_hours)
        wh_m = int((week_hours - wh_h) * 60)
        table.border_title = f"[b][#63f3ff]Week ({week})[/][/]   [#8d98a7]Tracked: {wh_h}hrs {wh_m:02d}min[/]"
        table.border_subtitle = f"[#8d98a7]Week net: {format_signed_rich(summary['actual'])} pts[/]"
        category_table.border_title = "[b][#63f3ff]Category Totals[/][/]"

    def refresh_overview_view(self):
        cache = self._data_cache
        report = cache.get_report_sections("ALL_TIME", "ALL")
        current_week = get_current_week()
        week_total = cache.get_report_sections(current_week, "WEEK")["total_points"]
        table = self.query_one("#overview-table", DataTable)
        table.clear(columns=False)
        rows = []
        for section_name in ("positive", "negative", "unscored"):
            section_rows = report[section_name]
            if section_rows:
                rows.append((f"[{section_name.upper()}]", "", "", ""))
            for name, hours, rate, pts in section_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if report["positive_results"]:
            rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in report["positive_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if report["negative_results"]:
            rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in report["negative_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        table.add_rows(rows)
        total_hours = report["total_hours"]
        th_h = int(total_hours)
        th_m = int((total_hours - th_h) * 60)
        table.border_title = f"[b][#63f3ff]Overview[/][/]   [#8d98a7]Total Time: {th_h}hrs {th_m:02d}min[/]"
        table.border_subtitle = (
            f"[#8d98a7]Lifetime total {format_signed_rich(report['total_points'])} pts[/]"
        )

    def refresh_day_view(self):
        cache = self._data_cache
        metrics = cache.get_day_metrics(self.selected_day)
        table = self.query_one("#day-table", DataTable)
        table.clear(columns=False)
        pos_rows = [r for r in metrics["results"] if r[3] is not None and r[3] >= 0]
        neg_rows = [r for r in metrics["results"] if r[3] is not None and r[3] < 0]
        unscored_rows = [r for r in metrics["results"] if r[3] is None]

        rows = []
        if pos_rows:
            rows.append(("[POSITIVE]", "", "", ""))
            for name, hours, rate, pts in pos_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if neg_rows:
            rows.append(("[NEGATIVE]", "", "", ""))
            for name, hours, rate, pts in neg_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if metrics["positive_results"]:
            rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in metrics["positive_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if metrics["negative_results"]:
            rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in metrics["negative_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if unscored_rows:
            rows.append(("[UNSCORED]", "", "", ""))
            for name, hours, rate, pts in unscored_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        table.add_rows(rows)
        dh = int(metrics['total_hours'])
        dm = int((metrics['total_hours'] - dh) * 60)
        table.border_title = f"[b][#63f3ff]Day ({self.selected_day})[/][/]   [#8d98a7]Tracked: {dh}hrs {dm:02d}min[/]"
        table.border_subtitle = (
            f"[#8d98a7]Pos [#37d994]+{metrics['logged_positive']:.1f}[/]   "
            f"Negs [#ff5f5f]-{metrics['logged_negative']:.1f}[/]   Net {format_signed_rich(metrics['net'])}[/]"
        )

    def refresh_negatives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#negatives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows([(name, fmt_pts_rich(-points)) for name, points in get_negative_catalog_rows()])
        recent = self.query_one("#negatives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_negative_log_rows()
        recent.add_rows([(row["date"], row["name"], fmt_pts_rich(-row["points"])) for row in recent_rows])
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press n to log. Visible penalties: [#ff5f5f]-{total_recent:.0f}[/] pts[/]"

    def refresh_positives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#positives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows([(name, fmt_pts_rich(points)) for name, points in get_positive_catalog_rows()])
        recent = self.query_one("#positives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_positive_log_rows()
        recent.add_rows([(row["date"], row["name"], fmt_pts_rich(row["points"])) for row in recent_rows])
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press p to log. Visible positives: [#37d994]+{total_recent:.0f}[/] pts[/]"

    def refresh_recovery_view(self):
        cache = self._data_cache
        data = cache.get_recovery_rows("ALL_TIME", "ALL")
        table = self.query_one("#recovery-table", DataTable)
        table.clear(columns=False)
        rows = []
        for row in data["rows"]:
            rate = row["rate"]
            color = "[#37d994]" if rate >= 2 else ("[#63f3ff]" if rate >= 1 else "[#d7dde8]")
            rows.append((f"{color}{row['category']}[/]", f"{color}{fmt_rate(rate)}[/]", f"{color}{row['hours_needed']}[/]"))
        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Recovery[/][/]"
        table.border_subtitle = (
            "[#8d98a7]Already non-negative.[/]"
            if not data["rows"]
            else f"[#8d98a7]Current total {format_signed_rich(data['total_points'])} pts[/]"
        )

    def refresh_sync_view(self):
        status = get_sync_status_data()
        table = self.query_one("#sync-table", DataTable)
        table.clear(columns=False)
        cache_age = status["projects_cache_age_days"]
        remaining = status["quota_remaining"] if status["quota_remaining"] is not None else "Unknown"
        limit = status["quota_limit"] if status["quota_limit"] is not None else "Unknown"
        rows = [
            ("Current week", status["current_week"]),
            ("Last updated", status["last_updated"]),
            ("Projects cache", "missing" if cache_age is None else f"{cache_age:.1f} days old"),
            ("Synced weeks", str(len(status["synced_weeks"]))),
            ("Synced days", str(len(status["synced_days"]))),
            ("Requests made", str(API_RUN_STATS["requests_made"])),
            ("Quota remaining", f"{remaining}/{limit}"),
        ]
        if status["quota_resets_in"] is not None:
            rows.append(("Quota resets in", _format_reset_window(status["quota_resets_in"])))
        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Sync Status[/][/]"
        table.border_subtitle = "[#8d98a7]u syncs current week. U refreshes projects and syncs 4 weeks.[/]"

    # ──────────────────────────────────────────────
    # EVENT HANDLERS
    # ──────────────────────────────────────────────

    @on(DataTable.RowHighlighted, "#week-table")
    def update_selected_day(self, event: DataTable.RowHighlighted):
        if self._is_syncing_cursors:
            return
        if event.row_key is not None:
            self.selected_day = str(event.row_key.value)
            self.refresh_day_view()
            # Keep spark-days-table cursor in sync
            self._sync_spark_days_cursor()

    @on(DataTable.RowHighlighted, "#spark-days-table")
    def spark_day_highlighted(self, event: DataTable.RowHighlighted):
        """Clicking / navigating a day row in the spark panel updates the
        selected day exactly as navigating the week-table does."""
        if self._is_syncing_cursors:
            return
        if event.row_key is not None:
            self.selected_day = str(event.row_key.value)
            self.refresh_day_view()
            # Keep week-table cursor in sync when spark panel drives selection
            self._sync_week_table_cursor()

    def _sync_spark_days_cursor(self):
        """Move the spark-days-table cursor to match self.selected_day."""
        self._is_syncing_cursors = True
        try:
            table = self.query_one("#spark-days-table", DataTable)
            for i in range(table.row_count):
                try:
                    key = list(table.rows.keys())[i]
                    if str(key.value) == self.selected_day:
                        table.move_cursor(row=i, animate=False)
                        break
                except (IndexError, AttributeError):
                    pass
        finally:
            self._is_syncing_cursors = False

    def _sync_week_table_cursor(self):
        """Move the week-table cursor to match self.selected_day."""
        self._is_syncing_cursors = True
        try:
            table = self.query_one("#week-table", DataTable)
            try:
                keys = list(table.rows.keys())
                for i, key in enumerate(keys):
                    if str(key.value) == self.selected_day:
                        table.move_cursor(row=i, animate=False)
                        break
            except (IndexError, AttributeError):
                pass
        finally:
            self._is_syncing_cursors = False

    @on(Click, ".view-tab")
    def click_view_tab(self, event: Click):
        if event.widget.id and event.widget.id.startswith("view-tab-"):
            self.active_view_index = int(event.widget.id.rsplit("-", 1)[1])
            self._refresh_view_by_index(self.active_view_index)
            self.update_tabs()
            self.update_view_visibility()
            self.focus_active_view()

    def action_next_view(self):
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.focus_active_view()

    def action_prev_view(self):
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.focus_active_view()

    def action_refresh_data(self):
        load_runtime_settings()
        self.refresh_all_views()
        self.notify("Reloaded local data")

    def action_toggle_sparkbar(self):
        if self.size.width < 120:
            self.sparkbar_forced_open = not self.sparkbar_forced_open
            self.sparkbar_collapsed = False
        else:
            self.sparkbar_collapsed = not self.sparkbar_collapsed
            self.sparkbar_forced_open = False
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def action_show_help(self):
        self.notify("Left/right switch views, n add negative, u sync, U full sync, s toggle sparkbar, q quit")

    def action_sync_current_week(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Syncing current week...")
                self._do_sync_current_week()

        self.push_screen(ConfirmScreen("Sync current week", "Run a current-week sync now?"), after_confirm)

    @work(thread=True)
    def _do_sync_current_week(self):
        try:
            result = sync_current_week_light(prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_sync_done, ok, message, "Synced current week")

    def action_sync_full(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Syncing last 4 weeks...")
                self._do_sync_full()

        self.push_screen(ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"), after_confirm)

    @work(thread=True)
    def _do_sync_full(self):
        try:
            result = sync_api_to_csv(4, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_sync_done, ok, message, "Synced last 4 weeks")

    def _on_sync_done(self, ok, message, success_msg):
        load_runtime_settings()
        reset_cache()
        self.refresh_all_views()
        if ok:
            self.notify(success_msg)
        else:
            self.notify(message or "Sync skipped", severity="warning")

    def action_add_negative(self):
        def after_input(value):
            if value:
                ok, message = log_negative_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(NegativeInputScreen(), after_input)

    def action_add_positive(self):
        def after_input(value):
            if value:
                ok, message = log_positive_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(PositiveInputScreen(), after_input)

    def on_resize(self, event) -> None:
        new_size = event.size
        if new_size.width == 0 or new_size.height == 0:
            return
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def _resize_tables(self):
        self.update_sparkbar_visibility()

        # ── Main content tables ────────────────────────────────────────────
        table_ids = [
            "#week-table", "#week-category-table", "#overview-table",
            "#day-table", "#negatives-catalog-table", "#negatives-log-table",
            "#positives-catalog-table", "#positives-log-table", "#recovery-table",
            "#sync-table"
        ]
        text_cols = {"Category", "Negative", "Positive", "Metric", "Value", "Cate"}

        rail = self.query_one("#spark-rail")
        rail_w = 34 if not rail.has_class("-hidden") else 0
        content_w = self.size.width - rail_w

        if content_w <= 0:
            return

        available_width = max(10, content_w - 2)

        for t_id in table_ids:
            try:
                table = self.query_one(t_id, DataTable)
            except Exception:
                continue

            if not table.columns:
                continue

            # Skip tables in hidden views to avoid forced reflows
            if not table.display:
                continue

            col_keys = list(table.columns.keys())
            n_cols = len(col_keys)
            cell_padding = table.cell_padding

            req_widths = {key: len(col.label.plain) for key, col in table.columns.items()}

            for row_idx in range(table.row_count):
                row_data = table.get_row_at(row_idx)
                for col_idx, col_key in enumerate(col_keys):
                    val = str(row_data[col_idx])
                    cell_w = len(strip_ansi(val))
                    if cell_w > req_widths[col_key]:
                        req_widths[col_key] = cell_w

            total_padding = 2 * cell_padding * n_cols
            content_budget = available_width - total_padding
            total_req_content = sum(req_widths.values())

            expandable_keys = []
            fixed_keys = []
            for key, col in table.columns.items():
                label_str = col.label.plain
                if label_str in text_cols or label_str.startswith("Cat"):
                    expandable_keys.append(key)
                else:
                    fixed_keys.append(key)

            if not expandable_keys:
                expandable_keys = list(table.columns.keys())
                fixed_keys = []

            if content_budget >= total_req_content:
                extra = content_budget - total_req_content
                for key in fixed_keys:
                    table.columns[key].width = req_widths[key]
                    table.columns[key].auto_width = False
                expand_extra = extra // len(expandable_keys)
                rem = extra % len(expandable_keys)
                for i, key in enumerate(expandable_keys):
                    table.columns[key].width = req_widths[key] + expand_extra + (1 if i < rem else 0)
                    table.columns[key].auto_width = False
            else:
                min_widths = {key: max(3, len(col.label.plain))
                              for key, col in table.columns.items()}
                total_min = sum(min_widths.values())

                if content_budget <= total_min:
                    base_w = content_budget // n_cols
                    rem = content_budget % n_cols
                    for i, key in enumerate(table.columns.keys()):
                        table.columns[key].width = max(1, base_w + (1 if i < rem else 0))
                        table.columns[key].auto_width = False
                else:
                    remaining = content_budget
                    widths = dict(min_widths)
                    remaining -= total_min

                    for key in fixed_keys:
                        extra = min(req_widths[key] - min_widths[key], remaining)
                        if extra > 0:
                            widths[key] += extra
                            remaining -= extra

                    if remaining > 0 and expandable_keys:
                        expand_extra = remaining // len(expandable_keys)
                        rem = remaining % len(expandable_keys)
                        for i, key in enumerate(expandable_keys):
                            widths[key] += expand_extra + (1 if i < rem else 0)

                    for key, w in widths.items():
                        table.columns[key].width = w
                        table.columns[key].auto_width = False

            table.refresh(layout=True)
            table.scroll_to(x=0, animate=False)

        # ── Spark rail tables (fixed 34-char rail) ─────────────────────────
        SPARK_RAIL_W = 34
        for t_id in ("#spark-weeks-table", "#spark-days-table"):
            try:
                table = self.query_one(t_id, DataTable)
            except Exception:
                continue
            if not table.columns:
                continue
            if not table.display:
                continue

            col_keys = list(table.columns.keys())
            cell_padding = table.cell_padding
            inner_w = SPARK_RAIL_W - 2
            total_padding = 2 * cell_padding * len(col_keys)
            content_budget = max(8, inner_w - total_padding)

            label_w = 6
            net_w = max(4, content_budget - label_w)

            for i, key in enumerate(col_keys):
                table.columns[key].width = label_w if i == 0 else net_w
                table.columns[key].auto_width = False

            table.refresh(layout=True)
            table.scroll_to(x=0, animate=False)


def fmt_rate(rate):
    if rate is None:
        return "—"
    r = int(rate) if rate == int(rate) else rate
    return f"×{r}"


def fmt_pts(pts):
    if pts is None:
        return "—"
    if pts == 0:
        return "0.0"
    return f"+{pts}" if pts > 0 else str(pts)


def format_signed_rich(value):
    if abs(value) < 0.05:
        value = 0.0
    if value > 0:
        return f"[#37d994]+{value:.1f}[/]"
    elif value < 0:
        return f"[#ff5f5f]{value:.1f}[/]"
    return "0.0"


def fmt_pts_rich(pts):
    if pts is None:
        return "—"
    if pts == 0:
        return "0.0"
    if pts > 0:
        return f"[#37d994]+{pts:.1f}[/]"
    return f"[#ff5f5f]{pts:.1f}[/]"


# ──────────────────────────────────────────────
# WEEKLY DAILY BREAKDOWN
# ──────────────────────────────────────────────

def print_neg_catalog():
    print(f"\n  {BOLD}{RED}NEGATIVES CATALOG{RESET}")
    print("  " + "─" * 35)
    for name, points in get_negative_catalog_rows():
        print(f"  {name:<25} {RED}-{points:>4.1f}{RESET}")
    print()

def print_pos_catalog():
    print(f"\n  {BOLD}{GREEN}POSITIVES CATALOG{RESET}")
    print("  " + "─" * 35)
    for name, points in get_positive_catalog_rows():
        print(f"  {name:<25} {GREEN}+{points:>4.1f}{RESET}")
    print()

def _parse_day_arg(arg):
    if not arg: return None
    arg = arg.lower()
    if arg == "today": return date.today().strftime("%Y-%m-%d")
    if arg == "yesterday": return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    days = {"sun":0, "mon":1, "tue":2, "wed":3, "thu":4, "fri":5, "sat":6}
    if arg in days:
        target_weekday = days[arg]
        today_weekday = (date.today().weekday() + 1) % 7 # sun=0
        diff = (today_weekday - target_weekday) % 7
        return (date.today() - timedelta(days=diff)).strftime("%Y-%m-%d")
    return arg

def print_weekly_dashboard(label):
    start_d, end_d = get_week_dates(label)
    cache = get_cache()
    print(f"\n  {BOLD}{CYAN}DAILY BREAKDOWN{RESET} {DIM}({label}){RESET}")
    table_width = 85
    print("  " + "─" * table_width)
    print(
        f"  {BOLD}{'Day':<10} {'Date':<8} {'Hours':>8} {'Earned':>9} {'Pos':>8} {'Negs':>8} {'Goal':>8} {'Δ':>8} {'Net':>8}{RESET}"
    )
    print("  " + "─" * table_width)
    has_data = False
    cumulative_net = 0.0
    cumulative_days = 0
    cutoff = min(end_d, date.today()) if label == get_current_week() else end_d
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        day_name = d.strftime("%A")[:3]
        date_short = d.strftime("%d %b")
        projs = cache.daily_data.get(d_str, {})
        neg_entries = cache.negatives_raw.get(d_str, [])
        pos_entries = cache.positives_raw.get(d_str, [])
        if not projs and not neg_entries and not pos_entries and d > date.today():
            continue
        has_data = True
        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
        tracked_neg = sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0)
        hours = sum(projs.values())
        neg_cost = sum(e["points"] for e in neg_entries)
        pos_bonus = sum(e["points"] for e in pos_entries)
        net = earned - tracked_neg - neg_cost + pos_bonus
        h_str = f"{hours:.1f}h" if hours > 0 else "—"
        e_str = (
            f"+{earned:.1f}"
            if earned > 0
            else (f"{earned:.1f}" if earned < 0 else "0.0")
        )
        if earned == 0 and hours == 0:
            e_str = "—"
        p_str = f"+{pos_bonus:.1f}" if pos_bonus > 0 else "—"
        p_styled = f"{GREEN}{p_str:>8}{RESET}" if pos_bonus > 0 else f"{p_str:>8}"
        n_str = f"-{neg_cost:.1f}" if neg_cost > 0 else "—"
        n_styled = f"{MAGENTA}{n_str:>8}{RESET}" if neg_cost > 0 else f"{n_str:>8}"
        goal_str = f"{DAILY_TARGET:.1f}"
        delta = net - DAILY_TARGET
        delta_raw = (
            f"+{delta:.1f}" if delta > 0 else (f"{delta:.1f}" if delta < 0 else "0.0")
        )
        delta_col = GREEN if delta > 0 else (RED if delta < 0 else DIM)
        styled_delta = f"{delta_col}{delta_raw}{RESET}"
        delta_pad = len(styled_delta) - len(delta_raw)
        raw_net = f"+{net:.1f}" if net > 0 else (f"{net:.1f}" if net < 0 else "0.0")
        net_col = GREEN if net > 0 else (RED if net < 0 else DIM)
        if d <= cutoff:
            cumulative_net += net
            cumulative_days += 1
        if earned == 0 and hours == 0 and neg_cost == 0 and pos_bonus == 0:
            print(
                f"  {DIM}{day_name:<10} {date_short:<8} {h_str:>8} {e_str:>9} {p_str:>8} {n_str:>8} {goal_str:>8} {delta_raw:>8} {'—':>8}{RESET}"
            )
        else:
            styled_net = f"{net_col}{raw_net}{RESET}"
            net_pad = len(styled_net) - len(raw_net)
            print(
                f"  {day_name:<10} {date_short:<8} {h_str:>8} {e_str:>9} {p_styled} {n_styled} {goal_str:>8} {styled_delta:>{8 + delta_pad}} {styled_net:>{8 + net_pad}}"
            )
    print("  " + "─" * table_width)
    if cumulative_days > 0:
        expected = DAILY_TARGET * cumulative_days
        total_delta = cumulative_net - expected
        scope = "through today" if label == get_current_week() else "for week"
        delta_raw = (
            f"+{total_delta:.1f}"
            if total_delta > 0
            else (f"{total_delta:.1f}" if total_delta < 0 else "0.0")
        )
        delta_col = GREEN if total_delta > 0 else (RED if total_delta < 0 else DIM)
        print(
            f"  {DIM}Target {scope}:{RESET} {expected:.1f} pts  {DIM}Actual:{RESET} {cumulative_net:.1f} pts  {DIM}Δ:{RESET} {delta_col}{delta_raw}{RESET}"
        )
    if not has_data and label != get_current_week():
        print(f"  {DIM}Daily breakdown is only available for the current week.{RESET}")
    print()


# ──────────────────────────────────────────────
# SPARKBAR HELPERS (used by CLI print_report)
# ──────────────────────────────────────────────

def get_week_pos_breakdown(week_str):
    return get_cache().get_week_pos_breakdown(week_str)

def get_week_neg_breakdown(week_str):
    return get_cache().get_week_neg_breakdown(week_str)


def build_blame_bar(tracked, logged, n=BLAME_W):
    total = tracked + logged
    if total == 0:
        return " " * n
    red_count = round(tracked / total * n)
    mag_count = n - red_count
    return f"{RED}{'█' * red_count}{RESET}{MAGENTA}{'█' * mag_count}{RESET}"


def time_left_in_week():
    now = datetime.now()
    current_sunday = get_sunday_of_week(date.today())
    end_of_sat = datetime.combine(
        current_sunday + timedelta(days=6), datetime.max.time()
    )
    diff = end_of_sat - now
    if diff.total_seconds() <= 0:
        return "0h"
    total_secs = int(diff.total_seconds())
    days = total_secs // 86400
    hours = (total_secs % 86400) // 3600
    return f"{days}d {hours:02d}h" if days > 0 else f"{hours}h"


# ──────────────────────────────────────────────
# SPARKBAR (CLI only — TUI uses DataTables above)
# ──────────────────────────────────────────────
def build_week_sparkbar_lines(week_str=None):
    week_str = week_str or get_current_week()
    start_d, _ = get_week_dates(week_str)
    cache = get_cache()

    day_data = []
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        projs = cache.daily_data.get(d_str, {})
        neg_entries = cache.negatives_raw.get(d_str, [])
        pos_entries = cache.positives_raw.get(d_str, {})

        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
        logged_neg = sum(e["points"] for e in neg_entries)
        logged_pos = sum(e["points"] for e in pos_entries)
        tracked_neg = sum(
            abs(r[3]) for r in results if r[3] is not None and r[3] < 0
        )
        net = round(earned - tracked_neg - logged_neg + logged_pos, 1)
        if abs(net) < 0.05:
            net = 0.0

        day_data.append(
            {
                "name": d.strftime("%a"),
                "net": net,
                "tracked_neg": round(tracked_neg, 1),
                "logged_neg": round(logged_neg, 1),
                "logged_pos": round(logged_pos, 1),
                "is_today": d == date.today(),
                "future": d > date.today(),
                "has_data": bool(projs or neg_entries or pos_entries),
            }
        )

    nonzero = [abs(dd["net"]) for dd in day_data if dd["has_data"] and dd["net"] != 0]
    max_abs = max(nonzero, default=1)

    lines: list[str] = []

    BOX_W = SPARK_W + 2
    title_p4w = f" Past 4 Weeks "
    title_p4w_vis = len(title_p4w)
    top_border_p4w = "┌" + f"{BOLD}{CYAN}{title_p4w}{RESET}" + "─" * (BOX_W - title_p4w_vis - 2) + "┐"
    lines.append(top_border_p4w)

    current_sunday = get_sunday_of_week(date.today())

    past_weeks_data = []
    max_abs_pw = 0.1

    for i in range(3, 0, -1):
        pw_sunday = current_sunday - timedelta(days=7 * i)
        pw = get_week_str(pw_sunday)
        pw_num = pw.split("W")[1]
        pw_label = f"W{int(pw_num)}"

        pw_data = get_data_for_week(pw)
        if pw_data:
            pw_results = calculate(pw_data)
            pw_earned = sum(r[3] for r in pw_results if r[3] is not None and r[3] > 0)
            pw_tracked_neg = sum(abs(r[3]) for r in pw_results if r[3] is not None and r[3] < 0)
        else:
            pw_earned = 0.0
            pw_tracked_neg = 0.0

        pw_tracked, pw_logged = get_week_neg_breakdown(pw)
        pw_logged_pos = get_week_pos_breakdown(pw)
        pw_net = round(pw_earned - pw_tracked_neg - pw_logged + pw_logged_pos, 1)

        max_abs_pw = max(max_abs_pw, abs(pw_net))
        past_weeks_data.append(
            {
                "label": pw_label,
                "net": pw_net,
                "tracked_neg": pw_tracked,
                "logged_neg": pw_logged,
            }
        )

    SIDE_W = SPARK_PTS_W + 1 + SPARK_BAR_W
    TOTAL_LEFT_MARGIN = 2

    for pwd in past_weeks_data:
        net = pwd["net"]
        label_base = f"{pwd['label']:<3}"

        bar_len = max(1, round(abs(net) / max_abs_pw * SPARK_BAR_W)) if net != 0 else 0
        bar_str = "█" * bar_len

        blame_str: str = ""
        blame_vis_len: int = 0

        if (pwd["tracked_neg"] + pwd["logged_neg"]) > 0 and net < 0:
            blame_str = build_blame_bar(pwd["tracked_neg"], pwd["logged_neg"])
            blame_vis_len = len(strip_ansi(blame_str))

        if net < 0:
            pts_s = str(net)
            label_str = f"{RED}{label_base}{RESET}"

            spacing = " " if blame_str else ""
            content_vis_len = len(pts_s) + len(spacing) + blame_vis_len

            total_left_space = TOTAL_LEFT_MARGIN + SIDE_W
            pad_len = max(0, total_left_space - content_vis_len)

            left_side_str = " " * pad_len + f"{RED}{pts_s}{RESET}{spacing}{blame_str}"
            pos_part = " " * SIDE_W

            line = f"│{pad_ansi(f'{left_side_str} {label_str} {pos_part}', SPARK_W)}│"

        elif net > 0:
            pts_s = f"+{net}"
            label_str = label_base

            neg_pad = max(0, SIDE_W - blame_vis_len)
            neg_part = " " * neg_pad + blame_str
            left_side_str = " " * TOTAL_LEFT_MARGIN + neg_part

            spacing = " " if bar_str else ""
            content_len = bar_len + len(spacing) + len(pts_s)
            pad_len = max(0, SIDE_W - content_len)

            pos_part = (
                f"{GREEN}{bar_str}{RESET}{spacing}{GREEN}{pts_s}{RESET}" + " " * pad_len
            )

            line = f"│{pad_ansi(f'{left_side_str} {label_str} {pos_part}', SPARK_W)}│"

        else:
            pts_s = "0.0"
            label_str = label_base

            neg_pad = max(0, SIDE_W - blame_vis_len)
            neg_part = " " * neg_pad + blame_str
            left_side_str = " " * TOTAL_LEFT_MARGIN + neg_part

            content_len = len(pts_s)
            pad_len = max(0, SIDE_W - content_len)
            pos_part = f"   {DIM}{pts_s}{RESET}" + " " * pad_len

            line = f"│{pad_ansi(f'{left_side_str} {label_str} {pos_part}', SPARK_W)}│"

        lines.append(line)

    lines.append("└" + "─" * (BOX_W - 2) + "┘")

    tw_logged_neg = round(sum(dd["logged_neg"] for dd in day_data), 1)
    tw_logged_pos = round(sum(dd["logged_pos"] for dd in day_data), 1)
    
    neg_val = int(tw_logged_neg) if tw_logged_neg == int(tw_logged_neg) else tw_logged_neg
    pos_val = int(tw_logged_pos) if tw_logged_pos == int(tw_logged_pos) else tw_logged_pos
    neg_l_str = f"{MAGENTA}-{neg_val}l{RESET}" if tw_logged_neg > 0 else f"{DIM}-0l{RESET}"
    pos_l_str = f"{GREEN}+{pos_val}l{RESET}" if tw_logged_pos > 0 else f"{DIM}+0l{RESET}"

    tw_num = week_str.split("W")[1]
    tw_label = f"W{int(tw_num)}"
    title_tw = f" This Week ({tw_label}) {pos_l_str} {neg_l_str} "
    title_tw_vis = vlen(title_tw)
    top_border_tw = "┌" + f"{BOLD}{title_tw}{RESET}" + "─" * max(0, BOX_W - title_tw_vis - 2) + "┐"
    lines.append(top_border_tw)

    SIDE_W = SPARK_PTS_W + 1 + SPARK_BAR_W

    for dd in day_data:
        net = dd["net"]
        name = dd["name"]
        today_mark = f" {YELLOW}◀{RESET}" if dd["is_today"] else ""

        if dd["future"] or not dd["has_data"]:
            day_str = f"{DIM}{name}{RESET}"
        else:
            day_str = name

        if (dd["future"] or not dd["has_data"]) and net == 0:
            neg_part = " " * SIDE_W
            pos_part = " " * SIDE_W
            line = f"│{pad_ansi(f'  {neg_part} {day_str} {pos_part}{today_mark}', SPARK_W)}│"
            lines.append(line)
            continue

        bar_len = max(1, round(abs(net) / max_abs * SPARK_BAR_W)) if net != 0 else 0
        bar_str = "█" * bar_len

        has_neg = (dd["tracked_neg"] + dd["logged_neg"]) > 0 and net < 0
        blame_str_d: str = (
            build_blame_bar(dd["tracked_neg"], dd["logged_neg"]) if has_neg else ""
        )
        blame_vis_len_d: int = len(strip_ansi(blame_str_d)) if has_neg else 0

        if net < 0:
            pts_s = str(net)
            day_str = f"{RED}{name}{RESET}"

            spacing = " " if blame_str_d else ""
            content_len = len(pts_s) + len(spacing) + blame_vis_len_d
            pad_len = max(0, SIDE_W - content_len)

            neg_part = " " * pad_len + f"{RED}{pts_s}{RESET}{spacing}{blame_str_d}"
            pos_part = " " * SIDE_W

        elif net > 0:
            pts_s = f"+{net}"

            neg_pad = max(0, SIDE_W - blame_vis_len_d)
            neg_part = " " * neg_pad + blame_str_d

            spacing = " " if bar_str else ""
            content_len = bar_len + len(spacing) + len(pts_s)
            pad_len = max(0, SIDE_W - content_len)

            pos_part = (
                f"{GREEN}{bar_str}{RESET}{spacing}{GREEN}{pts_s}{RESET}" + " " * pad_len
            )

        else:
            pts_s = "0.0"
            neg_pad = max(0, SIDE_W - blame_vis_len_d)
            neg_part = " " * neg_pad + blame_str_d

            content_len = len(pts_s)
            pad_len = max(0, SIDE_W - content_len)
            pos_part = f"   {DIM}{pts_s}{RESET}" + " " * pad_len

        line = f"│{pad_ansi(f'  {neg_part} {day_str} {pos_part}{today_mark}', SPARK_W)}│"
        lines.append(line)

    lines.append("└" + "─" * (BOX_W - 2) + "┘")

    all_time_data = get_all_time_data()
    if all_time_data:
        all_results = calculate(all_time_data)
        all_earned = sum(r[3] for r in all_results if r[3] is not None)
    else:
        all_earned = 0.0
    all_negatives = get_negatives_for_context("ALL_TIME", "ALL")
    all_positives = get_positives_for_context("ALL_TIME", "ALL")
    all_neg_pts = sum(r[3] for r in all_negatives)
    all_pos_pts = sum(r[3] for r in all_positives)
    lifetime_pts = round(all_earned + all_neg_pts + all_pos_pts, 1)

    if lifetime_pts < 0:
        deficit = abs(lifetime_pts)

        tl_raw = time_left_in_week()
        t_hrs = 0
        if "d" in tl_raw:
            d_part, tl_raw = tl_raw.split("d")
            t_hrs += int(d_part.strip()) * 24
        if "h" in tl_raw:
            h_part = tl_raw.split("h")[0]
            t_hrs += int(h_part.strip())

        tl_str = f"{t_hrs}h" if t_hrs > 0 else tl_raw.strip()

        deficit_val = int(deficit) if deficit == int(deficit) else deficit
        title_cu = f" Catch Up {RED}{deficit_val} Pts{RESET} {CYAN}in {tl_str}{RESET} "
        title_cu_vis = vlen(title_cu)
        top_border_cu = "┌" + f"{BOLD}{title_cu}{RESET}" + "─" * max(0, BOX_W - title_cu_vis - 2) + "┐"
        lines.append(top_border_cu)

        available_lines = max(1, 23 - len(lines))
        RIGHT_COL_W = SPARK_W

        group_colors = ["\033[36m", "\033[35m", "\033[32m", "\033[34m", "\033[33m"]

        rate_groups: dict[float, list[str]] = {}
        for task_name, rate in POINTS.items():
            if rate >= 1:
                rate_groups.setdefault(rate, []).append(task_name)

        rates_sorted = sorted(rate_groups.keys(), reverse=True)

        for i, rate in enumerate(rates_sorted):
            tasks = rate_groups[rate]
            hours_needed = deficit / rate
            h = int(hours_needed)
            m = int((hours_needed - h) * 60)
            h_str = f"{h}h {m:02d}m"
            rate_str = f"×{int(rate) if rate == int(rate) else rate}"
            short: list[str] = [TASK_SHORT_NAMES.get(t) or t for t in tasks]

            color_ansi = group_colors[i % len(group_colors)]
            remaining_rates = len(rates_sorted) - 1 - i

            prefix_ansi = f" {DIM}{rate_str:<3}{RESET}{YELLOW}{h_str}{RESET} "
            prefix_vis_len = 1 + max(len(rate_str), 3) + len(h_str) + 1

            expanded_lines: list[str] = []
            curr_line_ansi = prefix_ansi
            curr_vis_len = prefix_vis_len
            words_on_curr_line = 0

            indent_str = "     "
            indent_vis_len = 5

            for s in short:
                word_vis_len = len(s)
                space_needed = 1 if words_on_curr_line > 0 else 0

                if (
                    curr_vis_len + space_needed + word_vis_len > RIGHT_COL_W
                    and words_on_curr_line > 0
                ):
                    expanded_lines.append(curr_line_ansi)
                    curr_line_ansi = indent_str + f"{color_ansi}{s}{RESET}"
                    curr_vis_len = indent_vis_len + word_vis_len
                    words_on_curr_line = 1
                else:
                    curr_line_ansi += (
                        " " if space_needed else ""
                    ) + f"{color_ansi}{s}{RESET}"
                    curr_vis_len += space_needed + word_vis_len
                    words_on_curr_line += 1

            if curr_line_ansi:
                expanded_lines.append(curr_line_ansi)

            if available_lines >= len(expanded_lines) + remaining_rates:
                for el in expanded_lines:
                    lines.append(f"│{pad_ansi(el, SPARK_W)}│")
                available_lines -= len(expanded_lines)
            else:
                max_task_len = max(5, RIGHT_COL_W - prefix_vis_len)
                task_str = " ".join(short)

                if len(task_str) > max_task_len:
                    h_rounded = int(hours_needed) + (
                        1 if hours_needed > int(hours_needed) else 0
                    )
                    h_str = f"{h_rounded}h"
                    prefix_vis_len = 1 + max(len(rate_str), 3) + len(h_str) + 1
                    max_task_len = max(5, RIGHT_COL_W - prefix_vis_len)

                    short_compressed: list[str] = [s[:3] for s in short]
                    task_str = " ".join(short_compressed)

                compact_prefix = f" {DIM}{rate_str:<3}{RESET}{YELLOW}{h_str}{RESET} "
                lines.append(f"│{pad_ansi(compact_prefix + f'{color_ansi}{task_str}{RESET}', SPARK_W)}│")
                available_lines -= 1

        lines.append("└" + "─" * (BOX_W - 2) + "┘")

    else:
        title_ot = f" On Track {GREEN}+{lifetime_pts} pts{RESET} "
        title_ot_vis = vlen(title_ot)
        top_border_ot = "┌" + f"{BOLD}{title_ot}{RESET}" + "─" * max(0, BOX_W - title_ot_vis - 2) + "┐"
        lines.append(top_border_ot)
        lines.append("└" + "─" * (BOX_W - 2) + "┘")

    return lines


# ──────────────────────────────────────────────
# DEFICIT RECOVERY
# ──────────────────────────────────────────────
def print_recovery_cli(results, negative_results, positive_results, label, context_type):
    total_pts = sum(r[3] for r in results if r[3] is not None)
    total_pts += sum(r[3] for r in negative_results)
    total_pts += sum(r[3] for r in positive_results)
    total_pts = round(total_pts, 2)

    if context_type == "DAY":
        scope = (
            f"today ({label})" if label == date.today().strftime("%Y-%m-%d") else label
        )
    elif context_type == "WEEK":
        scope = f"this week ({label})"
    else:
        scope = "lifetime"

    print(f"\n  {BOLD}{CYAN}DEFICIT RECOVERY{RESET}  {DIM}· {scope}{RESET}")
    print("  " + "─" * 50)

    if total_pts >= 0:
        sign = "+" if total_pts > 0 else ""
        print(f"  {GREEN}You're already at {sign}{total_pts} pts — no deficit.{RESET}")
        print()
        return

    deficit = abs(total_pts)
    print(
        f"  Current total   {RED}{BOLD}{total_pts} pts{RESET}  {DIM}(need +{deficit:.2f} to break even){RESET}\n"
    )

    pos_categories = sorted(
        [(name, rate) for name, rate in POINTS.items() if rate > 0], key=lambda x: -x[1]
    )

    col1, col2, col3 = 28, 8, 14
    print(
        f"  {BOLD}{'Category':<{col1}} {'Rate':>{col2}} {'Hours needed':>{col3}}{RESET}"
    )
    print("  " + "─" * (col1 + col2 + col3 + 2))

    prev_rate = None
    for name, rate in pos_categories:
        if prev_rate is not None and rate != prev_rate:
            print()
        hours_needed = deficit / rate
        h = int(hours_needed)
        m = int((hours_needed - h) * 60)
        h_str = f"{h}h {m:02d}m"
        rate_str = f"×{int(rate) if rate == int(rate) else rate}"
        print(f"  {name:<{col1}} {rate_str:>{col2}} {YELLOW}{h_str:>{col3}}{RESET}")
        prev_rate = rate

    print()


# ──────────────────────────────────────────────
# MAIN REPORT (with inline sparkbar)
# ──────────────────────────────────────────────
def print_report(results, negative_results, positive_results, label, context_type="ALL"):
    if context_type == "WEEK":
        print_weekly_dashboard(label)

    total_pts = sum(r[3] for r in results if r[3] is not None)
    total_pts += sum(r[3] for r in negative_results)
    total_pts += sum(r[3] for r in positive_results)
    total_pts = round(total_pts, 2)
    is_deficit = total_pts < 0

    total_hours = sum(r[1] for r in results if r[1] is not None)
    h_floor = int(total_hours)
    m_floor = int((total_hours - h_floor) * 60)
    total_str = f"{h_floor}h {m_floor:02d}m"

    colour = GREEN if total_pts >= 0 else RED
    sign = "+" if total_pts >= 0 else ""
    last_updated = get_last_updated_str()

    if context_type == "ALL":
        meta = f"  {DIM}Lifetime Total  ·  {total_str} tracked  · Updated {last_updated}{RESET}"
    elif context_type == "DAY":
        meta = f"  {DIM}Date: {label}  ·  {total_str} tracked  · Updated {last_updated}{RESET}"
    else:
        start_d, end_d = get_week_dates(label)
        date_range = f"{start_d.strftime('%d %b %Y')} – {end_d.strftime('%d %b %Y')}"
        meta = f"  {DIM}Week: {label} ({date_range})  ·  {total_str} tracked  · Updated {last_updated}{RESET}"

    lines: list[str] = []

    sep_len = COL1 + COL2 + COL3 + COL4 + 3

    lines.append(meta)

    lines.append(
        f"  {BOLD}{'Category':<{COL1}} {'Hours':>{COL2}} {'Rate':>{COL3}} {'Points':>{COL4}}{RESET}"
    )
    lines.append("  " + "─" * sep_len)

    pos_rows = [r for r in results if r[3] is not None and r[3] >= 0]
    neg_rows = [r for r in results if r[3] is not None and r[3] < 0]
    null_rows = [r for r in results if r[3] is None]

    def _row_str(name, hours, rate, pts, color):
        h_str = f"{hours:.2f}h" if hours is not None else "—"
        r_str = fmt_rate(rate) if rate is not None else "—"
        p_str = fmt_pts(pts)
        if pts is None or pts == 0:
            p_col = f"{DIM}{p_str}{RESET}"
        else:
            p_col = f"{color}{p_str}{RESET}"
        pad = COL4 + len(p_col) - len(p_str)
        return f"  {name:<{COL1}} {h_str:>{COL2}} {r_str:>{COL3}} {p_col:>{pad}}"

    if pos_rows:
        lines.append(f"  {BOLD}{DIM}POSITIVE{RESET}")
        for r in pos_rows:
            lines.append(_row_str(r[0], r[1], r[2], r[3], GREEN))

    if positive_results:
        pos_log_subtotal = round(sum(r[3] for r in positive_results), 1)
        lines.append("")
        lines.append(
            f"  {BOLD}{DIM}POSITIVES LOGGED{RESET}  "
            f"{GREEN}+{pos_log_subtotal} manually logged{RESET}"
        )
        for r in positive_results:
            lines.append(_row_str(r[0], r[1], r[2], r[3], GREEN))

    if neg_rows:
        neg_subtotal = round(sum(r[3] for r in neg_rows), 1)
        lines.append("")
        if is_deficit:
            lines.append(
                f"  {BOLD}{DIM}NEGATIVE{RESET}  "
                f"{RED}{neg_subtotal} from tracked time{RESET}"
            )
        else:
            lines.append(f"  {BOLD}{DIM}NEGATIVE{RESET}")
        for r in neg_rows:
            lines.append(_row_str(r[0], r[1], r[2], r[3], RED))

    if negative_results:
        neg_log_subtotal = round(sum(r[3] for r in negative_results), 1)
        lines.append("")
        if is_deficit:
            lines.append(
                f"  {BOLD}{DIM}NEGATIVES LOGGED{RESET}  "
                f"{MAGENTA}{neg_log_subtotal} manually logged{RESET}"
            )
        else:
            lines.append(f"  {BOLD}{DIM}NEGATIVES LOGGED{RESET}")
        for r in negative_results:
            lines.append(_row_str(r[0], r[1], r[2], r[3], MAGENTA))

    if null_rows:
        lines.append("")
        lines.append(f"  {BOLD}{DIM}UNSCORED{RESET}")
        for r in null_rows:
            lines.append(_row_str(r[0], r[1], r[2], r[3], DIM))

    lines.append("")
    lines.append("  " + "─" * sep_len)

    raw_total = f"{sign}{total_pts}"
    styled_total = f"{colour}{BOLD}{raw_total}{RESET}"
    pad_adj = len(styled_total) - len(raw_total)
    lines.append(
        f"  {'TOTAL':<{COL1}} {'':>{COL2}} {'':>{COL3}} {styled_total:>{COL4 + pad_adj}}"
    )
    lines.append("")

    spark_lines: list[str] = []
    if context_type in ("WEEK", "ALL", "DAY"):
        spark_lines = build_week_sparkbar_lines()

    for i, tline in enumerate(lines):
        si = i - SPARK_START_ROW
        if spark_lines and 0 <= si < len(spark_lines):
            tv = vlen(tline)
            pad = max(TABLE_W - tv + TABLE_SPARK_GAP, TABLE_SPARK_GAP)
            print(tline + " " * pad + spark_lines[si])
        else:
            print(tline)

    if spark_lines:
        first_remaining = len(lines) - SPARK_START_ROW
        for si in range(max(first_remaining, 0), len(spark_lines)):
            print(" " * (TABLE_W + TABLE_SPARK_GAP) + spark_lines[si])


# ──────────────────────────────────────────────
# MAIN CLI ENTRY
# ──────────────────────────────────────────────
def main():
    try:
        _main()
    except TogglRateLimitError as e:
        print(f"\n  {RED}{BOLD}{e}{RESET}")
        sys.exit(1)
    except TogglAPIError as e:
        print(f"\n  {RED}{e}{RESET}")
        sys.exit(1)


def _main():
    load_runtime_settings()
    
    if len(sys.argv) == 1:
        TogglTUI().run()
        return

    parser = argparse.ArgumentParser(description="Toggl Track Life Points CLI")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--update-all", type=int, nargs='?', const=4)
    parser.add_argument("--week", type=str, nargs='?', const=get_current_week())
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--yesterday", action="store_true")
    parser.add_argument("--day", type=str)
    parser.add_argument("--negatives", action="store_true")
    parser.add_argument("--negative", type=str, nargs='?', const="")
    parser.add_argument("--neg-log", type=str, nargs='?', const="week")
    parser.add_argument("--positives", action="store_true")
    parser.add_argument("--positive", type=str, nargs='?', const="")
    parser.add_argument("--pos-log", type=str, nargs='?', const="week")
    parser.add_argument("--quota", action="store_true")
    parser.add_argument("--recovery", action="store_true")
    
    args = parser.parse_args()
    
    if args.update:
        result = sync_current_week_light()
        reset_cache()
        if result["success"]:
            print(f"{GREEN}✓ {result['message']}{RESET}")
        else:
            print(f"{DIM}{result.get('message', 'Sync skipped')}{RESET}")
    elif args.update_all is not None:
        result = sync_api_to_csv(weeks_back=args.update_all)
        reset_cache()
        if result["success"]:
            print(f"{GREEN}✓ {result['message']}{RESET}")
        else:
            print(f"{DIM}{result.get('message', 'Sync skipped')}{RESET}")
    elif args.quota:
        _reset_api_stats()
        get_api_token()
        _print_api_usage_summary()
    elif args.negatives:
        print_neg_catalog()
    elif args.negative is not None:
        if args.negative == "":
            neg_name = pick_negative_interactive()
            if neg_name: log_negative(neg_name)
        else:
            log_negative(args.negative)
    elif args.neg_log:
        print_neg_log(args.neg_log)
    elif args.positives:
        print_pos_catalog()
    elif args.positive is not None:
        if args.positive == "":
            pos_name = pick_positive_interactive()
            if pos_name: log_positive(pos_name)
        else:
            log_positive(args.positive)
    elif args.pos_log:
        print_pos_log(args.pos_log)
    elif args.today:
        d_str = date.today().strftime("%Y-%m-%d")
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.yesterday:
        d_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.day:
        d_str = _parse_day_arg(args.day)
        if d_str is None:
            print(f"{RED}Error: --day requires a value (e.g. mon, today, YYYY-MM-DD){RESET}")
            sys.exit(1)
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.week:
        report = get_report_sections(args.week, "WEEK")
        print_report(report["results"], report["negative_results"], report["positive_results"], args.week, "WEEK")
    elif args.recovery:
        report = get_report_sections("ALL_TIME", "ALL")
        print_recovery_cli(report["results"], report["negative_results"], report["positive_results"], "ALL_TIME", "ALL")
    else:
        report = get_report_sections("ALL_TIME", "ALL")
        print_report(report["results"], report["negative_results"], report["positive_results"], "ALL_TIME", "ALL")


if __name__ == "__main__":
    main()