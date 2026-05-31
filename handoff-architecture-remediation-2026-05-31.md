# Handoff: Architecture Remediation — Final State & Remaining Work

> For a fresh agent picking this up. All architectural phases (P1–P4) from `docs/plan/IMPROVEMENT_PLAN.md` and `architecture_review_v4.md` are complete.

---

## Current State (after ~15 sessions of refactoring)

| File | Lines | What it does |
|------|-------|-------------|
| `toggl/tui.py` | 508 | App shell — tab navigator, sync/log/zoom actions, refresh orchestration |
| `toggl/command.py` | 714 | CommandTab + CalendarWidget + graph controls |
| `toggl/panels.py` | 422 | OverviewPanel + SyncPanel (extracted from tui.py) |
| `toggl/cache.py` | 763 | DataCache — CSV crud, query methods, sync triggers |
| `toggl/services/metrics.py` | 251 | MetricsService — business logic (graph data, daily breakdown, period nets) |
| `toggl/services/sync.py` | ~20 | History load/save (extracted from cache.py) |
| `toggl/formatters/` | ~300 | cells.py, colors.py, sections.py — formatting utilities |
| `toggl/screens/dialogs.py` | ~175 | BaseDialog, ConfirmScreen, NegativeInputScreen, PositiveInputScreen |
| `toggl/models/metrics.py` | ~80 | DayMetrics, ProjectResult, ReportSections, SyncStatus, WeekDashboard |

**Tests:** 125 pass (unit + e2e + quality). Pre-existing: 1–16 stale visual snapshot baselines.

**What was removed:** backfill.py (551L), archive/ (474L), CLI dead code from neg.py/api.py, spark tables, 5 dead views, all SQLite artifacts (~810KB), `__pycache__/`.

---

## Completed Phases (all done)

| Phase | Key changes |
|-------|-------------|
| P1 — Delete/Clean | Killed backfill subsystem, extracted CSS→theme.tcss, extracted formatters package, removed dead views/handlers, tui.py 2085→508 |
| P2 — Decouple/Extract | DRY logging, single DataCache, typed models, dialogs in screens/, sync in services/, CalendarWidget decoupled via Messages |
| P3 — Service Layer | MetricsService with DI, async cache loading via `@work`, Config DI in service constructor, CommandTab business logic migrated |
| P4 — Polish | CLI/TUI split (dead code removed), type annotations on 224/235 functions (95%), view-widget extraction (OverviewPanel, SyncPanel) |

---

## Remaining Analytical Work

### 1. Stale snapshot baselines (cosmetic, not urgent)

16 snapshot baselines reference removed views (day-table, week-table, month-table, spark tables). Run to fix:

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/visual/ --snapshot-update
```

### 2. Duplicate category-table rendering (~50 lines × 2)

`OverviewPanel._refresh_categories()` (panels.py:290) and `CommandTab._refresh_category_table()` (command.py:496) both render the same 3-section (positive/negative/unscored) + logged results layout. They differ only in data source (ALL_TIME vs range) and title. Extract into `formatters/sections.py` as a parameterized builder.

### 3. `cache.py` is still the largest file (763 lines)

It remains a god class with 4+ responsibilities:
- CSV I/O (`_load_weekly`, `_load_daily`, `_atomic_write`)
- Query methods (`get_day_metrics`, `get_range_aggregate`, `get_recovery_rows`)
- Cache management (`DataCache.load()`, `reset_cache`, `_cache` singleton)
- Sync triggers (`sync_api_to_csv`, `sync_current_week_light`)

**Idea:** Split into `services/sync.py` (already partial), `repository/csv_repo.py` (data access), and keep `DataCache` as a thin query facade.

### 4. `command.py` still at 714 lines

`CalendarWidget` (250 lines) could be extracted to `toggl/widgets/calendar.py`. It's already decoupled from CommandTab via Messages but lives in the same file.

### 5. No dedicated tests for new modules

| Module | Test file |
|--------|-----------|
| `services/metrics.py` | `tests/unit/test_metrics.py` — **missing** |
| `services/sync.py` | — covered indirectly via cache tests |
| `panels.py` | — covered via e2e tests, no unit tests |
| `screens/dialogs.py` | — covered via e2e tests, no unit tests |
| `models/metrics.py` | — pure dataclasses, trivial |

### 6. Reactive state attributes (architectural)

Phase 4 listed "Replace `refresh_all_views()` with Textual reactive attributes" but it was never implemented. Currently views refresh imperatively via `_refresh_view_by_index()`. Converting to `reactive` attributes on the App or panels would make stale UI architecturally impossible.

Example: `data_cache: DataCache | None = reactive[DataCache | None](None)` with `watch_data_cache` updating all panels automatically.

### 7. MetricsService doesn't cache

Each call to `refresh_overview_view` creates `MetricsService(cache)` and runs queries. For views that query the same data multiple times (categories + insights both run `get_report_sections`), this is wasteful. Light memoization or batch query method would help.

### 8. Config still uses global state

`load_runtime_settings()` mutates module-level globals (`POINTS`, `NEGATIVES`, `RATE_COLORS`, etc.). `MetricsService` accepts `get_daily_target` as DI, but all other config access remains global. Full DI would make every function testable without monkeypatching.

---

## Suggested Skills

When starting work, invoke:

| Skill | When |
|-------|------|
| `skill({name: "brainstorming"})` | Before any new feature or structural change |
| `skill({name: "writing-plans"})` | After a spec is approved |
| `skill({name: "test-driven-development"})` | When adding new functions or fixing bugs |
| `skill({name: "systematic-debugging"})` | If you encounter unexpected test failures |
| `skill({name: "verification-before-completion"})` | Before claiming work is done |
| `skill({name: "requesting-code-review"})` | Before merging or finishing a branch |

---

## Key Architecture Diagrams

### Current dependency direction (unidirectional ✓)

```
tui.py → panels.py, command.py
       → services/metrics.py → cache.py
       → screens/dialogs.py
       → formatters/
```

No circular imports remain. No module imports `tui.py` at runtime.

### View hierarchy

```
TogglTUI (App)
  ├── ScrollableFooter
  ├── OverviewPanel (id="overview-view")
  │     ├── categories-table, recovery-table, recent-log-table, insights
  │     └── [LogNegRequested / LogPosRequested] messages → App
  ├── CommandTab (id="command-view")
  │     ├── GraphWidget, CalendarWidget
  │     ├── cmd-category-table, cmd-daily-table
  │     └── data_cache set by App before refresh_all()
  └── SyncPanel (id="sync-view")
        └── sync-table
```

---

## Design Documents & Plans

| Doc | Path |
|-----|------|
| Architecture review (complete) | `./architecture_review_v4.md` |
| View widget extraction spec | `./2026-05-31-view-widget-extraction-design.md` |
| Phase 4 quick wins plan | `docs/superpowers/plans/2026-05-31-phase4-quick-wins.md` |

---

## Running the project

```bash
# First time setup (gitignored)
cp toggl_config.json.example toggl_config.json
# edit api_token and project/point mappings

python -m app                    # TUI entrypoint
python -m pytest tests/ -x -q    # run tests (125 pass)
python -m pytest tests/visual/ --snapshot-update  # regenerate baselines
```
