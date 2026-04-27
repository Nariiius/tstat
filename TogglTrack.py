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
import urllib.request
import urllib.parse
import urllib.error
import base64
import argparse
import io
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, date, timedelta, timezone

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static, OptionList

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


# ──────────────────────────────────────────────
# CONFIG HELPERS
# ──────────────────────────────────────────────
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
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
    config = load_config()
    POINTS = _load_rate_map(config, "points")
    NEGATIVES = _load_rate_map(config, "negatives")
    POSITIVES = _load_rate_map(config, "positives")
    daily_target = config.get("daily_target", DEFAULT_DAILY_TARGET)
    DAILY_TARGET = float(_coerce_number(daily_target, "daily_target"))


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
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
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
    API_RUN_STATS["requests_made"] = 0
    API_RUN_STATS["remaining"] = None
    API_RUN_STATS["limit"] = None
    API_RUN_STATS["resets_in"] = None


def _record_quota_headers(headers):
    remaining = _parse_int(_header_value(headers, "X-Toggl-Quota-Remaining"))
    limit = _parse_int(_header_value(headers, "X-Toggl-Quota-Limit"))
    resets_in = _parse_int(_header_value(headers, "X-Toggl-Quota-Resets-In"))
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
    API_RUN_STATS["requests_made"] += 1
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode() if method != "HEAD" else None
            headers = dict(response.headers)
            _record_quota_headers(headers)
            return body, headers, None
    except urllib.error.HTTPError as e:
        headers = dict(e.headers) if e.headers else {}
        _record_quota_headers(headers)
        return None, headers, e.code
    except Exception as e:
        return None, {}, str(e)


def toggl_request(endpoint, token):
    url = f"https://api.track.toggl.com/api/v9/{endpoint}"
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        assert body is not None
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
        print(f"\n  {RED}{BOLD}Rate limit reached ({limit} req/hr){RESET}")
        if resets_in:
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            print(f"  {YELLOW}Quota resets in: {BOLD}{wait}{RESET}")
        else:
            print(
                f"  {DIM}Quota reset time unavailable — wait up to 60 minutes.{RESET}"
            )
        print(f"  {DIM}Remaining: {remaining}/{limit} requests{RESET}\n")
        sys.exit(1)
    print(f"{RED}API Error: {err}{RESET} for endpoint {endpoint}")
    sys.exit(1)


def check_quota(token):
    url = f"https://api.track.toggl.com/api/v9/me"
    auth_string = f"{token}:api_token"
    b64_auth = base64.b64encode(auth_string.encode()).decode()
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {b64_auth}")
    req.add_header("Content-Type", "application/json")
    print(f"\n  {BOLD}{CYAN}API QUOTA STATUS{RESET}")
    print("  " + "─" * 35)
    try:
        with urllib.request.urlopen(req) as response:
            headers = response.headers
            remaining = headers.get("X-Toggl-Quota-Remaining", "Unknown")
            resets_in = headers.get("X-Toggl-Quota-Resets-In", "Unknown")
            print(f"  {GREEN}✓ Request successful{RESET}")
            print(f"  Requests remaining  {CYAN}{BOLD}{remaining}{RESET}")
            if resets_in != "Unknown":
                secs = int(resets_in)
                mins, s = divmod(secs, 60)
                wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
                print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
            else:
                print(f"  Window resets in    {DIM}Unknown{RESET}")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  {RED}✗ HTTP 429 — Rate limit exceeded.{RESET}")
            print(f"  {DIM}Making requests too fast. Safe limit is ~1 req/sec.{RESET}")
        elif e.code == 402:
            headers = e.headers
            resets_in = headers.get("X-Toggl-Quota-Resets-In", "Unknown")
            print(f"  {RED}✗ HTTP 402 — Hourly quota exhausted.{RESET}")
            if resets_in != "Unknown":
                secs = int(resets_in)
                mins, s = divmod(secs, 60)
                wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
                print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
        else:
            print(f"  {RED}✗ HTTP {e.code} — {e.reason}{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Failed to connect: {e}{RESET}")
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
        with open(PROJECTS_FILE, "r") as f:
            raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
    projects_data = toggl_request("me/projects", token)
    result = {p["id"]: p["name"] for p in projects_data if p.get("active")}
    with open(PROJECTS_FILE, "w") as f:
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
    with open(HISTORY_FILE, "r") as f:
        return json.load(f)


def _save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)


