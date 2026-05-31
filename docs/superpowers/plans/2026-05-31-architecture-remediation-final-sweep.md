# Architecture Remediation — Final Sweep Implementation Plan

> **For agentic workers:** Use inline execution. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Complete all 7 remaining architectural items from the handoff: snapshot cleanup, unit tests, category-table DRY, CalendarWidget extraction, cache.py split, MetricsService caching, reactive state.

**Architecture:** Preserve unidirectional dependency direction. Extract shared utilities to `toggl/dates.py` to break circular imports. No logic changes — pure mechanical refactoring + test additions.

**Tech Stack:** Python 3.12+, Textual, pytest, csv fixtures.

---

### Task 1: Stale Snapshot Baselines

- [ ] **Run snapshot update**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/visual/ --snapshot-update -x -q 2>&1 | tail -10
```

Expected: 15 snapshots removed, 1 updated, 126 passed.

- [ ] **Commit**

```bash
git add tests/visual/ && git commit -m "chore: update snapshot baselines (remove 15 stale, fix 1 mismatch)"
```

---

### Task 2: Unit Tests for MetricsService

**Files:**
- Create: `tests/unit/test_metrics.py`
- Modify: (none — new file only)

**Test plan:** Create a MetricsService with a DataCache loaded from sample CSV fixtures. Test each method against known data.

- [ ] **Write `test_metrics.py`**

```python
"""Unit tests for MetricsService business logic."""
import pytest
from datetime import date

from toggl.cache import DataCache
from toggl.services.metrics import MetricsService


