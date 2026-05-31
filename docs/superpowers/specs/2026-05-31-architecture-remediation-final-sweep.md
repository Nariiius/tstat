# Architecture Remediation — Final Sweep

> After ~15 sessions of refactoring (P1–P4 complete), the remaining analytical work items from the handoff.

## Current State

| File | Lines | Role |
|------|-------|------|
| `toggl/tui.py` | 508 | App shell — tab nav, sync/log/zoom actions, refresh orchestration |
| `toggl/command.py` | 714 | CommandTab + CalendarWidget + graph controls |
| `toggl/panels.py` | 422 | OverviewPanel + SyncPanel |
| `toggl/cache.py` | 763 | DataCache — CSV crud, query methods, sync triggers (god class) |
| `toggl/services/metrics.py` | 251 | MetricsService — business logic |
| `toggl/services/sync.py` | ~30 | History load/save (partial) |
| `toggl/formatters/` | ~300 | cells.py, colors.py, sections.py |

**Tests:** 125 pass; 15 stale snapshot baselines; no unit tests for MetricsService.

## Items

### 1. Stale snapshot baselines
Run `--snapshot-update` to delete 15 unused baselines and fix 1 mismatch.

### 2. DRY category-table rendering
Extract shared section loop from `panels.py:_refresh_categories` and `command.py:_refresh_category_table` into parameterized builder in `formatters/sections.py`. Each existing implementation does identical 3-section (positive/negative/unscored) + logged results rendering differing only in data source and border titles.

### 3. Split cache.py — sync logic → services/sync.py
Move `_patch_daily_csv`, `_patch_weekly_csv`, `fetch_week_data`, `sync_api_to_csv`, `sync_current_week_light` to `services/sync.py`. Update imports in `tui.py` to import sync functions from `services/sync.py`. Keep `DataCache` class, date helpers, and CSV-loading methods in `cache.py`.

### 4. Extract CalendarWidget to `toggl/widgets/calendar.py`
Mechanical extraction of `CalendarWidget` class (lines 40–290 of `command.py`) to new `toggl/widgets/calendar.py`. No logic changes — widget is already decoupled via Messages.

### 5. Add unit tests for MetricsService
New `tests/unit/test_metrics.py` using `tmp_data_dir` fixture + sample CSVs. Test `get_day_metrics`, `get_week_dashboard_rows`, `get_report_sections`, `get_graph_data`, `get_daily_breakdown`, `compute_period_nets`.

### 6. MetricsService caching
Add `_report_sections_cache: dict[tuple, Any]` keyed by `(label, context_type)`. Invalidate on new calls. Simple dict-based memoization.

### 7. Reactive state attributes on TogglTUI
Replace `_data_cache` with `data_cache = reactive[DataCache | None](None)` + `watch_data_cache`. Makes refresh automatic on cache changes.

## Execution Order

1. Snapshot cleanup
2. MetricsService unit tests (safety net)
3. DRY category tables
4. CalendarWidget extraction
5. cache.py → sync.py split
6. MetricsService caching
7. Reactive state attributes

**Verification:** Run full test suite after each item.
