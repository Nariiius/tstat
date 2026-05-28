"""Backfill subsystem for Toggl TUI.

Pulls all historical Toggl data (from 2023-01-01 onward) into local CSVs.
Tracks progress in a SQLite DB at ``data/toggl_backfill.db``.
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

from toggl.api import (
    API_RUN_STATS,
    TogglRateLimitError,
)
from toggl.cache import (
    _patch_daily_csv,
    _patch_weekly_csv,
    fetch_week_data,
    get_current_week,
    get_sunday_of_week,
    get_week_dates,
    get_week_str,
)
from toggl.const import BACKFILL_DB



# ── Path ─────────────────────────────────────────────────────────────────────

def get_backfill_db_path():
    return BACKFILL_DB


# ── DB init ───────────────────────────────────────────────────────────────────

def _get_conn():
    return sqlite3.connect(BACKFILL_DB)


def init_backfill_db():
    os.makedirs(os.path.dirname(BACKFILL_DB), exist_ok=True)
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'started',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            weeks_discovered INTEGER DEFAULT 0,
            weeks_backfilled INTEGER DEFAULT 0,
            api_requests_made INTEGER DEFAULT 0,
            stopped_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            earliest_week TEXT,
            last_completed_week TEXT,
            last_verified_at TEXT,
            last_verified_week TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
    """)
    conn.commit()
    conn.close()


# ── Week helpers ─────────────────────────────────────────────────────────────

def _weeks_in_range(start_week, end_week):
    start_d, _ = get_week_dates(start_week)
    end_d, _ = get_week_dates(end_week)
    weeks = []
    current = start_d
    while current <= end_d:
        weeks.append(get_week_str(current))
        current += timedelta(days=7)
    return weeks


def _has_week_data(weekly_data, daily_data):
    return bool(weekly_data) or any(d for d in daily_data.values())


# ── Binary search ────────────────────────────────────────────────────────────

def find_earliest_week(token, projects_map):
    low = date(2023, 1, 1)
    high = date.today()

    while low <= high:
        mid = low + (high - low) // 2
        mid_sunday = get_sunday_of_week(mid)
        mid_week = get_week_str(mid_sunday)

        weekly_data, daily_data = fetch_week_data(mid_week, token, projects_map)

        if _has_week_data(weekly_data, daily_data):
            high = mid_sunday - timedelta(days=1)
        else:
            low = mid_sunday + timedelta(days=7)

    low_sunday = get_sunday_of_week(low)
    low_week = get_week_str(low_sunday)
    if low_sunday > date.today():
        return None
    weekly_data, daily_data = fetch_week_data(low_week, token, projects_map)
    return low_week if _has_week_data(weekly_data, daily_data) else None


# ── Missing week detection ───────────────────────────────────────────────────

def find_missing_weeks(earliest_week):
    current_week = get_current_week()
    all_weeks = _weeks_in_range(earliest_week, current_week)
    missing = []

    existing_weekly = _load_weekly_csv()
    existing_daily = _load_daily_csv()

    for week_str in all_weeks:
        in_weekly = week_str in existing_weekly
        in_daily = _week_has_daily_data(week_str, existing_daily)
        if not in_weekly or not in_daily:
            missing.append(week_str)

    return missing


def _csv_file():
    import toggl.const as _c
    return _c.CSV_FILE


def _daily_csv_file():
    import toggl.const as _c
    return _c.DAILY_CSV_FILE


def _load_weekly_csv():
    path = _csv_file()
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        import csv
        return {row["Week"] for row in csv.DictReader(f)}


def _load_daily_csv():
    path = _daily_csv_file()
    if not os.path.exists(path):
        return {}
    import csv
    result = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            result.setdefault(row["Date"], {}).setdefault(row["Project"], 0.0)
            result[row["Date"]][row["Project"]] += float(row["Hours"])
    return result