def get_last_updated_str():
    history = _load_history()
    ts = history.get("last_updated")
    if not ts:
        return "never"
    dt = datetime.fromisoformat(ts)
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
    diff = datetime.now() - datetime.fromisoformat(ts)
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
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone()
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
    with open(DAILY_CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Project", "Hours"])
        writer.writeheader()
        writer.writerows(rows)


def _patch_weekly_csv(week_str, weekly_data):
    existing = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r") as f:
            existing = [row for row in csv.DictReader(f) if row["Week"] != week_str]
    for proj, hours in weekly_data.items():
        if hours > 0:
            existing.append(
                {"Week": week_str, "Project": proj, "Hours": round(hours, 4)}
            )
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Week", "Project", "Hours"])
        writer.writeheader()
        writer.writerows(existing)


def sync_api_to_csv(weeks_back=4, prompt_on_warning=True):
    weeks_back = int(weeks_back)
    if weeks_back < 1:
        print(f"{RED}Error: --update-all expects a positive number of weeks.{RESET}")
        sys.exit(1)
    token = get_api_token()
    _reset_api_stats()
    estimated_requests = weeks_back + 2
    sync_label = f"full sync ({weeks_back} week{'s' if weeks_back != 1 else ''})"
    if not _confirm_sync_quota(
        token, estimated_requests, sync_label, prompt_on_warning=prompt_on_warning
    ):
        print(f"{DIM}Sync cancelled. Existing local data was left untouched.{RESET}")
        return False
    print(f"{DIM}Fetching projects map...{RESET}")
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
        print(f"{DIM}Fetching data for week {week}...{RESET}", end="")
        weekly_data, daily_data = fetch_week_data(week, token, projects_map)
        print(f"{DIM} found {len(weekly_data)} projects.{RESET}")
        weekly_payloads[week] = weekly_data
        if week == current_week:
            current_week_daily_data = daily_data
            if not daily_data:
                print(
                    f"{DIM}  -> No daily records found for the current week (since Sunday).{RESET}"
                )
            else:
                print(
                    f"{DIM}  -> Active daily records found for {len(daily_data)} day(s) this week.{RESET}"
                )
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
    print(f"{GREEN}✓ Successfully synced data (Weekly & Daily up to date){RESET}")
    _print_api_usage_summary()
    return True


def sync_current_week_light(auto_refresh=False, prompt_on_warning=True):
    token = get_api_token()
    refresh_projects = is_projects_cache_stale()
    _reset_api_stats()
    estimated_requests = 2 + (1 if refresh_projects else 0)
    sync_label = "auto-refresh" if auto_refresh else "current-week sync"
    if not _confirm_sync_quota(
        token, estimated_requests, sync_label, prompt_on_warning=prompt_on_warning
    ):
        print(f"{DIM}Sync cancelled. Existing local data was left untouched.{RESET}")
        return False
    if refresh_projects:
        age_days = get_projects_cache_age_days()
        if age_days is None:
            print(f"{DIM}Project cache missing — refreshing projects map...{RESET}")
        else:
            print(
                f"{DIM}Project cache is stale ({age_days:.1f} days old) — refreshing projects map...{RESET}"
            )
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
    if auto_refresh:
        print(f"{DIM}↻ Auto-refreshed (data was stale >30m){RESET}")
    else:
        print(f"{GREEN}✓ Successfully synced current week{RESET}")
    _print_api_usage_summary()
    return True


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
    pos_name = canonical
    cost = POSITIVES[pos_name]
    if not _prompt_yes_no(
        f"{YELLOW}Log positive '{pos_name}' for +{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    file_exists = os.path.exists(POSITIVES_CSV_FILE)
    with open(POSITIVES_CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Positive", "Points"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "Date": date.today().strftime("%Y-%m-%d"),
                "Positive": pos_name,
                "Points": cost,
            }
        )
    print(f"\n{GREEN}✓ Logged '{pos_name}' (+{cost} pts).{RESET}\n")
    sys.exit(0)

def print_pos_log(group_by="week"):
    if not os.path.exists(POSITIVES_CSV_FILE):
        print(f"{YELLOW}No positives logged yet.{RESET}")
        return
    rows = []
    with open(POSITIVES_CSV_FILE, "r") as f:
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
    neg_name = canonical
    cost = NEGATIVES[neg_name]
    if not _prompt_yes_no(
        f"{YELLOW}Log negative '{neg_name}' for -{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    file_exists = os.path.exists(NEGATIVES_CSV_FILE)
    with open(NEGATIVES_CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Negative", "Points"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "Date": date.today().strftime("%Y-%m-%d"),
                "Negative": neg_name,
                "Points": cost,
            }
        )
    print(f"\n{RED}✓ Logged '{neg_name}' (-{cost} pts).{RESET}\n")
    sys.exit(0)


def get_negatives_for_context(label, context_type):
    if not os.path.exists(NEGATIVES_CSV_FILE):
        return []
    negatives_dict: dict[str, float] = {}
    start_d, end_d = None, None
    if context_type == "WEEK":
        start_d, end_d = get_week_dates(label)
    with open(NEGATIVES_CSV_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                r_date_str = row["Date"]
                r_date = datetime.strptime(r_date_str, "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            include = False
            if context_type == "ALL":
                include = True
            elif context_type == "DAY" and r_date_str == label:
                include = True
            elif (
                context_type == "WEEK"
                and start_d
                and end_d
                and start_d <= r_date <= end_d
            ):
                include = True
            if include:
                try:
                    name = row.get("Negative") or row.get("Penalty") or "Unknown"
                    pts = float(row["Points"])
                    negatives_dict[name] = negatives_dict.get(name, 0.0) + pts
                except (KeyError, ValueError):
                    continue
    return [(name, None, None, -pts) for name, pts in negatives_dict.items()]


def print_neg_log(group_by="week"):
    """Print all negatives grouped by week or month."""
    if not os.path.exists(NEGATIVES_CSV_FILE):
        print(f"{YELLOW}No negatives logged yet.{RESET}")
        return
    rows = []
    with open(NEGATIVES_CSV_FILE, "r") as f:
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
    if not os.path.exists(CSV_FILE):
        return None
    projects: dict[str, float] = {}
    with open(CSV_FILE, "r") as f:
        for row in csv.DictReader(f):
            if row["Week"] == target_week:
                proj = row["Project"]
                projects[proj] = projects.get(proj, 0.0) + float(row["Hours"])
    return projects


def get_data_for_day(target_day):
    if not os.path.exists(DAILY_CSV_FILE):
        return None
    projects: dict[str, float] = {}
    with open(DAILY_CSV_FILE, "r") as f:
        for row in csv.DictReader(f):
            if row["Date"] == target_day:
                proj = row["Project"]
                projects[proj] = projects.get(proj, 0.0) + float(row["Hours"])
    return projects


def get_all_time_data():
    if not os.path.exists(CSV_FILE):
        return None
    projects: dict[str, float] = {}
    with open(CSV_FILE, "r") as f:
        for row in csv.DictReader(f):
            proj = row["Project"]
            projects[proj] = projects.get(proj, 0.0) + float(row["Hours"])
    return projects


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
    if not os.path.exists(NEGATIVES_CSV_FILE):
        return []
    rows = []
    with open(NEGATIVES_CSV_FILE, "r") as f:
        for row in csv.DictReader(f):
            try:
                rows.append(
                    {
                        "date": row["Date"],
                        "name": row.get("Negative") or row.get("Penalty") or "?",
                        "points": float(row["Points"]),
                    }
                )
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda item: item["date"], reverse=True)
    return rows[:limit]


def format_signed(value):
    if abs(value) < 0.05:
        value = 0.0
    return f"+{value:.1f}" if value > 0 else (f"{value:.1f}" if value < 0 else "0.0")


def get_day_metrics(day_str):
    projects = get_data_for_day(day_str) or {}
    results = calculate(projects)
    negatives = get_negatives_for_context(day_str, "DAY")
    positives = get_positives_for_context(day_str, "DAY")
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


def get_week_dashboard_rows(label):
    start_d, end_d = get_week_dates(label)
    rows = []
    cutoff = min(end_d, date.today()) if label == get_current_week() else end_d
    cumulative_net = 0.0
    cumulative_days = 0
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        metrics = get_day_metrics(d_str)
        has_activity = bool(metrics["projects"] or metrics["negative_results"] or metrics["positive_results"])
        if not has_activity and d > date.today():
            continue
        if d <= cutoff:
            cumulative_net += metrics["net"]
            cumulative_days += 1
        rows.append(
            {
                "day": d.strftime("%a"),
                "date": d_str,
                "date_short": d.strftime("%d %b"),
                "hours": metrics["total_hours"],
                "earned": metrics["earned"],
                "tracked_negative": metrics["tracked_negative"],
                "logged_positive": metrics["logged_positive"],
                "positive_total": round(
                    metrics["earned"] + metrics["logged_positive"], 1
                ),
                "logged_negative": metrics["logged_negative"],
                "negative_total": round(
                    metrics["tracked_negative"] + metrics["logged_negative"], 1
                ),
                "goal": DAILY_TARGET,
                "delta": metrics["delta"],
                "net": metrics["net"],
                "has_activity": has_activity,
                "is_today": d == date.today(),
            }
        )
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


def get_report_sections(label, context_type):
    if context_type == "DAY":
        projects = get_data_for_day(label) or {}
    elif context_type == "WEEK":
        projects = get_data_for_week(label) or {}
    else:
        projects = get_all_time_data() or {}
    results = calculate(projects)
    negative_results = get_negatives_for_context(label, context_type)
    positive_results = get_positives_for_context(label, context_type)
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


def get_recovery_rows(label, context_type):
    report = get_report_sections(label, context_type)
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
        rows.append(
            {
                "category": name,
                "rate": rate,
                "hours_needed": f"{h}h {m:02d}m",
            }
        )
    return {"total_points": total_pts, "rows": rows}


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
    if not os.path.exists(POSITIVES_CSV_FILE):
        return []
    positives_dict: dict[str, float] = {}
    start_d, end_d = None, None
    if context_type == "WEEK":
        start_d, end_d = get_week_dates(label)
    with open(POSITIVES_CSV_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                r_date_str = row["Date"]
                r_date = datetime.strptime(r_date_str, "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            include = False
            if context_type == "ALL":
                include = True
            elif context_type == "DAY" and r_date_str == label:
                include = True
            elif (
                context_type == "WEEK"
                and start_d
                and end_d
                and start_d <= r_date <= end_d
            ):
                include = True
            if include:
                try:
                    name = row.get("Positive") or row.get("Bonus") or "Unknown"
                    pts = float(row["Points"])
                    positives_dict[name] = positives_dict.get(name, 0.0) + pts
                except (KeyError, ValueError):
                    continue
    return [(name, None, None, pts) for name, pts in positives_dict.items()]

def get_positive_catalog_rows():
    return [(name, POSITIVES[name]) for name in POSITIVES]

def get_positive_log_rows(limit=30):
    if not os.path.exists(POSITIVES_CSV_FILE):
        return []
    rows = []
    with open(POSITIVES_CSV_FILE, "r") as f:
        for row in csv.DictReader(f):
            try:
                rows.append(
                    {
                        "date": row["Date"],
                        "name": row.get("Positive") or row.get("Bonus") or "?",
                        "points": float(row["Points"]),
                    }
                )
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda item: item["date"], reverse=True)
    return rows[:limit]

def log_positive_direct(pos_name):
    lower_map = {k.lower(): k for k in POSITIVES}
    canonical = lower_map.get(pos_name.strip().lower())
    if not canonical:
        return False, f"Positive '{pos_name}' not found"
    file_exists = os.path.exists(POSITIVES_CSV_FILE)
    with open(POSITIVES_CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Positive", "Points"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "Date": date.today().strftime("%Y-%m-%d"),
                "Positive": canonical,
                "Points": POSITIVES[canonical],
            }
        )
    return True, f"Logged {canonical} (+{POSITIVES[canonical]} pts)"


def log_negative_direct(neg_name):
    lower_map = {k.lower(): k for k in NEGATIVES}
    canonical = lower_map.get(neg_name.strip().lower())
    if not canonical:
        return False, f"Negative '{neg_name}' not found"
    file_exists = os.path.exists(NEGATIVES_CSV_FILE)
    with open(NEGATIVES_CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Negative", "Points"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "Date": date.today().strftime("%Y-%m-%d"),
                "Negative": canonical,
                "Points": NEGATIVES[canonical],
            }
        )
    return True, f"Logged {canonical} (-{NEGATIVES[canonical]} pts)"


def run_quietly(func, *args, **kwargs):
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        result = func(*args, **kwargs)
    output = stdout_buffer.getvalue().strip()
    errors = stderr_buffer.getvalue().strip()
    text = output or errors
    return result, text


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
        width: 32;
        min-width: 32;
        max-width: 32;
        border: solid #2e3947;
        padding: 0 1;
        display: block;
    }

    #spark-rail.-hidden {
        display: none;
    }

    #spark-title {
        color: #63f3ff;
        text-style: bold;
        margin: 0;
    }

    #sparkbar {
        height: 1fr;
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
        self._resize_timer = None

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
                with Vertical(id="spark-rail"):
                    yield Static(id="sparkbar")
            with Vertical(id="footer"):
                yield Static(id="footer-main")

    def on_mount(self):
        self._setup_tables()
        load_runtime_settings()
        if needs_auto_update():
            ok, message = run_quietly(
                sync_current_week_light, auto_refresh=True, prompt_on_warning=False
            )
            if ok:
                self.notify("Auto-refreshed stale data")
            elif message:
                self.notify("Auto-refresh skipped", severity="warning")
        self.refresh_all_views()

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

    def refresh_all_views(self):
        self.update_tabs()
        self.update_status_line()
        self.refresh_week_view()
        self.refresh_overview_view()
        self.refresh_day_view()
        self.refresh_negatives_view()
        self.refresh_positives_view()
        self.refresh_recovery_view()
        self.refresh_sync_view()
        self.refresh_sparkbar()
        self.update_view_visibility()
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def _schedule_resize(self):
        """Debounced resize: cancels any pending resize before scheduling a new one."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.1, self._resize_tables)

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
        footer_main.append(" sparkbar  •  up/down scroll  •  enter/select  •  q quit", style="#8d98a7")

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

    def refresh_sparkbar(self):
        rail = self.query_one("#spark-rail", Vertical)
        rail.border_title = "[b][#63f3ff]Current Week Trends[/][/]"
        self.query_one("#sparkbar", Static).update(Text.from_ansi(get_sparkbar_text()))

    def refresh_week_view(self):
        week = get_current_week()
        dashboard = get_week_dashboard_rows(week)
        report = get_report_sections(week, "WEEK")
        table = self.query_one("#week-table", DataTable)
        table.clear(columns=False)
        for row in dashboard["rows"]:
            neg_text = "—" if row["negative_total"] == 0 else f"[#ff5f5f]-{row['negative_total']:.1f}[/]"
            pos_text = "—" if row["logged_positive"] == 0 else f"[#37d994]+{row['logged_positive']:.1f}[/]"
            hour_text = "—" if row["hours"] == 0 else f"{row['hours']:.1f}h"
            earned_text = "—" if row["hours"] == 0 and row["earned"] == 0 else format_signed_rich(row["earned"])
            table.add_row(
                row["day"],
                row["date_short"],
                hour_text,
                earned_text,
                pos_text,
                neg_text,
                format_signed_rich(row["net"]),
                key=row["date"],
            )
        if dashboard["rows"]:
            default_date = self.selected_day if any(r["date"] == self.selected_day for r in dashboard["rows"]) else dashboard["rows"][0]["date"]
            self.selected_day = default_date
            row_index = next(i for i, row in enumerate(dashboard["rows"]) if row["date"] == default_date)
            table.move_cursor(row=row_index, column=0)
        category_table = self.query_one("#week-category-table", DataTable)
        category_table.clear(columns=False)
        for section_name in ("positive", "negative", "unscored"):
            rows = report[section_name]
            if rows:
                category_table.add_row(f"[{section_name.upper()}]", "", "", "")
            for name, hours, rate, pts in rows:
                category_table.add_row(
                    name,
                    f"{hours:.2f}h",
                    fmt_rate(rate),
                    fmt_pts_rich(pts),
                )
        if report["positive_results"]:
            category_table.add_row("[LOGGED POSITIVE]", "", "", "")
            for name, _, _, pts in report["positive_results"]:
                category_table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        if report["negative_results"]:
            category_table.add_row("[LOGGED NEGATIVE]", "", "", "")
            for name, _, _, pts in report["negative_results"]:
                category_table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        summary = dashboard["summary"]
        table.border_title = f"[b][#63f3ff]Week ({week})[/][/]"
        table.border_subtitle = f"[#8d98a7]Week net: {format_signed_rich(summary['actual'])} pts[/]"
        category_table.border_title = "[b][#63f3ff]Category Totals[/][/]"

    def refresh_overview_view(self):
        report = get_report_sections("ALL_TIME", "ALL")
        current_week = get_current_week()
        week_total = get_report_sections(current_week, "WEEK")["total_points"]
        table = self.query_one("#overview-table", DataTable)
        table.clear(columns=False)
        for section_name in ("positive", "negative", "unscored"):
            rows = report[section_name]
            if rows:
                table.add_row(f"[{section_name.upper()}]", "", "", "")
            for name, hours, rate, pts in rows:
                table.add_row(name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts))
        if report["positive_results"]:
            table.add_row("[LOGGED POSITIVE]", "", "", "")
            for name, _, _, pts in report["positive_results"]:
                table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        if report["negative_results"]:
            table.add_row("[LOGGED NEGATIVE]", "", "", "")
            for name, _, _, pts in report["negative_results"]:
                table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        total_hours = report["total_hours"]
        table.border_title = "[b][#63f3ff]Overview[/][/]"
        table.border_subtitle = (
            f"[#8d98a7]Lifetime total {format_signed_rich(report['total_points'])} pts   "
            f"{total_hours:.2f}h tracked   This week {format_signed_rich(week_total)}[/]"
        )

    def refresh_day_view(self):
        metrics = get_day_metrics(self.selected_day)
        table = self.query_one("#day-table", DataTable)
        table.clear(columns=False)
        pos_rows = [r for r in metrics["results"] if r[3] is not None and r[3] >= 0]
        neg_rows = [r for r in metrics["results"] if r[3] is not None and r[3] < 0]
        unscored_rows = [r for r in metrics["results"] if r[3] is None]

        if pos_rows:
            table.add_row("[POSITIVE]", "", "", "")
            for name, hours, rate, pts in pos_rows:
                table.add_row(name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts))
        if neg_rows:
            table.add_row("[NEGATIVE]", "", "", "")
            for name, hours, rate, pts in neg_rows:
                table.add_row(name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts))
        if metrics["positive_results"]:
            table.add_row("[LOGGED POSITIVE]", "", "", "")
            for name, _, _, pts in metrics["positive_results"]:
                table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        if metrics["negative_results"]:
            table.add_row("[LOGGED NEGATIVE]", "", "", "")
            for name, _, _, pts in metrics["negative_results"]:
                table.add_row(name, "—", "logged", fmt_pts_rich(pts))
        if unscored_rows:
            table.add_row("[UNSCORED]", "", "", "")
            for name, hours, rate, pts in unscored_rows:
                table.add_row(name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts))
        meta = (
            f"[#8d98a7]Hours {metrics['total_hours']:.1f}h   Earned {format_signed_rich(metrics['earned'])}   "
            f"Pos [#37d994]+{metrics['logged_positive']:.1f}[/]   "
            f"Negs [#ff5f5f]-{metrics['logged_negative']:.1f}[/]   Net {format_signed_rich(metrics['net'])}[/]"
        )
        table.border_title = f"[b][#63f3ff]Day ({self.selected_day})[/][/]"
        table.border_subtitle = meta

    def refresh_negatives_view(self):
        catalog = self.query_one("#negatives-catalog-table", DataTable)
        catalog.clear(columns=False)
        for name, points in get_negative_catalog_rows():
            catalog.add_row(name, fmt_pts_rich(-points))
        recent = self.query_one("#negatives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = get_negative_log_rows()
        for row in recent_rows:
            recent.add_row(row["date"], row["name"], fmt_pts_rich(-row["points"]))
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press n to log. Visible penalties: [#ff5f5f]-{total_recent:.0f}[/] pts[/]"

    def refresh_positives_view(self):
        catalog = self.query_one("#positives-catalog-table", DataTable)
        catalog.clear(columns=False)
        for name, points in get_positive_catalog_rows():
            catalog.add_row(name, fmt_pts_rich(points))
        recent = self.query_one("#positives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = get_positive_log_rows()
        for row in recent_rows:
            recent.add_row(row["date"], row["name"], fmt_pts_rich(row["points"]))
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press p to log. Visible positives: [#37d994]+{total_recent:.0f}[/] pts[/]"

    def refresh_recovery_view(self):
        data = get_recovery_rows("ALL_TIME", "ALL")
        table = self.query_one("#recovery-table", DataTable)
        table.clear(columns=False)
        for row in data["rows"]:
            rate = row["rate"]
            color = "[#37d994]" if rate >= 2 else ("[#63f3ff]" if rate >= 1 else "[#d7dde8]")
            table.add_row(f"{color}{row['category']}[/]", f"{color}{fmt_rate(rate)}[/]", f"{color}{row['hours_needed']}[/]")
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
        table.add_row("Current week", status["current_week"])
        table.add_row("Last updated", status["last_updated"])
        cache_age = status["projects_cache_age_days"]
        table.add_row(
            "Projects cache",
            "missing" if cache_age is None else f"{cache_age:.1f} days old",
        )
        table.add_row("Synced weeks", str(len(status["synced_weeks"])))
        table.add_row("Synced days", str(len(status["synced_days"])))
        
        remaining = status["quota_remaining"] if status["quota_remaining"] is not None else "Unknown"
        limit = status["quota_limit"] if status["quota_limit"] is not None else "Unknown"
        table.add_row("Requests made", str(API_RUN_STATS["requests_made"]))
        table.add_row("Quota remaining", f"{remaining}/{limit}")
        
        if status["quota_resets_in"] is not None:
            table.add_row(
                "Quota resets in", _format_reset_window(status["quota_resets_in"])
            )
        table.border_title = "[b][#63f3ff]Sync Status[/][/]"
        table.border_subtitle = "[#8d98a7]u syncs current week. U refreshes projects and syncs 4 weeks.[/]"

    @on(DataTable.RowHighlighted, "#week-table")
    def update_selected_day(self, event: DataTable.RowHighlighted):
        if event.row_key is not None:
            self.selected_day = str(event.row_key.value)
            self.refresh_day_view()

    @on(Click, ".view-tab")
    def click_view_tab(self, event: Click):
        if event.widget.id and event.widget.id.startswith("view-tab-"):
            self.active_view_index = int(event.widget.id.rsplit("-", 1)[1])
            self.update_tabs()
            self.update_view_visibility()
            self.focus_active_view()

    def action_next_view(self):
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self.update_tabs()
        self.update_view_visibility()
        self.focus_active_view()

    def action_prev_view(self):
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
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
        # Reflow columns — sparkbar appearing/disappearing changes #content width.
        # Without this call, column widths stay frozen at the pre-toggle dimensions.
        self._schedule_resize()

    def action_show_help(self):
        self.notify("Left/right switch views, n add negative, u sync, U full sync, s toggle sparkbar, q quit")

    def action_sync_current_week(self):
        def after_confirm(confirmed):
            if confirmed:
                ok, message = run_quietly(
                    sync_current_week_light, prompt_on_warning=False
                )
                self.refresh_all_views()
                if ok:
                    self.notify("Synced current week")
                else:
                    self.notify(message or "Sync skipped", severity="warning")

        self.push_screen(ConfirmScreen("Sync current week", "Run a current-week sync now?"), after_confirm)

    def action_sync_full(self):
        def after_confirm(confirmed):
            if confirmed:
                ok, message = run_quietly(
                    sync_api_to_csv, 4, prompt_on_warning=False
                )
                self.refresh_all_views()
                if ok:
                    self.notify("Synced last 4 weeks")
                else:
                    self.notify(message or "Full sync skipped", severity="warning")

        self.push_screen(ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"), after_confirm)

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

    def watch_size(self, size) -> None:
        """Fires whenever the terminal dimensions change.
        Replaces on_resize: Textual's Resize event has bubble=False so it is
        dispatched to the Screen, not the App — on_resize on App is unreliable.
        watch_size is a reactive watcher on App.size and always fires correctly."""
        if size.width == 0 or size.height == 0:
            return
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def _resize_tables(self):
        from rich.text import Text

        table_ids = [
            "#week-table", "#week-category-table", "#overview-table",
            "#day-table", "#negatives-catalog-table", "#negatives-log-table",
            "#positives-catalog-table", "#positives-log-table", "#recovery-table",
            "#sync-table"
        ]
        text_cols = {"Category", "Negative", "Positive", "Metric", "Value", "Cate"}

        # Always compute width from App size rather than #content.size
        # to avoid race conditions with Textual's async layout pass.
        rail = self.query_one("#spark-rail")
        rail_w = 34 if not rail.has_class("-hidden") else 0
        content_w = self.size.width - rail_w

        if content_w <= 0:
            # Terminal size unknown — bail and wait for the next resize event.
            return

        # -2 for the DataTable's own left+right border.
        available_width = max(10, content_w - 2)

        for t_id in table_ids:
            try:
                table = self.query_one(t_id, DataTable)
            except Exception:
                continue

            if not table.columns:
                continue

            col_keys = list(table.columns.keys())
            n_cols = len(col_keys)
            cell_padding = table.cell_padding  # default 1; get_render_width adds 2*cell_padding per col

            # req_widths stores PURE CONTENT widths (no padding).
            # column.width must be pure content — get_render_width() adds 2*cell_padding on top.
            # If we put padding into column.width it gets double-counted and columns overflow.
            req_widths = {key: len(col.label.plain) for key, col in table.columns.items()}

            for row_idx in range(table.row_count):
                row_data = table.get_row_at(row_idx)
                for col_idx, col_key in enumerate(col_keys):
                    val = str(row_data[col_idx])
                    try:
                        cell_w = Text.from_markup(val).cell_len
                    except Exception:
                        cell_w = len(strip_ansi(val))
                    if cell_w > req_widths[col_key]:
                        req_widths[col_key] = cell_w

            # Total space consumed by padding across all columns (added automatically by get_render_width).
            total_padding = 2 * cell_padding * n_cols
            # Space available for pure column content after accounting for padding.
            content_budget = available_width - total_padding
            # Total pure content width required to fit every cell without clipping.
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
                # Enough room — give everyone their minimum, expand text cols with leftover.
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
                # Not enough room — give fixed cols their minimum, squeeze text cols.
                fixed_content_req = sum(req_widths[k] for k in fixed_keys)
                expandable_budget = content_budget - fixed_content_req
                if expandable_budget > 0 and expandable_keys:
                    for key in fixed_keys:
                        table.columns[key].width = req_widths[key]
                        table.columns[key].auto_width = False
                    base_w = expandable_budget // len(expandable_keys)
                    rem = expandable_budget % len(expandable_keys)
                    for i, key in enumerate(expandable_keys):
                        table.columns[key].width = max(1, base_w + (1 if i < rem else 0))
                        table.columns[key].auto_width = False
                else:
                    # Extremely narrow — split content_budget equally across all cols.
                    base_w = content_budget // n_cols
                    rem = content_budget % n_cols
                    for i, key in enumerate(table.columns.keys()):
                        table.columns[key].width = max(1, base_w + (1 if i < rem else 0))
                        table.columns[key].auto_width = False

            # layout=True forces DataTable to recompute its virtual size (scroll bounds)
            # from the new column widths — without this the repaint uses stale dimensions.
            table.refresh(layout=True)
            # Reset horizontal scroll — refresh(layout=True) fixes virtual size but
            # never resets scroll_x. Without this, the table renders from a stale
            # offset and appears unchanged even though widths are correctly computed.
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
    daily_proj: dict[str, dict[str, float]] = {}
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d_str = row["Date"]
                if d_str not in daily_proj:
                    daily_proj[d_str] = {}
                daily_proj[d_str][row["Project"]] = daily_proj[d_str].get(
                    row["Project"], 0.0
                ) + float(row["Hours"])
    daily_neg: dict[str, dict[str, float]] = {}
    if os.path.exists(NEGATIVES_CSV_FILE):
        with open(NEGATIVES_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d_str = row["Date"]
                name = row.get("Negative") or row.get("Penalty") or "Unknown"
                if d_str not in daily_neg:
                    daily_neg[d_str] = {}
                daily_neg[d_str][name] = daily_neg[d_str].get(name, 0.0) + float(
                    row["Points"]
                )
    daily_pos: dict[str, dict[str, float]] = {}
    if os.path.exists(POSITIVES_CSV_FILE):
        with open(POSITIVES_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d_str = row["Date"]
                name = row.get("Positive") or row.get("Bonus") or "Unknown"
                if d_str not in daily_pos:
                    daily_pos[d_str] = {}
                daily_pos[d_str][name] = daily_pos[d_str].get(name, 0.0) + float(
                    row["Points"]
                )
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
        projs = daily_proj.get(d_str, {})
        negs = daily_neg.get(d_str, {})
        poss = daily_pos.get(d_str, {})
        if not projs and not negs and not poss and d > date.today():
            continue
        has_data = True
        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None)
        hours = sum(projs.values())
        neg_cost = sum(negs.values())
        pos_bonus = sum(poss.values())
        net = earned - neg_cost + pos_bonus
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
# SPARKBAR HELPERS
# ──────────────────────────────────────────────

def get_week_pos_breakdown(week_str):
    logged = 0.0
    if os.path.exists(POSITIVES_CSV_FILE):
        try:
            start_d, end_d = get_week_dates(week_str)
            with open(POSITIVES_CSV_FILE, "r") as f:
                for row in csv.DictReader(f):
                    try:
                        r_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                        if start_d <= r_date <= end_d:
                            logged += float(row["Points"])
                    except (KeyError, ValueError):
                        continue
        except Exception:
            pass
    return round(logged, 1)

def get_week_neg_breakdown(week_str):
    """
    Returns (tracked_neg_pts, logged_neg_pts) both as positive numbers.
    tracked = points lost from negative-rate Toggl projects that week.
    logged  = points lost from manually logged negatives that week.
    """
    tracked = 0.0
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                if row["Week"] == week_str:
                    rate = POINTS.get(row["Project"])
                    if rate is not None and rate < 0:
                        tracked += abs(float(row["Hours"]) * rate)

    logged = 0.0
    if os.path.exists(NEGATIVES_CSV_FILE):
        try:
            start_d, end_d = get_week_dates(week_str)
            with open(NEGATIVES_CSV_FILE, "r") as f:
                for row in csv.DictReader(f):
                    try:
                        r_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                        if start_d <= r_date <= end_d:
                            logged += float(row["Points"])
                    except (KeyError, ValueError):
                        continue
        except Exception:
            pass

    return round(tracked, 1), round(logged, 1)


def build_blame_bar(tracked, logged, n=BLAME_W):
    """
    Returns an n-block bar split proportionally between:
      RED     = tracked negatives share (negative-rate Toggl projects)
      MAGENTA = logged negatives share  (manually logged negatives)
    Returns spaces if no negatives at all.
    """
    total = tracked + logged
    if total == 0:
        return " " * n
    red_count = round(tracked / total * n)
    mag_count = n - red_count
    return f"{RED}{'█' * red_count}{RESET}{MAGENTA}{'█' * mag_count}{RESET}"


def time_left_in_week():
    """Returns human-readable time remaining until end of Saturday."""
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
# SPARKBAR (returns list of strings)
# ──────────────────────────────────────────────
def build_week_sparkbar_lines(_week_str=None):
    """
    Always builds the sparkbar for the CURRENT week regardless of what week
    the main table is displaying.  Returns a list of strings (ANSI coloured).
    """
    week_str = get_current_week()
    start_d, _ = get_week_dates(week_str)

    # ── load daily project hours ──
    daily_proj: dict[str, dict[str, float]] = {}
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d = row["Date"]
                daily_proj.setdefault(d, {})
                daily_proj[d][row["Project"]] = daily_proj[d].get(
                    row["Project"], 0.0
                ) + float(row["Hours"])

    # ── load daily negatives ──
    daily_neg_map: dict[str, dict[str, float]] = {}
    if os.path.exists(NEGATIVES_CSV_FILE):
        with open(NEGATIVES_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d = row["Date"]
                name = row.get("Negative") or row.get("Penalty") or "?"
                daily_neg_map.setdefault(d, {})
                try:
                    daily_neg_map[d][name] = daily_neg_map[d].get(name, 0.0) + float(
                        row["Points"]
                    )
                except ValueError:
                    pass
    daily_pos_map: dict[str, dict[str, float]] = {}
    if os.path.exists(POSITIVES_CSV_FILE):
        with open(POSITIVES_CSV_FILE, "r") as f:
            for row in csv.DictReader(f):
                d = row["Date"]
                name = row.get("Positive") or row.get("Bonus") or "?"
                daily_pos_map.setdefault(d, {})
                try:
                    daily_pos_map[d][name] = daily_pos_map[d].get(name, 0.0) + float(
                        row["Points"]
                    )
                except ValueError:
                    pass

    # ── compute per-day stats ──
    day_data = []
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        projs = daily_proj.get(d_str, {})
        negs = daily_neg_map.get(d_str, {})
        pos_logged = daily_pos_map.get(d_str, {})

        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None)
        logged_neg = sum(negs.values())
        logged_pos = sum(pos_logged.values())
        tracked_neg = sum(
            abs(hours * POINTS[name])
            for name, hours in projs.items()
            if name in POINTS and POINTS[name] < 0
        )
        net = round(earned - logged_neg + logged_pos, 1)
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
                "has_data": bool(projs or negs or pos_logged),
            }
        )

    nonzero = [abs(dd["net"]) for dd in day_data if dd["has_data"] and dd["net"] != 0]
    max_abs = max(nonzero, default=1)

    lines: list[str] = []

    # ════════════════════════════════
    # PAST 4 WEEKS
    # ════════════════════════════════
    lines.append(f"{BOLD}{CYAN}PAST 4 WEEKS{RESET}")
    lines.append("─" * SPARK_W)

    current_sunday = get_sunday_of_week(date.today())

    # 1. Gather data to compute max_abs for scaling the weekly bars
    past_weeks_data = []
    max_abs_pw = 0.1  # Prevent division by zero if all weeks are exactly 0

    for i in range(3, 0, -1):
        pw_sunday = current_sunday - timedelta(days=7 * i)
        pw = get_week_str(pw_sunday)
        pw_num = pw.split("W")[1]
        pw_label = f"W{int(pw_num)}"

        pw_data = get_data_for_week(pw)
        if pw_data:
            pw_results = calculate(pw_data)
            pw_earned = sum(r[3] for r in pw_results if r[3] is not None)
        else:
            pw_earned = 0.0

        pw_tracked, pw_logged = get_week_neg_breakdown(pw)
        pw_logged_pos = get_week_pos_breakdown(pw)
        pw_net = round(pw_earned - pw_logged + pw_logged_pos, 1)

        max_abs_pw = max(max_abs_pw, abs(pw_net))
        past_weeks_data.append(
            {
                "label": pw_label,
                "net": pw_net,
                "tracked_neg": pw_tracked,
                "logged_neg": pw_logged,
            }
        )

    # 2. Render rows with rigid central alignment
    SIDE_W = SPARK_PTS_W + 1 + SPARK_BAR_W
    TOTAL_LEFT_MARGIN = 2  # Global spaces before neg_part in normal rows

    for pwd in past_weeks_data:
        net = pwd["net"]
        label_base = f"{pwd['label']:<3}"

        # Force the bar to be at least 1 char wide if net isn't 0
        bar_len = max(1, round(abs(net) / max_abs_pw * SPARK_BAR_W)) if net != 0 else 0
        bar_str = "█" * bar_len

        # Initialize blame variables so they exist for all branches
        blame_str: str = ""
        blame_vis_len: int = 0

        # Generate blame bar ONLY if there are negatives AND the net score is below zero
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

            line = f"{left_side_str} {label_str} {pos_part}"

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

            line = f"{left_side_str} {label_str} {pos_part}"

        else:
            # Zero net
            pts_s = "0.0"
            label_str = label_base

            neg_pad = max(0, SIDE_W - blame_vis_len)
            neg_part = " " * neg_pad + blame_str
            left_side_str = " " * TOTAL_LEFT_MARGIN + neg_part

            content_len = len(pts_s)
            pad_len = max(0, SIDE_W - content_len)
            pos_part = f"   {DIM}{pts_s}{RESET}" + " " * pad_len

            line = f"{left_side_str} {label_str} {pos_part}"

        lines.append(line)

    lines.append("─" * SPARK_W)

    # ════════════════════════════════
    # THIS WEEK header
    # ════════════════════════════════
    tw_logged_neg = round(sum(dd["logged_neg"] for dd in day_data), 1)
    tw_logged_pos = round(sum(dd["logged_pos"] for dd in day_data), 1)
    
    neg_l_str = f"{MAGENTA}-{tw_logged_neg}l{RESET}" if tw_logged_neg > 0 else f"{DIM}-0l{RESET}"
    pos_l_str = f"{GREEN}+{tw_logged_pos}l{RESET}" if tw_logged_pos > 0 else f"{DIM}+0l{RESET}"
    l_str = f"{pos_l_str} {neg_l_str}"

    lines.append(f"{BOLD}THIS WEEK{RESET} {DIM}({week_str}){RESET} {l_str}")
    lines.append("─" * SPARK_W)

    # ════════════════════════════════
    # Day rows
    # ════════════════════════════════
    SIDE_W = SPARK_PTS_W + 1 + SPARK_BAR_W

    for dd in day_data:
        net = dd["net"]
        name = dd["name"]
        today_mark = f" {YELLOW}◀{RESET}" if dd["is_today"] else ""

        if dd["future"] or not dd["has_data"]:
            day_str = f"{DIM}{name}{RESET}"
        else:
            day_str = name

        # Future or empty days: blank axis + optional today marker
        if (dd["future"] or not dd["has_data"]) and net == 0:
            neg_part = " " * SIDE_W
            pos_part = " " * SIDE_W
            line = f"  {neg_part} {day_str} {pos_part}{today_mark}"
            lines.append(line)
            continue

        bar_len = max(1, round(abs(net) / max_abs * SPARK_BAR_W)) if net != 0 else 0
        bar_str = "█" * bar_len

        # Generate blame bar ONLY if there are negatives AND the net score is below zero
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
            # zero net but has data
            pts_s = "0.0"
            neg_pad = max(0, SIDE_W - blame_vis_len_d)
            neg_part = " " * neg_pad + blame_str_d

            content_len = len(pts_s)
            pad_len = max(0, SIDE_W - content_len)
            pos_part = f"   {DIM}{pts_s}{RESET}" + " " * pad_len

        line = f"  {neg_part} {day_str} {pos_part}{today_mark}"
        lines.append(line)

    lines.append("─" * SPARK_W)

    # ════════════════════════════════
    # CATCHUP
    # ════════════════════════════════
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

        lines.append(
            f"{YELLOW}CATCHUP{RESET} {RED}{deficit} Pts{RESET} {CYAN}in {tl_str}{RESET}"
        )

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
            # Use TASK_SHORT_NAMES with guaranteed str fallback
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
                lines.extend(expanded_lines)
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
                lines.append(compact_prefix + f"{color_ansi}{task_str}{RESET}")
                available_lines -= 1

    else:
        lines.append(f"{GREEN}ON TRACK{RESET}  {DIM}(+{lifetime_pts} pts){RESET}")

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
    # Weekly day-by-day breakdown prints separately above the merged table
    if context_type == "WEEK":
        print_weekly_dashboard(label)

    # ── compute totals ──
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

    # ── build table lines ──
    lines: list[str] = []

    sep_len = COL1 + COL2 + COL3 + COL4 + 3  # = 52

    lines.append(meta)

    lines.append(
        f"  {BOLD}{'Category':<{COL1}} {'Hours':>{COL2}} {'Rate':>{COL3}} {'Points':>{COL4}}{RESET}"
    )
    lines.append("  " + "─" * sep_len)

    pos_rows = [r for r in results if r[3] is not None and r[3] >= 0]
    neg_rows = [r for r in results if r[3] is not None and r[3] < 0]
    null_rows = [r for r in results if r[3] is None]

    # ── shared row formatter ──
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

    # POSITIVE
    if pos_rows:
        lines.append(f"  {BOLD}{DIM}POSITIVE{RESET}")
        for r in pos_rows:
            lines.append(_row_str(r[0], r[1], r[2], r[3], GREEN))

    # POSITIVES LOGGED
    if positive_results:
        pos_log_subtotal = round(sum(r[3] for r in positive_results), 1)
        lines.append("")
        lines.append(
            f"  {BOLD}{DIM}POSITIVES LOGGED{RESET}  "
            f"{GREEN}+{pos_log_subtotal} manually logged{RESET}"
        )
        for r in positive_results:
            lines.append(_row_str(r[0], r[1], r[2], r[3], GREEN))

    # NEGATIVE  (tracked projects with negative rates)
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

    # NEGATIVES LOGGED  (manually logged penalties)
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

    # UNSCORED
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

    # ── sparkbar: show for ALL, WEEK, and DAY contexts ──
    spark_lines: list[str] = []
    if context_type in ("WEEK", "ALL", "DAY"):
        spark_lines = build_week_sparkbar_lines()

    # ── merge table + sparkbar and print ──
    for i, tline in enumerate(lines):
        si = i - SPARK_START_ROW
        if spark_lines and 0 <= si < len(spark_lines):
            tv = vlen(tline)
            pad = max(TABLE_W - tv + TABLE_SPARK_GAP, TABLE_SPARK_GAP)
            print(tline + " " * pad + spark_lines[si])
        else:
            print(tline)

    # any spark lines that extend below the table
    if spark_lines:
        first_remaining = len(lines) - SPARK_START_ROW
        for si in range(max(first_remaining, 0), len(spark_lines)):
            print(" " * (TABLE_W + TABLE_SPARK_GAP) + spark_lines[si])


# ──────────────────────────────────────────────
# MAIN CLI ENTRY
# ──────────────────────────────────────────────
def main():
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
        sync_current_week_light()
    elif args.update_all is not None:
        sync_api_to_csv(weeks_back=args.update_all)
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