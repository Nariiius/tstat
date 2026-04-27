"""DataCache — reads all CSVs once per refresh cycle, serves queries from memory."""

import os
import csv
import io
from datetime import datetime, date, timedelta

from toggl.const import (
    CSV_FILE, DAILY_CSV_FILE, NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE,
    HISTORY_FILE,
)
from toggl.config import POINTS, NEGATIVES, POSITIVES, DAILY_TARGET
from toggl.calc import calculate


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
    return urllib_parse_quote(dt.isoformat())


def urllib_parse_quote(s):
    import urllib.parse
    return urllib.parse.quote(s)


# ──────────────────────────────────────────────
# LAST-UPDATED HELPERS
# ──────────────────────────────────────────────
import json


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
        return "Never"
    dt = parse_iso(ts)
    if dt is None:
        return "Never"
    diff = datetime.now() - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
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
# DATA CACHE
# ──────────────────────────────────────────────
class DataCache:
    """Parses all 4 CSV files into memory once, then serves queries from dicts."""

    def __init__(self):
        self.weekly_data: dict[str, dict[str, float]] = {}
        self.daily_data: dict[str, dict[str, float]] = {}
        self.negatives_raw: dict[str, list[dict]] = {}
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


# ──────────────────────────────────────────────
# CACHE SINGLETON
# ──────────────────────────────────────────────
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
# SYNC LOGIC
# ──────────────────────────────────────────────
def _write_daily_csv(day_str, daily_data):
    existing = []
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE, "r", encoding="utf-8") as f:
            existing = [row for row in csv.DictReader(f) if row["Date"] != day_str]
    for proj, hours in daily_data.items():
        if hours > 0:
            existing.append({"Date": day_str, "Project": proj, "Hours": round(hours, 4)})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(existing)
    _atomic_write(DAILY_CSV_FILE, buf.getvalue())


def _patch_weekly_csv(week_str, weekly_data):
    existing = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            existing = [row for row in csv.DictReader(f) if row["Week"] != week_str]
    for proj, hours in weekly_data.items():
        if hours > 0:
            existing.append({"Week": week_str, "Project": proj, "Hours": round(hours, 4)})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Week", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(existing)
    _atomic_write(CSV_FILE, buf.getvalue())


def fetch_week_data(week_str, token, projects_map):
    from toggl.api import toggl_request
    start_d, end_d = get_week_dates(week_str)
    start_iso = get_iso_format(start_d, is_end=False)
    end_iso = get_iso_format(end_d, is_end=True)
    endpoint = f"time_entries?start_date={start_iso}&end_date={end_iso}"
    entries = toggl_request(endpoint, token)
    weekly_data: dict[str, float] = {}
    daily_data: dict[str, float] = {}
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
        day_str = entry.get("start", "")[:10]
        if day_str:
            daily_data[proj_name] = daily_data.get(proj_name, 0.0) + hrs
    return weekly_data, daily_data


def sync_api_to_csv(weeks_back=4, prompt_on_warning=True):
    from toggl.api import get_api_token, get_projects_map, _reset_api_stats, _confirm_sync_quota
    weeks_back = int(weeks_back)
    if weeks_back < 1:
        raise ValueError("--update-all expects a positive number of weeks")
    token = get_api_token()
    _reset_api_stats()
    estimated = weeks_back * 7 + 2
    if not _confirm_sync_quota(token, estimated, "full sync", prompt_on_warning):
        return {"success": False, "message": "Sync cancelled (low quota)"}
    projects_map = get_projects_map(token)
    for i in range(weeks_back - 1, -1, -1):
        sunday = get_sunday_of_week(date.today()) - timedelta(days=7 * i)
        week_str = get_week_str(sunday)
        weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
        _patch_weekly_csv(week_str, weekly_data)
        for d_str, d_projs in daily_data.items():
            _write_daily_csv(d_str, d_projs)
    _save_history({"last_updated": datetime.now().isoformat(), "synced_weeks": {}})
    return {"success": True, "message": f"Successfully synced {weeks_back} week(s)"}


def sync_current_week_light(auto_refresh=False, prompt_on_warning=True):
    from toggl.api import get_api_token, get_projects_map, is_projects_cache_stale, _reset_api_stats, _confirm_sync_quota
    token = get_api_token()
    refresh_projects = is_projects_cache_stale()
    _reset_api_stats()
    estimated = 9 if refresh_projects else 8
    label = "auto-refresh" if auto_refresh else "weekly sync"
    if not _confirm_sync_quota(token, estimated, label, prompt_on_warning):
        return {"success": False, "message": "Sync cancelled (low quota)"}
    projects_map = get_projects_map(token, use_cache=not refresh_projects)
    week_str = get_current_week()
    weekly_data, daily_data = fetch_week_data(week_str, token, projects_map)
    _patch_weekly_csv(week_str, weekly_data)
    for d_str, d_projs in daily_data.items():
        _write_daily_csv(d_str, d_projs)
    _save_history({"last_updated": datetime.now().isoformat(), "synced_weeks": {}})
    return {"success": True, "message": "Synced current week"}