def _week_has_daily_data(week_str, daily_data):
    start_d, end_d = get_week_dates(week_str)
    today = date.today()
    # Only require data up to today for the current (partial) week
    cutoff = min(end_d, today)
    week_dates = set(
        (start_d + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((cutoff - start_d).days + 1)
    )
    present = set(d for d in daily_data if d in week_dates)
    return len(present) == len(week_dates)


# ── Backfill single week ─────────────────────────────────────────────────────

def backfill_week(week_str, token, projects_map):
    try:
        weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
    except TogglRateLimitError:
        return {"success": False, "reason": "quota"}

    _patch_weekly_csv(week_str, weekly_data)
    _patch_daily_csv(week_str, daily_data)
    return {"success": True}


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_backfill(token, projects_map):
    init_backfill_db()
    conn = _get_conn()
    now = datetime.now().isoformat()

    cursor = conn.execute(
        "INSERT INTO runs (status, started_at) VALUES (?, ?)",
        ("started", now),
    )
    run_id = cursor.lastrowid

    checkpoint = _get_latest_checkpoint(conn)
    earliest = None

    if checkpoint and checkpoint["earliest_week"]:
        earliest = checkpoint["earliest_week"]
    else:
        earliest = find_earliest_week(token, projects_map)
        if earliest:
            conn.execute(
                "INSERT INTO checkpoints (run_id, earliest_week) VALUES (?, ?)",
                (run_id, earliest),
            )
            conn.commit()

    if earliest is None:
        conn.execute(
            "UPDATE runs SET status=?, finished_at=?, stopped_reason=? WHERE id=?",
            ("success", datetime.now().isoformat(), "no_data", run_id),
        )
        conn.commit()
        conn.close()
        return {
            "status": "success",
            "weeks_discovered": 0,
            "weeks_backfilled": 0,
            "stopped_reason": "no_data",
        }

    missing = find_missing_weeks(earliest)
    if not missing:
        conn.execute(
            "UPDATE runs SET status=?, finished_at=?, stopped_reason=? WHERE id=?",
            ("success", datetime.now().isoformat(), "complete", run_id),
        )
        conn.execute(
            "UPDATE checkpoints SET last_verified_at=?, last_verified_week=? WHERE run_id=?",
            (datetime.now().isoformat(), get_current_week(), run_id),
        )
        conn.commit()
        conn.close()
        return {
            "status": "success",
            "weeks_discovered": 0,
            "weeks_backfilled": 0,
            "stopped_reason": "complete",
        }

    api_requests = 0
    weeks_backfilled = 0
    stopped_reason = "complete"

    for week_str in missing:
        remaining = API_RUN_STATS.get("remaining")
        if remaining is not None and remaining <= 2:
            stopped_reason = "quota"
            break

        result = backfill_week(week_str, token, projects_map)
        api_requests += 1

        if not result["success"]:
            stopped_reason = result.get("reason", "error")
            break

        weeks_backfilled += 1

        conn.execute(
            "UPDATE runs SET weeks_backfilled=?, api_requests_made=? WHERE id=?",
            (weeks_backfilled, api_requests, run_id),
        )
        conn.execute(
            "UPDATE checkpoints SET last_completed_week=?, last_verified_at=? WHERE run_id=?",
            (week_str, datetime.now().isoformat(), run_id),
        )
        conn.commit()

    status = "success" if stopped_reason == "complete" else "failed"
    conn.execute(
        "UPDATE runs SET status=?, finished_at=?, weeks_discovered=?, weeks_backfilled=?, api_requests_made=?, stopped_reason=? WHERE id=?",
        (status, datetime.now().isoformat(), len(missing), weeks_backfilled, api_requests, stopped_reason, run_id),
    )
    conn.commit()
    conn.close()

    return {
        "status": status,
        "weeks_discovered": len(missing),
        "weeks_backfilled": weeks_backfilled,
        "stopped_reason": stopped_reason,
        "api_requests_made": api_requests,
    }


# ── Status ────────────────────────────────────────────────────────────────────

def _get_latest_checkpoint(conn):
    cursor = conn.execute(
        "SELECT earliest_week, last_completed_week, last_verified_at, last_verified_week "
        "FROM checkpoints ORDER BY run_id DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        return {
            "earliest_week": row[0],
            "last_completed_week": row[1],
            "last_verified_at": row[2],
            "last_verified_week": row[3],
        }
    return None


def get_backfill_status():
    if not os.path.exists(BACKFILL_DB):
        return {
            "status": None,
            "earliest_week": None,
            "last_completed_week": None,
            "weeks_backfilled": 0,
            "total_weeks": 0,
        }

    conn = _get_conn()
    cursor = conn.execute(
        "SELECT status, weeks_discovered, weeks_backfilled, stopped_reason "
        "FROM runs ORDER BY id DESC LIMIT 1"
    )
    run_row = cursor.fetchone()

    checkpoint = _get_latest_checkpoint(conn)
    conn.close()

    status_info = {
        "earliest_week": checkpoint["earliest_week"] if checkpoint else None,
        "last_completed_week": checkpoint["last_completed_week"] if checkpoint else None,
    }

    if run_row:
        status_info["status"] = run_row[0]
        status_info["weeks_discovered"] = run_row[1] or 0
        status_info["weeks_backfilled"] = run_row[2] or 0
        status_info["stopped_reason"] = run_row[3]
    else:
        status_info["status"] = None
        status_info["weeks_discovered"] = 0
        status_info["weeks_backfilled"] = 0
        status_info["stopped_reason"] = None

    if status_info["earliest_week"]:
        all_weeks = _weeks_in_range(status_info["earliest_week"], get_current_week())
        status_info["total_weeks"] = len(all_weeks)
    else:
        status_info["total_weeks"] = 0

    return status_info


# ── CSV-only gap detection (no API calls) ────────────────────────────────────

def verify_backfill_needed():
    existing_weekly = _load_weekly_csv()
    existing_daily = _load_daily_csv()

    if not existing_weekly:
        return []

    week_strs = sorted(existing_weekly)
    missing = []

    for week_str in week_strs:
        if not _week_has_daily_data(week_str, existing_daily):
            missing.append(week_str)

    return missing


def run_monthly_verification():
    missing = verify_backfill_needed()
    if not missing:
        return {"needed": False, "missing_weeks": []}
    return {"needed": True, "missing_weeks": missing}