class TestMetricsService:
    """MetricsService composes DataCache queries into higher-level metrics."""

    def test_get_day_metrics(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns complete day metrics dict."""
        svc = MetricsService(DataCache.load())
        metrics = svc.get_day_metrics("2023-01-02")

        assert metrics["label"] == "2023-01-02"
        assert metrics["total_hours"] == pytest.approx(2.1)  # 1.5 + 0.6
        assert "net" in metrics
        assert "delta" in metrics
        assert metrics["earned"] >= 0

    def test_get_day_metrics_empty(self, tmp_data_dir, sample_config):
        """Handles empty day with no data."""
        svc = MetricsService(DataCache.load())
        metrics = svc.get_day_metrics("2099-01-01")

        assert metrics["total_hours"] == 0.0
        assert metrics["net"] == 0.0
        assert metrics["earned"] == 0.0
        assert metrics["tracked_negative"] == 0.0

    def test_get_week_dashboard_rows(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Returns 7 rows plus summary."""
        svc = MetricsService(DataCache.load())
        result = svc.get_week_dashboard_rows("2023-W01")

        assert "rows" in result
        assert "summary" in result
        assert len(result["rows"]) == 7
        row = result["rows"][0]
        assert "day" in row
        assert "date" in row
        assert "hours" in row
        assert "net" in row
        assert "is_today" in row

    def test_get_report_sections_week(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """Returns categorized sections for a week."""
        svc = MetricsService(DataCache.load())
        report = svc.get_report_sections("2023-W01", "WEEK")

        assert "positive" in report
        assert "negative" in report
        assert "unscored" in report
        assert "total_points" in report
        assert "total_hours" in report
        assert len(report["results"]) > 0

    def test_get_report_sections_all(self, tmp_data_dir, sample_weekly_csv, sample_config):
        """Returns all-time sections."""
        svc = MetricsService(DataCache.load())
        report = svc.get_report_sections("ALL_TIME", "ALL")

        assert report["total_hours"] > 0
        assert len(report["results"]) > 0

    def test_get_graph_data_net_mode(self, tmp_data_dir, sample_daily_csv, sample_config):
        """get_graph_data computes cumulative net correctly."""
        svc = MetricsService(DataCache.load())
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        dates, values, raw, avg = svc.get_graph_data(dashboard["rows"], "net")

        assert len(dates) == 7
        assert len(values) == 7
        # Cumulative: each value should be >= previous
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1]

    def test_get_graph_data_negative_mode(self, tmp_data_dir, sample_daily_csv, sample_config):
        """get_graph_data returns inverted negative values."""
        svc = MetricsService(DataCache.load())
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        dates, values, raw, avg = svc.get_graph_data(dashboard["rows"], "negative")

        assert len(values) == 7
        # Negative values should be <= 0
        for v in values:
            assert v <= 0

    def test_get_daily_breakdown_day(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Daily breakdown returns individual day entries."""
        svc = MetricsService(DataCache.load())
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        breakdown = svc.get_daily_breakdown(dashboard["rows"], "day")

        assert len(breakdown) > 0
        for entry in breakdown:
            assert "label" in entry
            assert "positive" in entry
            assert "negative" in entry
            assert "net" in entry

    def test_get_daily_breakdown_week(self, tmp_data_dir, sample_daily_csv, sample_config):
        """Weekly breakdown groups by week."""
        svc = MetricsService(DataCache.load())
        dashboard = svc.get_week_dashboard_rows("2023-W01")
        breakdown = svc.get_daily_breakdown(dashboard["rows"], "week")

        assert len(breakdown) > 0
        for entry in breakdown:
            assert entry["label"].startswith("Wk")

    def test_compute_period_nets_day(self, tmp_data_dir, sample_daily_csv, sample_config):
        """compute_period_nets for day mode returns daily + weekly net."""
        svc = MetricsService(DataCache.load())
        result = svc.compute_period_nets(date(2023, 1, 2), date(2023, 1, 2), "day")

        assert "daily_net" in result
        assert "weekly_net" in result
```

- [ ] **Run the new tests to verify they pass**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_metrics.py -v 2>&1 | tail -30
```

Expected: all pass (new file, no dependencies).

- [ ] **Commit**

```bash
git add tests/unit/test_metrics.py && git commit -m "test: add unit tests for MetricsService"
```

---

### Task 3: DRY Category-Table Rendering

**Files:**
- Modify: `toggl/formatters/sections.py` (add `build_category_rows`)
- Modify: `toggl/panels.py` (use new function, lines 307-334)
- Modify: `toggl/command.py` (use new function, lines 474-520)

- [ ] **Add `build_category_rows` to `formatters/sections.py`**

```python
def build_category_rows(aggregate: dict) -> list:
    """Build category table rows from an aggregate data dict.
    
    The aggregate dict must have keys: 'positive', 'negative', 'unscored',
    'positive_results', 'negative_results'.
    Returns a flat list of 4-tuples (name, hours, rate, points) ready
    for DataTable.add_rows().
    """
    rows: list = []
    for section_name in ("positive", "negative", "unscored"):
        section_rows = aggregate[section_name]
        if section_rows:
            rows.append(
                (_fmt_section_header(f"\u2022 {section_name.upper()}"),
                 Text(""), Text(""), Text(""))
            )
        rows.extend(
            _render_category_section(
                section_rows, _fmt_project_tree, _fmt_tree_cells,
                section_color=SECTION_COLORS.get(section_name.upper(), ""),
            )
        )
    if aggregate.get("positive_results"):
        _render_logged_results(rows, aggregate["positive_results"],
                               "\u2022 LOGGED POSITIVE", SECTION_COLORS["LOGGED POSITIVE"])
    if aggregate.get("negative_results"):
        _render_logged_results(rows, aggregate["negative_results"],
                               "\u2022 LOGGED NEGATIVE", SECTION_COLORS["LOGGED NEGATIVE"])
    return rows
```

- [ ] **Update `panels.py:_refresh_categories`**

Replace lines ~308-334 with:

```python
    def _refresh_categories(self, cache, active_week: str) -> None:
        report = MetricsService(cache).get_report_sections("ALL_TIME", "ALL")
        cat_table = self.query_one("#overview-categories-table", DataTable)
        cat_table.clear(columns=False)
        rows = build_category_rows(report)
        self._add_rows_mark_sections(cat_table, rows)
        total_hours = report["total_hours"]
        th_h = int(total_hours)
        th_m = int((total_hours - th_h) * 60)
        cat_table.border_title = f"[b][#63f3ff]Lifetime[/][/]   [#8d98a7]{th_h}hrs {th_m:02d}min[/]"
        cat_table.border_subtitle = f"[#8d98a7]Total {format_signed_rich(report['total_points'])} pts[/]"
```

Add import at top of `panels.py`:
```python
from toggl.formatters.sections import build_category_rows
```

- [ ] **Update `command.py:_refresh_category_table`**

Replace lines ~474-520 with:

```python
    def _refresh_category_table(self, cache: DataCache, start: date, end: date) -> None:
        agg = cache.get_range_aggregate(start, end)
        table = self.query_one("#cmd-category-table", DataTable)
        table.clear(columns=False)

        mode = self.period.mode
        if mode == "day":
            suffix = start.strftime("%a %-d %b")
        elif mode == "week":
            wk = get_week_str(start)
            suffix = f"W{int(wk.split('W')[1])} {start.year}"
        else:
            suffix = start.strftime("%b %Y")

        table.border_title = f"[b][#63f3ff]{suffix}[/][/]"

        svc = MetricsService(cache)
        period_nets = svc.compute_period_nets(cache, start, end, mode)
        subtitle = period_nets.get("subtitle", "Insights coming soon")
        table.border_subtitle = f"[#8d98a7]{subtitle}[/]"

        rows = build_category_rows(agg)
        table.add_rows(rows)
```

Add import:
```python
from toggl.formatters.sections import build_category_rows
```

Remove unused local imports in `_refresh_category_table`:
- `_fmt_section_header`, `_render_category_section`, `_fmt_project_tree`, `_fmt_tree_cells`, `_render_logged_results`, `SECTION_COLORS`

- [ ] **Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: 126+ pass (existing + new MetricsService tests).

- [ ] **Commit**

```bash
git add toggl/formatters/sections.py toggl/panels.py toggl/command.py && git commit -m "refactor: DRY category-table rendering into build_category_rows"
```

---

### Task 4: Extract CalendarWidget

**Files:**
- Create: `toggl/widgets/__init__.py`
- Create: `toggl/widgets/calendar.py`
- Modify: `toggl/command.py` (remove CalendarWidget class, update import)

- [ ] **Create `toggl/widgets/__init__.py`**

Empty file.

- [ ] **Create `toggl/widgets/calendar.py`**

Copy the CalendarWidget class from `command.py` lines 40–~290. Include:
- Imports: `from __future__ import annotations`, `from datetime import date, timedelta`, `from typing import Any`, `from rich.text import Text`, `from textual.message import Message`, `from textual.widgets import Static`, `from toggl.formatters import _net_color, _label_for_day, format_signed_rich`, `from toggl.cache import get_week_dates`, `from toggl.period import PeriodController, PeriodMode`

The exact class:

```python
"""CalendarWidget — month-grid calendar sidebar with heatmap coloring."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from toggl.cache import get_week_dates
from toggl.formatters import _net_color, _label_for_day, format_signed_rich
from toggl.period import PeriodController, PeriodMode


class CalendarWidget(Static):
    """Month-grid calendar sidebar with net-based heatmap coloring."""

    can_focus = True

    class CalendarNav(Message):
        """Navigated to a different anchor date."""
        def __init__(self, anchor_date: date) -> None:
            super().__init__()
            self.anchor_date = anchor_date

    class CalendarDayClicked(Message):
        """User clicked on a specific day in the calendar."""
        def __init__(self, day_date: date) -> None:
            super().__init__()
            self.day_date = day_date

    def __init__(self) -> None:
        super().__init__()
        self._day_net: dict[str, float] = {}
        self._anchor: date = date.today()
        self._period_mode: PeriodMode = "week"
        self._period_ctrl: PeriodController | None = None

    def set_day_net_values(self, net_map: dict[str, float]) -> None:
        self._day_net = net_map

    def set_period_context(self, anchor: date, mode: PeriodMode) -> None:
        self._anchor = anchor
        self._period_mode = mode

    # ... (rest of CalendarWidget implementation)
```

I need the full CalendarWidget code. Let me read it from command.py.

- [ ] **Replace CalendarWidget in `command.py`**

Remove CalendarWidget class definition (lines 40–~290). Add import:
```python
from toggl.widgets.calendar import CalendarWidget
```

- [ ] **Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Commit**

```bash
git add toggl/widgets/ && git commit -m "refactor: extract CalendarWidget to toggl/widgets/calendar.py"
```

---

### Task 5: Split cache.py — Sync Logic to services/sync.py

**Files:**
- Create: `toggl/dates.py` (extract date utilities)
- Modify: `toggl/cache.py` (remove sync functions, import from dates.py)
- Modify: `toggl/services/sync.py` (add sync functions, import from dates.py)
- Modify: `toggl/tui.py` (update imports)
- Modify: `toggl/services/metrics.py` (update imports)
- Modify: `toggl/command.py` (update imports)
- Modify: `toggl/neg.py` (update imports)
- Modify: `toggl/__init__.py` (update imports)
- Modify: `tests/conftest.py` (update imports)
- Modify: `tests/unit/test_cache.py` (update imports)
- Modify: `tests/unit/test_new_fixes.py` (update imports)
- Modify: `tests/e2e/test_tui.py` (update imports)
- Modify: `tests/e2e/test_tui_edge.py` (update imports)
- Modify: `tools/generate_view_snapshots.py` (update imports)
- Modify: `tests/unit/test_command.py` (update imports)

- [ ] **Create `toggl/dates.py`**

Extract all date-related utility functions from cache.py:

```python
"""Date utilities for Toggl data processing."""

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any


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


def get_sunday_of_week(d: date) -> date:
    days_since_sun = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sun)


def _year_first_sunday(year: int) -> date:
    """Sunday on or before Jan 1 of *year*."""
    jan1 = date(year, 1, 1)
    return jan1 - timedelta(days=(jan1.weekday() + 1) % 7)


def get_week_str(d: date) -> str:
    """Return the week label for date *d*."""
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
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: str, content_str: str) -> None:
    """Atomic file write via tmp + replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content_str)
    os.replace(tmp, path)
```

- [ ] **Update `services/sync.py`**

Add the sync functions from cache.py:

```python
"""Sync metadata management + CSV sync logic."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Any

