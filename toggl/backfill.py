"""Backfill subsystem for Toggl TUI.

Pulls all historical Toggl data (from 2023-01-01 onward) into local CSVs.
Tracks progress in a SQLite DB at ``data/toggl_backfill.db``.
"""

import os
import sqlite3
import time
from datetime import date, datetime, timedelta

from toggl.api import (
    API_RUN_STATS,
    TogglAPIError,
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
    # Toggl API only allows querying time entries from the last 90 days
    low = date.today() - timedelta(days=90)
    high = date.today()

    while low <= high:
        _check_quota_or_wait()
        mid = low + (high - low) // 2
        mid_sunday = get_sunday_of_week(mid)
        mid_week = get_week_str(mid_sunday)

        try:
            weekly_data, daily_data = fetch_week_data(mid_week, token, projects_map)
        except TogglRateLimitError:
            _quota_wait()
            continue

        if _has_week_data(weekly_data, daily_data):
            high = mid_sunday - timedelta(days=1)
        else:
            low = mid_sunday + timedelta(days=7)

    low_sunday = get_sunday_of_week(low)
    low_week = get_week_str(low_sunday)
    if low_sunday > date.today():
        return None
    try:
        weekly_data, daily_data = fetch_week_data(low_week, token, projects_map)
    except TogglRateLimitError:
        _quota_wait()
        weekly_data, daily_data = fetch_week_data(low_week, token, projects_map)
    return low_week if _has_week_data(weekly_data, daily_data) else None


# ── Missing week detection ───────────────────────────────────────────────────

def find_missing_weeks(earliest_week):
    current_week = get_current_week()
    all_weeks = _weeks_in_range(earliest_week, current_week)
    missing = []

    existing_weekly = _load_weekly_csv()
    existing_daily = _load_daily_csv()

    weekly_hours = {}
    weekly_path = _csv_file()
    if os.path.exists(weekly_path):
        import csv
        with open(weekly_path) as f:
            for row in csv.DictReader(f):
                wk = row["Week"]
                hrs = float(row.get("Hours") or 0.0)
                weekly_hours[wk] = weekly_hours.get(wk, 0.0) + hrs

    for week_str in all_weeks:
        in_weekly = week_str in existing_weekly
        in_daily = _week_has_daily_data(week_str, existing_daily, weekly_hours)
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


def _week_has_daily_data(week_str, daily_data, weekly_hours=None):
    start_d, end_d = get_week_dates(week_str)
    week_dates = set(
        (start_d + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(7)
    )
    d_total = 0.0
    for d_str in week_dates:
        if d_str in daily_data:
            d_total += sum(daily_data[d_str].values())

    if weekly_hours is not None:
        w_total = weekly_hours.get(week_str, 0.0)
        # It has daily data if the daily total is at least close to the weekly total
        return (w_total - d_total) < 0.05

    return d_total > 0.0


# ── Backfill single week ─────────────────────────────────────────────────────

def backfill_week(week_str, token, projects_map):
    try:
        weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
    except TogglRateLimitError:
        return {"success": False, "reason": "quota"}
    except TogglAPIError as e:
        return {"success": False, "reason": f"api_error: {e}"}

    _patch_weekly_csv(week_str, weekly_data)
    _patch_daily_csv(week_str, daily_data)
    return {"success": True}


# ── Quota helpers ───────────────────────────────────────────────────────────

MAX_QUOTA_WAIT_SECONDS = 24 * 3600  # max 24 hours total wait before giving up


def _check_quota_or_wait(proactive=True):
    """Check quota; if exhausted and *proactive*, sleep until reset window passes."""
    remaining = API_RUN_STATS.get("remaining")
    if remaining is not None and remaining <= 2 and proactive:
        _quota_wait()


def _quota_wait():
    """Sleep until the quota reset window elapses, then return.
    Prints progress every 60 seconds. Raises RuntimeError after MAX_QUOTA_WAIT_SECONDS."""
    resets_in = _parse_quota_int("resets_in")
    if resets_in is not None and resets_in > 0:
        wait_secs = resets_in + 10
    else:
        wait_secs = 3600  # fallback: 1 hour

    print(f"\n  Quota exhausted — waiting {wait_secs}s for reset...")
    waited = 0
    while waited < wait_secs:
        chunk = min(60, wait_secs - waited)
        time.sleep(chunk)
        waited += chunk
        if waited % 60 == 0 or waited >= wait_secs:
            print(f"  ... waited {waited}s / {wait_secs}s")
    print("  Resuming backfill.\n")


def _parse_quota_int(key):
    val = API_RUN_STATS.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_backfill(token, projects_map):
    init_backfill_db()
    conn = _get_conn()
    try:
        now = datetime.now().isoformat()

        cursor = conn.execute(
            "INSERT INTO runs (status, started_at) VALUES (?, ?)",
            ("started", now),
        )
        run_id = cursor.lastrowid

        checkpoint = _get_latest_checkpoint(conn)
        earliest = None
        last_completed = None

        if checkpoint and checkpoint["earliest_week"]:
            earliest = checkpoint["earliest_week"]
            last_completed = checkpoint.get("last_completed_week")
        else:
            # Check quota before binary search (≈8 API calls)
            _check_quota_or_wait()
            try:
                earliest = find_earliest_week(token, projects_map)
            except (TogglAPIError, TogglRateLimitError) as e:
                conn.execute(
                    "UPDATE runs SET status=?, finished_at=?, stopped_reason=? "
                    "WHERE id=?",
                    ("failed", datetime.now().isoformat(), f"api_error: {e}", run_id),
                )
                conn.commit()
                raise
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
            return {
                "status": "success",
                "weeks_discovered": 0,
                "weeks_backfilled": 0,
                "stopped_reason": "no_data",
            }

        missing = find_missing_weeks(earliest)

        # Resume from checkpoint: skip already-completed weeks
        if last_completed:
            try:
                idx = missing.index(last_completed)
                missing = missing[idx + 1:]
                print(f"  Resuming from checkpoint after {last_completed} "
                      f"({len(missing)} weeks remaining)")
            except ValueError:
                pass  # last_completed not in current missing list

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
            return {
                "status": "success",
                "weeks_discovered": 0,
                "weeks_backfilled": 0,
                "stopped_reason": "complete",
            }

        api_requests = 0
        weeks_backfilled = 0
        stopped_reason = "complete"
        total_wait_seconds = 0

        i = 0
        while i < len(missing):
            week_str = missing[i]

            # Quota pre-check
            remaining = _parse_quota_int("remaining")
            if remaining is not None and remaining <= 2:
                resets_in = _parse_quota_int("resets_in")
                wait_secs = (resets_in + 10) if (resets_in and resets_in > 0) else 3600
                if total_wait_seconds + wait_secs > MAX_QUOTA_WAIT_SECONDS:
                    stopped_reason = "quota_timeout"
                    break
                print(f"\n  Quota exhausted ({remaining} left). "
                      f"Waiting {wait_secs}s for reset...")
                time.sleep(wait_secs)
                total_wait_seconds += wait_secs
                print("  Resuming.\n")
                continue  # retry same week after wait

            result = backfill_week(week_str, token, projects_map)
            api_requests += 1

            if not result["success"]:
                reason = result.get("reason", "error")
                if reason == "quota":
                    # Auto-retry once after quota reset
                    resets_in = _parse_quota_int("resets_in")
                    wait_secs = (resets_in + 5) if (resets_in and resets_in > 0) else 60
                    if total_wait_seconds + wait_secs > MAX_QUOTA_WAIT_SECONDS:
                        stopped_reason = "quota_timeout"
                        break
                    print(f"  Rate limited. Waiting {wait_secs}s...")
                    time.sleep(wait_secs)
                    total_wait_seconds += wait_secs
                    # Retry the same week; if it fails again, stop
                    result = backfill_week(week_str, token, projects_map)
                    api_requests += 1
                    if not result["success"]:
                        stopped_reason = "quota"
                        break
                else:
                    stopped_reason = reason
                    break

            weeks_backfilled += 1

            # Persist progress after every week
            conn.execute(
                "UPDATE runs SET weeks_backfilled=?, api_requests_made=? WHERE id=?",
                (weeks_backfilled, api_requests, run_id),
            )
            conn.execute(
                "UPDATE checkpoints SET last_completed_week=?, last_verified_at=? "
                "WHERE run_id=?",
                (week_str, datetime.now().isoformat(), run_id),
            )
            conn.commit()

            # Rate limit: 1 second between API calls
            if i + 1 < len(missing):
                time.sleep(1)

            i += 1

        status = "success" if stopped_reason == "complete" else "failed"
        conn.execute(
            "UPDATE runs SET status=?, finished_at=?, weeks_discovered=?, "
            "weeks_backfilled=?, api_requests_made=?, stopped_reason=? WHERE id=?",
            (status, datetime.now().isoformat(), len(missing) + (0 if last_completed is None else 1),
             weeks_backfilled, api_requests, stopped_reason, run_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": status,
        "weeks_discovered": len(missing),
        "weeks_backfilled": weeks_backfilled,
        "stopped_reason": stopped_reason,
        "api_requests_made": api_requests,
    }


# ── Status ────────────────────────────────────────────────────────────────────

def _csv_week_count():
    """Count unique weeks in the weekly CSV, or 0 if CSV is missing/empty."""
    weekly_path = _csv_file()
    if not os.path.exists(weekly_path):
        return 0
    import csv
    with open(weekly_path) as f:
        return len({row["Week"] for row in csv.DictReader(f)})


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
            "weeks_discovered": 0,
            "weeks_backfilled": 0,
            "weeks_remaining": 0,
            "total_weeks": 0,
            "requests_used": 0,
            "requests_needed": 0,
            "stopped_reason": None,
        }

    conn = _get_conn()
    cursor = conn.execute(
        "SELECT status, weeks_discovered, weeks_backfilled, api_requests_made, "
        "stopped_reason "
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
        status_info["requests_used"] = run_row[3] or 0
        status_info["stopped_reason"] = run_row[4]
    else:
        status_info["status"] = None
        status_info["weeks_discovered"] = 0
        status_info["weeks_backfilled"] = 0
        status_info["requests_used"] = 0
        status_info["stopped_reason"] = None

    if status_info["earliest_week"]:
        all_weeks = _weeks_in_range(status_info["earliest_week"], get_current_week())
        status_info["total_weeks"] = len(all_weeks)
    elif status_info["weeks_discovered"] > 0:
        # DB has discovered weeks but no earliest_week checkpoint
        status_info["total_weeks"] = status_info["weeks_discovered"]
    else:
        # No DB data — estimate from CSV as fallback
        csv_total = _csv_week_count()
        status_info["total_weeks"] = csv_total
        if csv_total > 0:
            status_info["weeks_discovered"] = csv_total

    # Derived: remaining and estimated requests needed
    completed = status_info["weeks_backfilled"]
    total = status_info["weeks_discovered"] or status_info["total_weeks"]
    status_info["weeks_remaining"] = max(0, total - completed)
    # Each remaining week costs ~1 API request
    status_info["requests_needed"] = status_info["weeks_remaining"]

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
