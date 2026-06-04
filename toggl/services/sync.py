"""Sync logic — API fetch, CSV patch, history tracking.

Moved from cache.py (lines ~590-763) to isolate sync concerns.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
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


def _ensure_csv_from_backup(csv_path: str) -> None:
    """Restore CSV from latest backup if the file is missing.

    This prevents data loss when the CSV file is accidentally deleted:
    the sync edits existing data rather than creating a fresh file.
    """
    if os.path.exists(csv_path):
        return
    backup_dir = os.path.join(toggl.const.DATA_DIR, "backups")
    if not os.path.isdir(backup_dir):
        return
    # Find the latest backup folder (sorted by name = sorted by time)
    dirs = sorted(
        d for d in os.listdir(backup_dir)
        if os.path.isdir(os.path.join(backup_dir, d))
    )
    for d in reversed(dirs):
        src = os.path.join(backup_dir, d, os.path.basename(csv_path))
        if os.path.exists(src):
            shutil.copy2(src, csv_path)
            logger.warning("[SYNC] Restored %s from backup %s", os.path.basename(csv_path), d)
            return


def _patch_daily_csv(week_str: str, daily_data: dict[str, dict[str, float]]) -> None:
    _ensure_csv_from_backup(toggl.const.DAILY_CSV_FILE)
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
    _ensure_csv_from_backup(toggl.const.CSV_FILE)
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


# ---------------------------------------------------------------------------
# Daily-data gap detection and conservative backfill
# ---------------------------------------------------------------------------


def detect_daily_gaps() -> list[str]:
    """Return weeks that have entries in the weekly CSV but zero days
    in the daily CSV, sorted oldest-first.
    """
    if not os.path.exists(toggl.const.CSV_FILE):
        return []
    if not os.path.exists(toggl.const.DAILY_CSV_FILE):
        # No daily CSV at all — every week with data is a gap
        weeks_with_data: set[str] = set()
        with open(toggl.const.CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                weeks_with_data.add(row["Week"])
        return sorted(weeks_with_data)

    # Collect dates present in the daily CSV
    daily_dates: set[str] = set()
    with open(toggl.const.DAILY_CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            daily_dates.add(row["Date"])

    # Scan weekly CSV for weeks whose date range has zero overlap
    weeks: dict[str, tuple[date, date]] = {}
    with open(toggl.const.CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wk = row["Week"]
            if wk not in weeks:
                weeks[wk] = get_week_dates(wk)

    gaps: list[str] = []
    for wk in sorted(weeks.keys()):
        start_d, end_d = weeks[wk]
        # Does any day in this week exist in daily_dates?
        any_present = any(
            (start_d + timedelta(days=i)).strftime("%Y-%m-%d") in daily_dates
            for i in range(7)
        )
        if not any_present:
            gaps.append(wk)

    # Skip the current + next week (API may have no entries for future)
    current_week = get_current_week()
    future_weeks = {current_week}
    # Also skip the week after current (partial future week)
    next_sunday = get_sunday_of_week(date.today()) + timedelta(days=7)
    future_weeks.add(get_week_str(next_sunday))

    gaps = [wk for wk in gaps if wk not in future_weeks]
    return gaps


def fill_daily_gaps(
    max_weeks: int = 3, prompt_on_warning: bool = False
) -> dict[str, bool | str]:
    """Fetch daily data for weeks that are missing it, up to *max_weeks*.

    Uses the existing ``_patch_*`` merge functions — existing data is
    never overwritten, only missing weeks are filled in.

    Returns ``{"success": True, "message": "Filled 3 week(s), 4 remaining"}``.
    """
    from toggl.api import (
        get_api_token,
        get_projects_map,
        _reset_api_stats,
        _confirm_sync_quota,
    )

    gaps = detect_daily_gaps()
    if not gaps:
        return {"success": True, "message": "No daily data gaps detected"}

    # Only fill the oldest gaps first (furthest back)
    to_fill = gaps[:max_weeks]

    token = get_api_token()
    _reset_api_stats()
    estimated = len(to_fill) + 2  # +1 projects, +1 headroom
    if not _confirm_sync_quota(token, estimated, "gap fill", prompt_on_warning):
        return {"success": False, "message": "Gap fill cancelled (low quota)"}

    projects_map = get_projects_map(token)
    filled = 0
    for wk in to_fill:
        logger.debug("[SYNC] fill_daily_gaps: fetching week=%s", wk)
        weekly_data, daily_data = fetch_week_data(wk, token, projects_map)
        _patch_weekly_csv(wk, weekly_data)
        _patch_daily_csv(wk, daily_data)
        filled += 1

    remaining = len(gaps) - filled
    history = _load_history()
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)

    if remaining > 0:
        msg = f"Filled {filled} week(s), {remaining} remaining"
    else:
        msg = f"Filled {filled} week(s), all gaps resolved"
    return {"success": True, "message": msg}