from toggl.const import HISTORY_FILE, CSV_FILE, DAILY_CSV_FILE
from toggl.dates import (
    get_week_dates, get_week_str, get_sunday_of_week, get_iso_format,
    parse_iso, get_current_week, _atomic_write,
)

logger = logging.getLogger("TStat")


def _load_history() -> dict[str, Any]:
    """Load sync history from JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: dict) -> None:
    """Save sync history to JSON file (atomic write)."""
    _atomic_write(HISTORY_FILE, json.dumps(history, indent=4))


def _patch_daily_csv(week_str: str, daily_data: dict[str, dict[str, float]]) -> None:
    start_d, end_d = get_week_dates(week_str)
    week_dates = set((start_d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7))

    existing_rows = []
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    merged = {}
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
                rows.append({"Date": day_str, "Project": proj, "Hours": round(hours, 4)})

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(DAILY_CSV_FILE, buf.getvalue())


def _patch_weekly_csv(week_str: str, weekly_data: dict[str, float]) -> None:
    existing_rows = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

    merged = {}
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
                rows.append({"Week": wk, "Project": proj, "Hours": round(hours, 4)})

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Week", "Project", "Hours"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(CSV_FILE, buf.getvalue())


def fetch_week_data(week_str: str, token: str, projects_map: dict[int, str]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    import urllib.parse
    from toggl.api import toggl_request

    start_d, end_d = get_week_dates(week_str)
    start_iso = get_iso_format(start_d, is_end=False)
    end_iso = get_iso_format(end_d, is_end=True)
    logger.debug("[SYNC] fetch_week_data: week=%s range=[%s \u2192 %s]", week_str, start_iso, end_iso)
    params = urllib.parse.urlencode(
        {"start_date": start_iso, "end_date": end_iso},
        safe=":",
    )
    endpoint = f"me/time_entries?{params}"
    entries = toggl_request(endpoint, token)
    logger.debug("[SYNC] fetch_week_data: API returned %d entries", len(entries) if entries else 0)
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
            daily_data[day_str][proj_name] = daily_data[day_str].get(proj_name, 0.0) + hrs
    logger.debug("[SYNC] fetch_week_data: processed \u2192 %d projects (weekly), %d days (daily)",
                 len(weekly_data), len(daily_data))
    return weekly_data, daily_data


def sync_api_to_csv(weeks_back: int = 4, prompt_on_warning: bool = True) -> dict[str, bool | str]:
    from toggl.api import get_api_token, get_projects_map, _reset_api_stats, _confirm_sync_quota
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


def sync_current_week_light(auto_refresh: bool = False, prompt_on_warning: bool = True) -> dict[str, bool | str]:
    from toggl.api import get_api_token, get_projects_map, is_projects_cache_stale, _reset_api_stats, _confirm_sync_quota
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
    logger.debug("[SYNC] fetch_week_data returned: %d weekly entries, %d daily entries",
                 len(weekly_data) if weekly_data else 0,
                 len(daily_data) if daily_data else 0)
    _patch_weekly_csv(week_str, weekly_data)
    _patch_daily_csv(week_str, daily_data)

    history = _load_history()
    history["last_updated"] = datetime.now().isoformat()
    _save_history(history)
    return {"success": True, "message": "Synced current week"}
```

- [ ] **Update `cache.py`**

Remove the sync functions (lines ~600–763). Replace with re-exports from services/sync:

```python
# Re-export from services.sync for backward compatibility
from toggl.services.sync import (  # noqa: F401
    _patch_daily_csv, _patch_weekly_csv, fetch_week_data,
    sync_api_to_csv, sync_current_week_light,
)
```

Update imports at top of cache.py:
- Remove: `import csv`, `import io`, line `from datetime import datetime, date, timedelta`
- Keep: those that are still needed for DataCache methods
- Add: `from toggl.dates import parse_iso, get_sunday_of_week, _year_first_sunday, get_week_str, get_current_week, get_week_dates, get_iso_format, _atomic_write`

Actually, cache.py still uses:
- `csv` — only in sync functions (being moved) — check if DataCache uses csv... Yes, `_load_weekly`, `_load_daily`, `_load_negatives`, `_load_positives` use csv.DictReader. So keep csv import.
- `io` — only used in sync functions → remove
- `datetime` — still used by DataCache methods
- `os` — still used
- All the date helpers are still needed by DataCache and the module-level functions

Let me just do the update carefully.

- [ ] **Update `tui.py` imports**

Change:
```python
from toggl.cache import (
    DataCache,
    get_cache,
    get_current_week,
    get_last_updated_str,
    needs_auto_update,
    reset_cache,
    sync_api_to_csv,
    sync_current_week_light,
)
```
To:
```python
from toggl.cache import (
    DataCache,
    get_cache,
    get_last_updated_str,
    needs_auto_update,
    reset_cache,
)
from toggl.dates import get_current_week
from toggl.services.sync import sync_api_to_csv, sync_current_week_light
```

- [ ] **Update `services/metrics.py` imports**

Change `from toggl.cache import DataCache, get_week_dates, get_current_week, get_week_str`
To: `from toggl.cache import DataCache` + `from toggl.dates import get_week_dates, get_current_week, get_week_str`

- [ ] **Update `command.py` imports**

Change `from toggl.cache import DataCache, get_week_str`
To: `from toggl.cache import DataCache` + `from toggl.dates import get_week_str`

- [ ] **Update `panels.py`**

The lazy import `from toggl.cache import get_last_updated_str, get_current_week` — `get_current_week` now comes from dates.py, `get_last_updated_str` stays in cache.py.

Change to:
```python
from toggl.cache import get_last_updated_str
from toggl.dates import get_current_week
```

- [ ] **Update `neg.py`**

Change `from toggl.cache import _atomic_write` to `from toggl.dates import _atomic_write`

- [ ] **Update `toggl/__init__.py`**

`from toggl.cache import DataCache, get_cache, reset_cache` — unchanged (these still in cache.py).

- [ ] **Update `tests/conftest.py`**

Change:
```python
from toggl.cache import get_week_dates
```
To:
```python
from toggl.dates import get_week_dates
```

And update the stub_api fixture:
```python
import toggl.cache
monkeypatch.setattr(toggl.cache, "fetch_week_data", _fake_fetch)
```
To:
```python
import toggl.services.sync
monkeypatch.setattr(toggl.services.sync, "fetch_week_data", _fake_fetch)
```

- [ ] **Update `tests/unit/test_new_fixes.py`**

Change:
```python
from toggl.cache import (
    _patch_daily_csv,
    _patch_weekly_csv,
    needs_auto_update,
    parse_iso,
)
```
To:
```python
from toggl.cache import needs_auto_update
from toggl.dates import parse_iso
from toggl.services.sync import _patch_daily_csv, _patch_weekly_csv
```

- [ ] **Update `tests/unit/test_cache.py`**

Add `from toggl.dates import get_week_dates, get_week_str`

- [ ] **Update `tests/unit/test_command.py`**

Lazy imports: change `from toggl.cache import get_week_dates` to `from toggl.dates import get_week_dates`

- [ ] **Update `tests/e2e/test_tui.py` and `tests/e2e/test_tui_edge.py`**

Lazy imports: change `from toggl.cache import get_week_dates` to `from toggl.dates import get_week_dates`

- [ ] **Update `tools/generate_view_snapshots.py`**

Lazy import: change `from toggl.cache import get_week_dates` to `from toggl.dates import get_week_dates`

- [ ] **Update `toggl/widgets/calendar.py`**

Import `get_week_dates` from `toggl.dates` instead of `toggl.cache`.

- [ ] **Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Commit**

```bash
git add toggl/dates.py toggl/services/sync.py toggl/cache.py toggl/tui.py toggl/services/metrics.py toggl/command.py toggl/panels.py toggl/neg.py toggl/widgets/calendar.py tests/ tools/ && git commit -m "refactor: split cache.py — extract dates.py and migrate sync logic to services/sync.py"
```

---

### Task 6: MetricsService Caching

**Files:**
- Modify: `toggl/services/metrics.py`

- [ ] **Add caching to `MetricsService`**

In `__init__`:
```python
self._report_sections_cache: dict[tuple[str, str], dict[str, Any]] = {}
```

Add `_invalidate_cache()` method:
```python
def _invalidate_cache(self) -> None:
    self._report_sections_cache.clear()
```

In `get_report_sections`, add caching:
```python
def get_report_sections(self, label: str, context_type: str) -> dict[str, Any]:
    key = (label, context_type)
    if key in self._report_sections_cache:
        return self._report_sections_cache[key]
    # ... existing logic ...
    result = { ... }
    self._report_sections_cache[key] = result
    return result
```

In `get_day_metrics`, `get_week_dashboard_rows`, call `self._invalidate_cache()` since they query underlying data.

- [ ] **Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Commit**

```bash
git add toggl/services/metrics.py && git commit -m "perf: add report_sections cache to MetricsService"
```

---

### Task 7: Reactive State Attributes

**Files:**
- Modify: `toggl/tui.py`

- [ ] **Add `reactive` import and attribute in `TogglTUI`**

```python
from textual.reactive import reactive
```

Replace `self._data_cache: DataCache | None = None` in `__init__` with:
```python
self.data_cache: DataCache | None = reactive[DataCache | None](None)  # type: ignore[valid-type]
self._initialized = False
self.active_view_index = 0
self.selected_day = date.today().strftime("%Y-%m-%d")
self._table_resize_timer = None
self._active_week = get_current_week()
```

- [ ] **Add `watch_data_cache` watcher**

```python
def watch_data_cache(self, old: DataCache | None, new: DataCache | None) -> None:
    """Automatically refresh views when data_cache changes."""
    if new is not None and old is not new:
        self.refresh_all_views()
```

- [ ] **Update all assignments to `_data_cache` → `self.data_cache`**

In `load_data`:
```python
self.data_cache = DataCache.load()
# Remove: self.refresh_all_views() — watcher handles it
```

In `refresh_all_views`:
```python
if self.data_cache is None:
```

In `refresh_overview_view`:
```python
panel.refresh_data(self.data_cache, self._active_week)
```

In `refresh_command_view`:
```python
cmd_tab.data_cache = self.data_cache
```

In `action_refresh_data`:
```python
self.data_cache = DataCache.load()
# Remove self.refresh_all_views() and self.notify — watcher handles it
self.notify("Reloaded local data")
```

In `_on_sync_done`:
```python
self.data_cache = get_cache()
# Remove self.refresh_all_views()
```

In `action_add_negative`/`action_add_positive`:
```python
self.data_cache = DataCache.load()
# Remove self.refresh_all_views()
```

Wait, but `refresh_all_views` also calls `update_tabs`, `update_status_line`, `update_view_visibility`, `_schedule_resize`. The watcher would only handle the cache reload. Let me think about this.

Currently `refresh_all_views` does:
1. Check data_cache is not None
2. `update_tabs()`
3. `update_status_line()`
4. For each view: `_refresh_view_by_index(idx)`
5. `update_view_visibility()`
6. `_schedule_resize()`

The reactive approach: when `data_cache` changes, auto-rerender the view content. But the other UI state (tabs, status, visibility, resize) isn't related to cache changes.

So the watcher should call refresh_all_views (which already handles all those), and we keep refresh_all_views as-is. But we can remove explicit refresh_all_views() calls after cache assignments since the watcher triggers it automatically.

Wait, but the watcher watches `data_cache`, and some places set `self.data_cache = DataCache.load()` and then immediately call `self.refresh_all_views()`. The watcher would fire during the assignment, so the explicit call is redundant.

Let me be careful about the order. In `action_refresh_data`:
```python
def action_refresh_data(self) -> None:
    load_runtime_settings()
    self._data_cache = DataCache.load()  # was self._data_cache
    self.refresh_all_views()
    self.notify("Reloaded local data")
```

With reactive:
```python
def action_refresh_data(self) -> None:
    load_runtime_settings()
    self.data_cache = DataCache.load()  # triggers watch_data_cache → refresh_all_views
    self.notify("Reloaded local data")  # watcher already triggered refresh
```

But watch_data_cache might not call everything that refresh_all_views does... actually it does call refresh_all_views. Let me keep it simple.

Wait, but there's a subtle issue. `watch_data_cache` fires when the value changes. But in `__init__`, we set `self.data_cache = reactive[DataCache | None](None)`. This initializes it to None. Then in `load_data`, we set `self.data_cache = DataCache.load()`. This change from None to a DataCache triggers the watcher, which calls `refresh_all_views()`. Good.

But in `action_refresh_data`, we do `self.data_cache = DataCache.load()`. Even if the DataCache has different content, it's a new object, so the watcher fires. Good.

In `_on_sync_done`, we do `self.data_cache = get_cache()`. Same thing.

But what about `action_add_negative` and `action_add_positive`? Those call `log_negative_direct(value)` and then `self.refresh_all_views()`. They don't change the cache object. So the watcher won't fire. We'd need:
```python
def action_add_negative(self) -> None:
    def after_input(value: str | None) -> None:
        if value:
            ok, message = log_negative_direct(value)
            self.data_cache = DataCache.load()  # reload + triggers refresh
            if ok:
                self.notify(message)
            else:
                self.notify(message, severity="error")
    self.push_screen(NegativeInputScreen(), after_input)
```

But `log_negative_direct` might already modify the cache state (it writes to a CSV file). So reloading the cache is correct behavior anyway.

Let me also check: `refresh_all_views()` in `load_data` - do we still want to call `update_tabs()` and `update_status_line()` and `update_view_visibility()` when data_cache changes? Yes — status line shows last_updated which depends on cache data.

OK, so the plan is:
1. Add `reactive` import
2. Replace `_data_cache` with `data_cache = reactive[DataCache | None](None)`
3. Add `watch_data_cache` that calls `self.refresh_all_views()`
4. Update all `self._data_cache` references to `self.data_cache`
5. Remove redundant `self.refresh_all_views()` calls that follow `self.data_cache = X`

- [ ] **Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass. Note: e2e tests may need adjustment if they mock `_data_cache`.

- [ ] **Commit**

```bash
git add toggl/tui.py && git commit -m "refactor: replace _data_cache with reactive attribute for auto-refresh"
```

---

### Self-Review & Verification

- [ ] **Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: all tests pass clean.

- [ ] **Final commit**

```bash
git add -A && git commit -m "chore: complete architecture remediation final sweep"
```
