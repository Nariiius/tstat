"""Sync logic — API fetch, CSV patch, history tracking.

Moved from cache.py (lines ~590-763) to isolate sync concerns.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Any

import toggl.const
from toggl.cache import (
    get_week_dates,
    get_week_str,
    get_sunday_of_week,
    get_current_week,
    get_iso_format,
    parse_iso,
)

logger = logging.getLogger("TStat")


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def _atomic_write(path: str, content_str: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content_str)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def _load_history() -> dict[str, Any]:
    """Load sync history from JSON file."""
    if not os.path.exists(toggl.const.HISTORY_FILE):
        return {}
    with open(toggl.const.HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: dict) -> None:
    """Save sync history to JSON file (atomic write)."""
    _atomic_write(toggl.const.HISTORY_FILE, json.dumps(history, indent=4))


# ---------------------------------------------------------------------------
# CSV patch helpers
# ---------------------------------------------------------------------------


def _patch_daily_csv(week_str: str, daily_data: dict[str, dict[str, float]]) -> None:
    start_d, end_d = get_week_dates(week_str)
    week_dates = set(
        (start_d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)
    )

    existing_rows = []
    if os.path.exists(toggl.const.DAILY_CSV_FILE):
        with open(toggl.const.DAILY_CSV_FILE, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    merged: dict[str, dict[str, float]] = {}
    for row in existing_rows:
        d = row["Date"]
        p = row["Project"]
        h = float(row["Hours"])
        if d not in week_dates:
            merged.setdefault(d, {})[p] = h

    for day_str, projs in daily_data.items():
        if day_str in week_dates:
            for proj, hours in projs.items():
                if hours > 0:
                    merged.setdefault(day_str, {})[proj] = hours

    rows = []
    for day_str in sorted(merged.keys()):
        for proj, hours in merged[day_str].items():
            if hours > 0:
                rows.append(
                    {"Date": day_str, "Project": proj, "Hours": round(hours, 4)}
                )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(toggl.const.DAILY_CSV_FILE, buf.getvalue())


def _patch_weekly_csv(week_str: str, weekly_data: dict[str, float]) -> None:
    existing_rows = []
    if os.path.exists(toggl.const.CSV_FILE):
        with open(toggl.const.CSV_FILE, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    merged: dict[str, dict[str, float]] = {}
    for row in existing_rows:
        wk = row["Week"]
        p = row["Project"]
        h = float(row["Hours"])
        if wk != week_str:
            merged.setdefault(wk, {})[p] = h

    for proj, hours in weekly_data.items():
        if hours > 0:
            merged.setdefault(week_str, {})[proj] = hours

    rows = []
    for wk in sorted(merged.keys()):
        for proj, hours in merged[wk].items():
            if hours > 0:
                rows.append(
                    {"Week": wk, "Project": proj, "Hours": round(hours, 4)}
                )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Week", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(toggl.const.CSV_FILE, buf.getvalue())


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------


def fetch_week_data(
    week_str: str,
    token: str,
    projects_map: dict[int, str],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    import urllib.parse

    from toggl.api import toggl_request

    start_d, end_d = get_week_dates(week_str)
    start_iso = get_iso_format(start_d, is_end=False)
    end_iso = get_iso_format(end_d, is_end=True)
    logger.debug("[SYNC] fetch_week_data: week=%s range=[%s -> %s]", week_str, start_iso, end_iso)
    params = urllib.parse.urlencode(
        {"start_date": start_iso, "end_date": end_iso},
        safe=":",
    )
    endpoint = f"me/time_entries?{params}"
    entries = toggl_request(endpoint, token)
    logger.debug(
        "[SYNC] fetch_week_data: API returned %d entries", len(entries) if entries else 0
    )
    weekly_data: dict[str, float] = {}
    daily_data: dict[str, dict[str, float]] = {}
    for entry in entries:
        pid = entry.get("pid")
        if pid is None or pid not in projects_map:
            continue
        proj_name = projects_map[pid]
        dur = entry.get("duration", 0)
        if dur < 0:
            continue
        hrs = dur / 3600.0
        weekly_data[proj_name] = weekly_data.get(proj_name, 0.0) + hrs
        start_raw = entry.get("start", "")
        if start_raw:
            dt = parse_iso(start_raw)
            if dt is not None:
                day_str = dt.astimezone().strftime("%Y-%m-%d")
            else:
                day_str = start_raw[:10]
        else:
            day_str = ""

        if day_str:
            if day_str not in daily_data:
                daily_data[day_str] = {}
            daily_data[day_str][proj_name] = (
                daily_data[day_str].get(proj_name, 0.0) + hrs
            )
    logger.debug(
        "[SYNC] fetch_week_data: processed -> %d projects (weekly), %d days (daily)",
        len(weekly_data),
        len(daily_data),
    )
    return weekly_data, daily_data


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------


def sync_api_to_csv(
    weeks_back: int = 4, prompt_on_warning: bool = True
) -> dict[str, bool | str]:
    from toggl.api import (
        get_api_token,
        get_projects_map,
        _reset_api_stats,
        _confirm_sync_quota,
    )

    weeks_back = int(weeks_back)
    if weeks_back < 1:
        raise ValueError("--update-all expects a positive number of weeks")
    token = get_api_token()
    _reset_api_stats()
    estimated = weeks_back + 2
    if not _confirm_sync_quota(token, estimated, "full sync", prompt_on_warning):
        return {"success": False, "message": "Sync cancelled (low quota)"}
    projects_map = get_projects_map(token)
    for i in range(weeks_back - 1, -1, -1):
        sunday = get_sunday_of_week(date.today()) - timedelta(days=7 * i)
        week_str = get_week_str(sunday)
        weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
        _patch_weekly_csv(week_str, weekly_data)
        _patch_daily_csv(week_str, daily_data)

    history = _load_history()
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)
    return {"success": True, "message": f"Successfully synced {weeks_back} week(s)"}


def sync_current_week_light(
    auto_refresh: bool = False, prompt_on_warning: bool = True
) -> dict[str, bool | str]:
    from toggl.api import (
        get_api_token,
        get_projects_map,
        is_projects_cache_stale,
        _reset_api_stats,
        _confirm_sync_quota,
    )

    token = get_api_token()
    refresh_projects = is_projects_cache_stale()
    _reset_api_stats()
    estimated = 3 if refresh_projects else 2
    label = "auto-refresh" if auto_refresh else "weekly sync"
    if not _confirm_sync_quota(token, estimated, label, prompt_on_warning):
        return {"success": False, "message": "Sync cancelled (low quota)"}
    projects_map = get_projects_map(token, use_cache=not refresh_projects)
    week_str = get_current_week()
    logger.debug("[SYNC] sync_current_week_light: fetching week=%s", week_str)
    weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
    logger.debug(
        "[SYNC] fetch_week_data returned: %d weekly entries, %d daily entries",
        len(weekly_data) if weekly_data else 0,
        len(daily_data) if daily_data else 0,
    )
    _patch_weekly_csv(week_str, weekly_data)
    _patch_daily_csv(week_str, daily_data)

    history = _load_history()
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)
    return {"success": True, "message": "Synced current week"}