# Architectural Review — Toggl TUI (Version 4)

---

## What's New in Version 4

Versions 1–3 progressively broadened scope: from source-only analysis (V1), to deeper module inspection (V2), to incorporating the test suite, data layer, and tooling (V3). Version 4 incorporates three new inputs:

1. **SQLite Confirmed Dead** — `toggl.db` and `toggl_backfill.db` are artefacts of a failed migration attempt. The mandate is explicit: delete both files and all code that references them. This reclassifies the "dual storage (SQLite + CSV)" pattern identified in V3 as a dead code problem, not an architectural choice. V3's data layer analysis was built on an incorrect premise.

2. **Backfill Subsystem Retirement** — `backfill.py` (552 lines) is built around SQLite throughout its core logic. With SQLite mandated for deletion, the entire backfill subsystem is retired. `tests/unit/test_backfill.py` becomes correspondingly dead. Backfill orchestration code in `tui.py` and cache references in `cache.py` are also deleted. The total confirmed dead code count rises from ~430 lines (V3, all within `tui.py`) to approximately **1,350 lines** spread across the codebase.

3. **V3 Reviewer Feedback Incorporated** — Three new sections are added: **Complexity Hotspots** (Section 9), **Change Risk Analysis** (Section 10), and **What Should NOT Be Refactored** (Section 11). The overall architecture score is revised from 3.5 to **4/10** to reflect the test suite and isolated modules. Model introduction is moved from Phase 3 into Phase 1. The "tui.py goes to ~550 lines" line-count prediction is removed. The SQLite migration recommendation (Phase 5 in V3) is removed entirely.

No findings from V1, V2, or V3 have been retracted.

**Overall Architecture Score: 4/10** (revised upward from 3.5 per V3 reviewer feedback; the additional dead code from SQLite retirement partially offsets the increase)

---

## Executive Summary

The Toggl TUI is a Python Textual application for personal time-tracking analytics, approximately 5,300 lines in the core package with a supporting test suite, tooling, and data layer. It is functional and actively maintained.

**This is not a badly engineered project.** It is a project that grew successfully past the size where its original architecture remains comfortable. The main issue is not correctness — it is that three files (`tui.py`, `command.py`, `cache.py`) became the default destination for all new functionality. The codebase needs architectural consolidation, not a rewrite.

The most significant new finding in V4 is that **the SQLite integration is confirmed dead code from a failed migration**. Combined with the dead code identified in V3, the project now carries approximately **1,350 lines of confirmed dead code** and **~810 KB of dead files** before any refactoring begins. Deleting all of this — at near-zero risk — is the single highest-value first step and clears the view to the actual architecture underneath.

The remaining core problem is **responsibility leakage**: app shell, CSS, UI rendering, business rules, data access, and sync orchestration are interleaved within the same classes and methods. A change to how a table cell formats a number requires touching the same file as a change to sync orchestration logic.

The good news: `period.py`, `graph.py`, `category.py`, and `rate_colors.py` are well-scoped, testable, single-purpose modules. The refactoring path is about making everything else look like those.

---

## 1. Architectural Health Scorecard

| Dimension | V1/V2 | V3 | V4 | Notes |
|---|---|---|---|---|
| **Separation of Concerns** | 2/10 | 2/10 | 2/10 | `tui.py`, `cache.py`, `command.py` each mix 4+ responsibilities |
| **Testability** | 3/10 | 4/10 | 4/10 | Four-tier test suite exists; architecture still prevents true unit isolation |
| **DRY** | 3/10 | 3/10 | 3/10 | 6× logged-section; 6× net calculation; 3× neg/pos function pairs |
| **Module Boundaries** | 3/10 | 3/10 | 3/10 | Sync in cache, CLI in neg, formatters in tui, CLI output in api |
| **Type Safety** | 2/10 | 2/10 | 2/10 | Raw dicts and tuples throughout; `models/` directory is empty |
| **Dead Code** | 2/10 | 2/10 | **1/10** | ~1,350 confirmed dead lines; ~810 KB dead files; entire subsystem retired |
| **Dependency Direction** | 4/10 | 4/10 | 4/10 | Circular `command ↔ tui`; global state; some modules well-isolated |
| **Code Organisation** | 4/10 | 4/10 | 4/10 | Flat structure; empty scaffolding directories |
| **State Management** | 3/10 | 3/10 | 3/10 | Mutable globals; dual cache instances; manual view refresh |
| **Scalability** | 4/10 | 4/10 | 4/10 | Adding a new view requires editing the god class |
| **Data Layer Clarity** | — | 3/10 | **2/10** | "Dual storage" was a mischaracterisation; SQLite was dead code; CSV-only but unstructured |

**Overall: 4/10**

The V3 reviewer correctly argued that 3.5/10 understated the positive attributes: a four-tier test suite, four well-scoped foundation modules, structured tooling, and `AGENTS.md` are uncommon in projects of this scale. The revision to 4/10 acknowledges this.

Dead Code drops from 2/10 to 1/10: the total confirmed dead code is now ~1,350 lines — including an entire 552-line subsystem built on a failed migration — alongside ~810 KB of dead files. Data Layer Clarity drops from 3/10 to 2/10 because V3's "dual storage design" finding was based on a misread; the layer was always CSV-only, with the SQLite code being an abandoned experiment that was never integrated into the active pipeline.

---

## 2. Project Structure Overview

```
.
├── AGENTS.md                         # Agent instructions ✓
├── TogglTrack.py                     # Main entry point  ← rename to main.py or __main__.py
├── app.py                            # App launcher      ← consolidate with TogglTrack.py
├── requirements.txt
├── toggl_config.json                 # Local config (gitignored) ✓
├── toggl_config.json.example         # Config template ✓ good practice
├── snapshots_savepoint.html          # ← DELETE (678 KB; gitignore)
│
├── archive/                          # ← DELETE ENTIRELY
│   ├── TogglTrack.py.bak             #   133 KB backup; Git handles history
│   └── cli.py                        #   Unused CLI
│
├── data/
│   ├── toggl.db                      # ← DELETE (SQLite; failed migration artefact)
│   ├── toggl_backfill.db             # ← DELETE (SQLite; failed migration artefact)
│   ├── toggl_data.csv                # Primary time entry data ✓
│   ├── toggl_daily.csv               # Aggregated daily totals ✓
│   ├── toggl_negatives.csv           # Logged negatives ✓
│   ├── toggl_positives.csv           # Logged positives ✓
│   ├── toggl_projects.json           # Project definitions cache ✓
│   ├── toggl_sync_history.json       # Sync state metadata ✓
│   ├── layout_debug.log              # ← Move to logs/ (not user data)
│   └── sync_debug.log               # ← Move to logs/ (not user data)
│
├── toggl/                            # Core application package
│   ├── __init__.py                   # ← Triggers config-load chain on import (fix)
│   ├── api.py       (286L)
│   ├── backfill.py  (552L)           # ← DELETE (SQLite-dependent; subsystem retired)
│   ├── cache.py     (845L)
│   ├── calc.py      (72L)
│   ├── category.py  (55L)            # ✓ Well-scoped
│   ├── command.py   (872L)
│   ├── config.py
│   ├── const.py     (96L)
│   ├── graph.py     (228L)           # ✓ Well-scoped
│   ├── neg.py       (243L)
│   ├── period.py    (259L)           # ✓ Well-scoped
│   ├── rate_colors.py (34L)          # ✓ Well-scoped
│   ├── tui.py       (2,086L)
│   ├── components/                   # Empty — populate during refactor
│   ├── managers/                     # Empty — populate or delete
│   └── models/                       # Empty — populate in Phase 1
│
├── tests/
│   ├── conftest.py
│   ├── TEST_SUMMARY.md
│   ├── VISUAL_TESTING.md
│   ├── test_btn.py
│   ├── e2e/
│   │   ├── test_tui.py
│   │   └── test_tui_edge.py
│   ├── ui_quality/
│   │   └── test_quality.py
│   ├── unit/
│   │   ├── test_backfill.py          # ← DELETE (module retired)
│   │   ├── test_cache.py
│   │   ├── test_calc.py
│   │   ├── test_command.py
│   │   ├── test_config.py
│   │   ├── test_neg.py
│   │   └── test_new_fixes.py
│   └── visual/
│       ├── test_snapshots.py
│       └── __snapshots__/            # .raw snapshot files
│
└── tools/
    ├── diag.py
    └── generate_view_snapshots.py
```

### Key Structural Observations

**Two entry points** (`app.py` and `TogglTrack.py`) exist at the root. The distinction is not self-evident from the names. A single `main.py` or `__main__.py` would eliminate the ambiguity.

**Data directory is now confirmed CSV-only.** The SQLite files (`toggl.db`, `toggl_backfill.db`) are dead artefacts. After deletion, the data directory contains CSV files, JSON metadata, and debug logs — a coherent picture.

**Debug logs in `data/`** alongside user data is a hygiene issue. `layout_debug.log` and `sync_debug.log` belong in a `logs/` directory with a separate `.gitignore` entry.

**Empty scaffold directories** (`components/`, `managers/`, `models/`) signal that a layered architecture was intended but never implemented. These should be populated during the refactor, not deleted.

---

## 3. Textual Architecture Review

*Unchanged from V3.*

### 3.1 Widget-to-Parent Coupling

`CalendarWidget` holds a direct reference to its parent `CommandTab` and calls methods on it:

```python
# command.py:170 — widget calling parent method directly
self.parent._on_zoom_out()
```

Widgets must never import or hold references to their parents. This is an explicit anti-pattern in Textual's architecture. The consequence is that `CalendarWidget` cannot be instantiated, tested, or reused outside of `CommandTab`. The fix is for `CalendarWidget` to emit a typed Textual `Message` upward, which `CommandTab` listens for:

```python
class CalendarWidget(Widget):
    class ZoomOut(Message): pass
    class DateSelected(Message):
        def __init__(self, date: date) -> None:
            self.date = date
            super().__init__()

def on_calendar_widget_zoom_out(self, event: CalendarWidget.ZoomOut) -> None:
    ...
```

### 3.2 State Ownership Ambiguity

State is distributed across multiple owners with no clear hierarchy:

- `TogglTUI` holds `selected_day` and `_data_cache`
- `CommandTab` holds its own `PeriodController` and `selected_date`
- `CommandTab.refresh_all()` calls `DataCache.load()` independently (command.py:487), creating a **second cache instance** separate from the one on `TogglTUI` (tui.py:927)

Two separate snapshots of CSV data can exist in memory simultaneously with no consistency guarantee. If a sync event updates the App's cache but `CommandTab` rebuilds its own, the Command view silently shows stale data. State should flow downward: the `App` owns a single `DataCache` instance and passes it to screens.

### 3.3 Manual View Refresh vs Reactive Properties

Views are updated by calling explicit `refresh_all_views()` after every state mutation. This is fragile: any call site that modifies state without triggering the refresh function will silently display outdated data. Textual's `reactive` descriptors exist precisely for this. A correctly architected Textual app does not need a `refresh_all_views()` function — reactive state changes automatically invoke the corresponding `watch_*` methods.

---

## 4. Data Layer Analysis (Revised)

*V3 characterised the data layer as "dual storage (SQLite + CSV)." That characterisation was incorrect. SQLite is confirmed dead code from a failed migration attempt. The data layer is, and always was, CSV-only.*

### 4.1 Actual Storage Architecture

| File | Format | Purpose |
|---|---|---|
| `toggl_data.csv` | CSV | Primary time entry data |
| `toggl_daily.csv` | CSV | Aggregated daily totals |
| `toggl_negatives.csv` | CSV | Logged negative activities |
| `toggl_positives.csv` | CSV | Logged positive activities |
| `toggl_projects.json` | JSON | Project definitions cache |
| `toggl_sync_history.json` | JSON | Sync state metadata |
| `toggl.db` | SQLite | **← DELETE: failed migration artefact** |
| `toggl_backfill.db` | SQLite | **← DELETE: failed migration artefact** |

The two SQLite files are not part of the active data pipeline. They are artefacts of a migration that was started and abandoned.

### 4.2 Impact on the Backfill Subsystem

`backfill.py` (552 lines) is the sole consumer of the SQLite databases. Its core functions — `find_earliest_week()`, `run_backfill()`, `_record_processed_week()`, `_is_week_processed()` — are built around SQLite for progress tracking, deduplication, and state management. With SQLite deleted, these functions have no storage mechanism. The backfill subsystem is retired.

**Cascading deletions required:**

| Target | Lines | Action |
|---|---|---|
| `backfill.py` | 552 | Delete entirely |
| `tests/unit/test_backfill.py` | ~200–250 | Delete entirely (tests a retired module) |
| Backfill orchestration in `tui.py` | ~50–80 | Delete (calls into deleted module) |
| Backfill-related references in `cache.py` | ~20–30 | Delete |
| `toggl.db` | — | Delete file |
| `toggl_backfill.db` | — | Delete file |

**Combined impact:** approximately **650–700 additional confirmed dead lines**, on top of the ~430 identified in V3.

### 4.3 CSV as Primary Storage — Corrected Assessment

V3 suggested migrating CSV storage to SQLite, reasoning that "SQLite is already a project dependency." That argument is now void. **The SQLite migration recommendation is removed entirely.** SQLite was attempted and abandoned; the project is CSV-only and should stay that way for the scope of this refactor.

The structural concerns about CSV storage remain real but are not blockers:

- Appending rows requires careful atomic file rewrite logic (`_patch_weekly_csv`, `_patch_daily_csv`) rather than a simple `INSERT`
- No transactions — a crash mid-write corrupts data irreversibly
- All queries require loading the entire file into memory
- Schema changes require custom migration logic

These are the existing constraints of the project. `DataCache` can be made dramatically simpler by extracting its non-CSV responsibilities (metrics calculation, sync orchestration) into services, without touching the storage format at all.

### 4.4 Log File Location

`layout_debug.log` and `sync_debug.log` live in `data/` alongside persistent user data files. These are debug artefacts. They belong in a `logs/` directory with a separate `.gitignore` entry.

---

## 5. Module Analysis

### 5.1 Current Architecture Diagram (Updated)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TogglTrack.py / app.py                          │
│                       (two entry points)                            │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     tui.py  (~2,086 lines)                          │
│  TogglTUI — 7+ Responsibilities (backfill orchestration → deleted)  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  • App shell + navigation                                    │   │
│  │  • View composition (Overview, Command, Sync)                │   │
│  │  • ~900 lines of embedded CSS                                │   │
│  │  • Modal screens (BaseDialog, ConfirmScreen, Input dialogs)  │   │
│  │  • ScrollableFooter widget                                   │   │
│  │  • ~200 lines of formatting utility functions                │   │
│  │  • View refresh methods (multiple dead)                      │   │
│  │  • Sync orchestration                                        │   │
│  │  • Negative/positive logging actions                         │   │
│  │  • Table column auto-sizing algorithm (~119 lines)           │   │
│  │  • ~215 lines of disabled spark rail code                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└───────┬──────────┬──────────┬──────────┬───────────┬────────────────┘
        │          │          │          │           │
        ▼          ▼          ▼          ▼           ▼
  command.py   cache.py   api.py   config.py    neg.py
  (872L)       (845L)     (286L)               (243L)

  ╔══════════════════════════════╗
  ║  backfill.py (552L) DELETED  ║  ← SQLite-dependent; retired
  ╚══════════════════════════════╝

        │          │
        ▼          ▼
    graph.py ✓  calc.py     period.py ✓
                                │
                                ▼
                      category.py ✓   rate_colors.py ✓   const.py

✓ = well-scoped, single-purpose module
```

### 5.2 Dependency Graph (Updated)

```
app.py ──► TogglTrack.py ──► tui.py ──────────────────────► api.py
                    │          │                              │
                    │          ├──► cache.py ◄──────────────┘
                    │          │       │
                    │          ├──► calc.py
                    │          ├──► config.py ──► const.py
                    │          │                   └──► rate_colors.py
                    │          │                   └──► category.py
                    │          ├──► command.py ──► cache.py
                    │          │       │       ──► graph.py ✓
                    │          │       │       ──► period.py ✓
                    │          │       └──► tui.py  ← CIRCULAR
                    │          └──► neg.py ──► cache.py
                    │
                    └──► config.py

  [backfill.py removed from graph]

CIRCULAR: command.py imports toggl.tui at runtime;
          tui.py imports CommandTab from command at module level
```

> The circular dependency between `command.py` and `tui.py` remains. Neither module can be imported or tested in true isolation.

---

## 6. Detailed Findings

### 6.1 God Classes

#### `TogglTUI` — tui.py

| Attribute | Value |
|---|---|
| Lines | ~2,086 total; ~1,430 logic after deleting backfill orchestration (~60L) and before CSS/formatter extraction |
| Responsibilities | 7+ |
| Severity | Critical |

`TogglTUI` conflates: app shell and navigation, view composition for three screens, ~900 lines of embedded CSS, view refresh methods (multiple dead), modal screen classes, a custom `ScrollableFooter` widget, ~200 lines of formatting utility functions, sync orchestration, negative/positive logging actions, and a 119-line table column auto-sizing algorithm. A change to the visual format of a points cell requires editing the same file as a change to sync quota logic.

#### `DataCache` — cache.py

| Attribute | Value |
|---|---|
| Lines | ~845 total; ~820 after removing backfill references |
| Responsibilities | 4 |
| Severity | High |

`DataCache` is simultaneously a CSV parser and repository, a query service, a metric calculator (computing earned/net/delta), and a view-model builder. Methods like `get_week_dashboard_rows()` return data structured for a UI table — including `is_today` flags and `date_short` formatted strings — from a class that claims to be a data cache. The data layer is coupled to the presentation layer.

#### `CommandTab` — command.py

| Attribute | Value |
|---|---|
| Lines | ~872 |
| Responsibilities | 5 |
| Severity | High |

`CommandTab` mixes: UI layout, data aggregation, graph data transformation, category table rendering, statistics computation, calendar widget management, and period navigation. Its `refresh_all()` method rebuilds a graph, calendar, multiple tables, statistics, and control states in a single 60-line sweep.

---

### 6.2 God Functions

| Function | File | Lines | Problem |
|---|---|---|---|
| `run_backfill` | backfill.py:263–430 | 167 | **DELETED with backfill subsystem** |
| `_resize_tables` | tui.py:1964–2083 | 119 | Complex column-width algorithm with nested loops referencing dead widget selectors |
| `refresh_overview_view` | tui.py:1451–1544 | 93 | Queries data, formats cells, builds rows, and sets border titles for 4 panels |
| `refresh_week_view` | tui.py:1354–1449 | 95 | References non-existent widgets; entirely dead |
| `refresh_all` | command.py:481–541 | 60 | Graph + calendar + tables + stats + controls in one method |
| `_refresh_daily_table` | command.py:629–736 | 107 | Aggregation + 3 mode branches + formatting |
| `_refresh_category_table` | command.py:545–625 | 80 | Aggregation + net computation + table rebuild + runtime tui import |
| `get_week_dashboard_rows` | cache.py:358–398 | 40 | View-model construction (UI concerns) inside the data layer |
| `_refresh_spark_catchup` | tui.py:1289–1351 | 62 | Rate grouping + hours computation inside a UI method that is never called |

---

### 6.3 Circular Dependencies

| Cycle | Mechanism | Impact |
|---|---|---|
| `command.py` ↔ `tui.py` | `command.py` does `import toggl.tui as _tui` at runtime; `tui.py` does `from toggl.command import CommandTab` at module level | Cannot import, test, or reason about either module in isolation |
| `cache.py` → `api.py` | Sync logic in `cache.py` imports from `api.py` at module level (~line 799) | Data persistence layer depends on HTTP transport layer |
| `neg.py` → `cache.py` (deferred) | `neg.py` uses `_atomic_write` from `cache.py` via deferred import | Hidden, load-order-sensitive dependency chain |

---

### 6.4 Tight Coupling and Hidden Dependencies

| Coupling | Location | Impact |
|---|---|---|
| `CalendarWidget` calls `self.parent._on_zoom_out()` | command.py:170 | Not independently instantiable, reusable, or testable |
| `CommandTab._refresh_category_table()` imports `toggl.tui` at runtime | command.py:546 | Circular import; formatting functions hardwired to app shell module |
| `DataCache` imports `POINTS`, `NEGATIVES`, `POSITIVES` at module scope | cache.py:15 | Cannot test with different configs without monkeypatching |
| `calculate()` reads global `POINTS` | calc.py:47 | Returns silently incorrect results if config was not loaded first |
| `_cache` module-level singleton | cache.py:661 | Tests must call `reset_cache()` explicitly or receive stale state |
| `const.py` creates `DATA_DIR` on import | const.py:82 | Filesystem side effect fires at import time |
| `__init__.py` calls `load_runtime_settings` and `calculate` on import | \_\_init\_\_.py:3 | Importing the `toggl` package triggers the full config-loading chain |

---

### 6.5 Duplicate Logic

**Logged positive/negative section rendering — 6 copies**

This ~15-line block exists identically at:

- `tui.py:1429–1440` — `refresh_week_view` (positive + negative) — also dead code
- `tui.py:1473–1484` — `refresh_overview_view` (positive + negative)
- `tui.py:1571–1582` — `refresh_day_view` (positive + negative) — also dead code
- `command.py:607–623` — `_refresh_category_table` (positive + negative)

Any change to how a logged category is displayed requires six edits in two files. Extracting `render_logged_section(table, results, mode)` into `formatters/sections.py` reduces this to one function with call sites.

**Net calculation — 6 copies**

The formula `net = earned - tracked_neg - logged_neg + logged_pos` appears at:

- `cache.py:342` — `get_day_metrics`
- `cache.py:452` — `get_yearly_day_net_map`
- `cache.py:500` — `get_monthly_aggregates`
- `cache.py:551` — `get_daily_data_for_range`
- `tui.py:1168` — `_refresh_spark_weeks` (dead code)
- `tui.py:1206` — `_refresh_spark_days` (dead code)

**`neg.py` function pairs — ~90% identical**

Three pairs that differ only in mode (negative vs positive):

- `log_negative_direct` / `log_positive_direct`
- `print_neg_log` / `print_pos_log` (two 43-line functions, structurally identical)
- `pick_negative_interactive` / `pick_positive_interactive`

All six should be unified into `log_activity_direct(mode, ...)` parameterised on mode.

---

### 6.6 Dead and Vestigial Code (Updated)

**New in V4 — SQLite retirement:**

| Code | Location | Evidence |
|---|---|---|
| `backfill.py` | toggl/ | Entire 552-line file: SQLite-dependent; subsystem retired |
| `tests/unit/test_backfill.py` | tests/unit/ | Tests a deleted module |
| Backfill orchestration in `tui.py` | tui.py ~50–80L | Calls into deleted `backfill.py` |
| Backfill references in `cache.py` | cache.py ~20–30L | Imports/calls into deleted `backfill.py` |
| `toggl.db` | data/ | Failed migration artefact; not part of active pipeline |
| `toggl_backfill.db` | data/ | Failed migration artefact; not part of active pipeline |

**Carried from V3 — confirmed dead in `tui.py`:**

| Code | Location | Evidence |
|---|---|---|
| `refresh_week_view()` | tui.py:1354–1449 | References `#week-table`; does not exist in `compose()` |
| `refresh_day_view()` | tui.py:1546–1596 | References `#day-table`; does not exist |
| `refresh_month_view()` | tui.py:1700–1711 | References `#month-table`; does not exist |
| `action_nav_month_prev/next` | tui.py:1783–1798 | References `#month-table` |
| `month_row_highlighted` handler | tui.py:1725–1737 | Tests `active_view_index == 3`; only 0–2 exist |
| `update_selected_day` for `#week-table` | tui.py:1715–1723 | Widget does not exist |
| `_skip_section_rows` dead selectors | tui.py:1113–1115 | Both selectors are dead |
| `_sync_week_table_cursor` | tui.py:1739–1745 | References `#week-table` |
| `refresh_spark_tables()` | tui.py:1133–1134 | Body is `pass`; never does anything |
| `_refresh_spark_weeks()` | tui.py:1136–1210 | `#spark-rail` is `display: none` in CSS |
| `_refresh_spark_days()` | tui.py:1212–1286 | Never called |
| `_refresh_spark_catchup()` | tui.py:1289–1351 | Never called |
| `#spark-rail` CSS + container | tui.py:708–715, 968–969 | Hidden empty sidebar |
| `_resize_tables` dead selectors | tui.py:1968–1972 | References removed widgets |
| `get_negative_catalog_rows()` / `get_positive_catalog_rows()` | calc.py:60–65 | No callers |
| `format_signed()` | calc.py:68–71 | Duplicate of `format_signed_rich()`; no callers |

**Dead files:**

| Target | Size | Reason |
|---|---|---|
| `archive/TogglTrack.py.bak` | 133 KB | Git handles history |
| `archive/cli.py` | — | Unused CLI |
| `snapshots_savepoint.html` | 678 KB | Gitignore and delete |

**Total confirmed dead code: approximately 1,350 lines across the codebase, plus ~810 KB of dead files.**

This represents roughly **25% of the active codebase** by line count. Deleting it is near-zero risk. The architecture underneath is cleaner than the current state suggests.

---

### 6.7 State Management Problems

| Problem | Location | Impact |
|---|---|---|
| Mutable module-level globals | config.py:124–130 | `POINTS`, `NEGATIVES`, `POSITIVES` are dicts mutated in-place by `load_runtime_settings()` |
| Config imported by reference at module scope | calc.py:3, cache.py:15 | Works only because `.clear()` + `.update()` mutates in-place; assigning `POINTS = {}` anywhere leaves other modules with stale references |
| No reactive state | `TogglTUI` | Views manually refreshed; any missed call site produces a stale UI |
| Two `DataCache` instances | tui.py:927, command.py:487 | App cache + independent `DataCache.load()` in `CommandTab.refresh_all()` |
| Distributed active-date state | tui.py, command.py | `selected_day` on App, `selected_date` in `CommandTab` — no single source of truth |

---

### 6.8 No Domain Model Layer

Data flows throughout the codebase as raw Python dicts and tuples with string keys:

```python
# Representative pattern — raw dict with magic string keys
metrics = cache.get_day_metrics(date)
earned = metrics["earned"]     # Silent KeyError if key name changes
net    = metrics["net"]
delta  = metrics["delta"]
```

The `toggl/models/` directory exists but contains only `__pycache__`. The downstream effects are: no IDE autocomplete for data attributes; key name typos fail silently at runtime; renaming a field requires grep-and-replace across all callers in every layer; tests cannot inspect model state without knowing the full dict schema.

---

### 6.9 Performance and Lifecycle Issues

**Full table rebuilds on every navigation event.** `refresh_all()` clears all rows from `DataTable` widgets and repopulates them on every keypress. Textual supports surgical cell updates and reactive row properties.

**Synchronous CSV parsing on the main thread.** `DataCache.load()` parses CSV files synchronously. If data files grow or disk I/O is slow, this will block the Textual event loop. Long operations should be dispatched via `asyncio.to_thread()` or a Textual `Worker`.

**Full cache reload on sync events.** `load_runtime_settings()` and `reset_cache()` appear to re-parse all four CSVs from scratch after every sync. An incremental update strategy would be substantially more efficient.

---

### 6.10 Module Boundary Violations

| Symptom | Evidence |
|---|---|
| Sync logic in `cache.py` | `sync_api_to_csv`, `sync_current_week_light`, `fetch_week_data`, `_patch_weekly_csv`, `_patch_daily_csv` — 165 lines of sync/HTTP/CSV-patching in the data cache module |
| CLI output in `api.py` | `check_quota`, `_print_api_usage_summary`, `_confirm_sync_quota` print to stdout with ANSI colour codes — transport logic printing to the terminal |
| CLI functions in `neg.py` | `log_negative`, `pick_negative_interactive`, `print_neg_log` — CLI-only functions in a module also imported by the TUI |
| Formatter functions in `tui.py` | `_spark_net_rich`, `fmt_rate`, `fmt_pts`, `format_signed_rich`, `_fmt_section_header` — ~200 lines of pure formatting utilities in the app shell |
| Presentation concerns in `DataCache` | `get_week_dashboard_rows()` adds `is_today` and `date_short` — view concerns generated inside the data layer |

---

### 6.11–6.13 (Single Responsibility, Dependency Inversion, Feature Envy)

All findings from V3 Sections 6.11–6.13 remain current. The only update: backfill-related entries (e.g., `run_backfill` god function, backfill sync references in `cache.py`) are removed from their respective sections as the subsystem is retired.

---

## 7. Test Suite Analysis (Updated)

### 7.1 Coverage Map (Updated)

| File | Target | Type | Status |
|---|---|---|---|
| `unit/test_calc.py` | `calc.py` | Unit | Active |
| `unit/test_cache.py` | `cache.py` | Unit (filesystem) | Active |
| `unit/test_config.py` | `config.py` | Unit | Active |
| `unit/test_neg.py` | `neg.py` | Unit | Active |
| `unit/test_backfill.py` | `backfill.py` | Unit | **← DELETE (module retired)** |
| `unit/test_command.py` | `command.py` | Unit (Textual) | Active |
| `unit/test_new_fixes.py` | Multiple | Regression | Active |
| `e2e/test_tui.py` | Full app | End-to-End | Active |
| `e2e/test_tui_edge.py` | Full app | Edge cases | Active |
| `visual/test_snapshots.py` | Rendered views | Visual regression | Active |
| `ui_quality/test_quality.py` | Rendered views | Quality checks | Active |
| `test_btn.py` | UI buttons | Smoke | Active |

### 7.2 Testability Challenges Imposed by the Architecture

The architectural problems described in Section 6 create direct obstacles in the test suite.

**Global state contamination.** `POINTS`, `NEGATIVES`, and `POSITIVES` are mutable module-level globals. Every test that exercises `calculate()`, `DataCache`, or `neg.py` must call `load_runtime_settings()` beforehand or monkeypatch the globals. A single test that forgets `reset_cache()` in teardown corrupts state for subsequent tests in the same process. `conftest.py` is obligated to manage this reset explicitly.

**Filesystem dependency in unit tests.** `unit/test_cache.py` tests `DataCache`, which reads CSV files directly. These are not true unit tests — they require writing temporary CSV files or heavily mocking `open` and `csv.reader`. Because there is no domain model layer, it is impossible to inject test data as Python objects; you must write files. If `DataCache` accepted a `list[DayEntry]` instead of parsing a path, unit tests would be trivially fast.

**Circular import problem in `test_command.py`.** Testing `CommandTab` in isolation is structurally difficult because `command.py` imports from `tui.py` at runtime. Any test that imports `command.py` may trigger the full Textual app-loading chain.

**E2E tests carrying disproportionate weight.** When unit tests are hard to write due to tight coupling, the natural tendency is to rely on E2E tests. E2E tests through Textual's `pilot` interface are slower, harder to debug on failure, and provide less precise fault localisation.

**Visual snapshot brittleness.** Snapshot tests compare exact character-level terminal output. Any change to CSS, layout geometry, or colour codes causes snapshot failures requiring `generate_view_snapshots.py` to be re-run. This amplifies the cost of every visual change during active refactoring.

### 7.3 How Refactoring Improves Testability

Once models (Phase 1) and service extraction (Phase 3) are implemented:

- `test_cache.py` can inject `[DayEntry(...), ...]` lists instead of writing CSV files to disk
- `test_calc.py` can call `calculate(projects, points={...})` with no global state
- `test_command.py` can test `CommandView` without triggering `tui.py` imports
- `test_neg.py` can call `log_activity_direct(activity, config=mock_config)` without patching globals
- E2E tests become confirmatory rather than load-bearing, and the snapshot suite stabilises

---

## 8. Tooling and Support Files

*Unchanged from V3.*

**`tools/diag.py`** — Runtime diagnostics utility. Purpose and usage should be documented in `README.md` or `AGENTS.md` so contributors know it exists.

**`tools/generate_view_snapshots.py`** — Generates `.raw` snapshot files used by `visual/test_snapshots.py`. Separating snapshot generation from test execution is the correct pattern.

**`AGENTS.md`** — AI agent instruction file at the project root. The current architectural complexity — circular imports, god classes, mutable global state — makes it significantly harder for an agent to make correct, scoped changes. An agent attempting to modify the net calculation will encounter it in six different locations. Architectural clarity directly improves agent effectiveness; the refactoring roadmap serves human and AI contributors equally.

**`toggl_config.json.example`** — A committed config template alongside a gitignored real config is exactly the right pattern.

---

## 9. Complexity Hotspots (New in V4)

*Answers: "where is the maintenance burden concentrated?"*

| Module | Complexity | Reason |
|---|---|---|
| `tui.py` | **Critical** | 7+ responsibilities; ~2,086 lines; circular dep with `command.py`; ~430L internal dead code; CSS embedded |
| `command.py` | **Very High** | 5 responsibilities; circular dep with `tui.py`; widget-parent coupling |
| `cache.py` | **High** | 4 responsibilities; sync mixed with CSV queries; metric logic in data layer; dual instance problem |
| `backfill.py` | **Deleted** | SQLite-dependent; retired |
| `api.py` | **Medium** | CLI output mixed with HTTP transport; quota management as a side concern |
| `neg.py` | **Medium** | TUI and CLI concerns interleaved; 3× duplicated function pairs |
| `config.py` | **Low** | Config loading; mutable global pattern is a risk but the module is small and focused |
| `calc.py` | **Low** | Small; global `POINTS` dependency is fixable in one targeted change |
| `const.py` | **Low** | Constants and paths; filesystem side effect on import is primarily a test concern |
| `period.py` | **Very Low ✓** | Well-scoped state management; no circular deps |
| `graph.py` | **Very Low ✓** | Well-scoped Textual widget; no circular deps |
| `category.py` | **Very Low ✓** | Tiny; single-purpose; no downstream dependencies |
| `rate_colors.py` | **Very Low ✓** | Tiny; single-purpose; no downstream dependencies |

**80% of the maintenance burden lives in three files: `tui.py`, `command.py`, `cache.py`.** A contributor new to the project can safely read and modify any of the green modules without risk of cross-cutting side effects.

---

## 10. Change Risk Analysis (New in V4)

*Answers: "where can I safely start working?"*

| File | Risk if Modified | Reason |
|---|---|---|
| `graph.py` | **Very Low** | Isolated widget; no circular deps; no global state |
| `period.py` | **Very Low** | Isolated state logic; no circular deps |
| `category.py` | **Very Low** | Tiny; no downstream dependencies |
| `rate_colors.py` | **Very Low** | Tiny; no downstream dependencies |
| `calc.py` | **Low** | Small file; global state is the only risk and it's contained |
| `config.py` | **Low–Medium** | Loaded early; mutable globals; changes propagate to all modules that import config values |
| `const.py` | **Low–Medium** | Filesystem side effects on import; changes affect all modules |
| `api.py` | **Medium** | Quota state; CLI output mixed in; API failure modes |
| `neg.py` | **Medium** | Shared TUI + CLI concerns; changes can affect both code paths |
| `cache.py` | **High** | God class; dual instance problem; sync mixed in; any change may affect all views |
| `command.py` | **Very High** | Circular dep with `tui.py`; widget-parent coupling; changes risk breaking either module's import chain |
| `tui.py` | **Critical** | Central god class; circular dep; dead code; CSS embedded; any change risks breaking any view |

**Safe starting points for new contributors:** `graph.py`, `period.py`, `category.py`, `rate_colors.py`. These files can be read, modified, and tested without touching the critical path. `calc.py` and `config.py` are the next step up.

---

## 11. What Should NOT Be Refactored (New in V4)

*Explicitly protecting what is already good prevents over-refactoring and wasted effort.*

**Leave unchanged:**

| Item | Reason |
|---|---|
| `period.py` | Well-scoped, single-purpose, already testable in isolation |
| `graph.py` | Well-scoped Textual widget; no coupling issues |
| `category.py` | Tiny, single-purpose config module |
| `rate_colors.py` | Tiny, single-purpose config module |
| `tools/generate_view_snapshots.py` | Correct pattern; snapshot generation correctly separated from test execution |
| `AGENTS.md` | Good practice; agent workflow documentation |
| `toggl_config.json.example` | Correct pattern; committed template alongside gitignored real config |
| Four-tier test structure (`unit/`, `e2e/`, `visual/`, `ui_quality/`) | The right architecture for this project; do not flatten or merge tiers |
| Snapshot test infrastructure (`.raw` files + snapshot tool) | Correct; do not convert to different snapshot format during refactor |
| `conftest.py` global state management | Necessary reset management given current architecture; simplify only after globals are replaced with DI |

**Planned for relocation rather than rewrite:**

- `period.py` → `state/period.py` (move only; no logic changes)
- `graph.py` → `widgets/graph.py` (move only; no logic changes)
- `calc.py` → `services/calculator.py` (move + rename + add DI parameter; ~20 lines changed)

**Not refactored — deleted:**

- `backfill.py` — retired entirely; not replaced

---

## 12. Proposed Target Architecture

*Unchanged from V3. SQLite does not appear at any layer.*

```
┌─────────────────────────────────────────────────────────────────────┐
│                         App Shell                                   │
│  app.py — TogglTUI(App): navigation, root state, key bindings only  │
├─────────────────────────────────────────────────────────────────────┤
│                     Screens and Widgets (UI Layer)                  │
│  screens/overview.py    screens/command.py    screens/sync.py       │
│  screens/dialogs.py     widgets/calendar.py   widgets/footer.py     │
│  widgets/graph.py       (emit Messages only; never call parents)    │
├─────────────────────────────────────────────────────────────────────┤
│                  Formatters (Pure Functions, no Textual)            │
│  formatters/cells.py    formatters/sections.py    formatters/colors.py │
├─────────────────────────────────────────────────────────────────────┤
│                     Services (Business Logic)                       │
│  services/calculator.py   services/metrics.py    services/sync.py   │
│  services/recovery.py     services/activity_logger.py               │
│  (accept Config + DataCache as constructor args; no Textual imports) │
├─────────────────────────────────────────────────────────────────────┤
│                    Models (Typed Dataclasses)                       │
│  models/metrics.py      models/project.py    models/activity.py     │
│  models/sync_status.py  models/theming.py    (no methods; pure data) │
├─────────────────────────────────────────────────────────────────────┤
│                    Repository / Data Layer                          │
│  data/cache.py      data/api_client.py      data/csv_writer.py      │
│  (I/O only: CSV parse and typed queries, HTTP transport, file writes) │
├─────────────────────────────────────────────────────────────────────┤
│                         Foundation                                  │
│  state/config.py (immutable dataclass)   state/period.py            │
│  const.py                                                           │
└─────────────────────────────────────────────────────────────────────┘
```

**Design rules:**

1. Screens and widgets know only about Models. They call Services to get data and Formatters to render it. They emit Messages upward and never call parent methods.
2. Services contain all business logic. They accept `Config` and `DataCache` as constructor arguments. They never import Textual.
3. Formatters are pure functions taking data and returning Rich Text or plain strings. Zero side effects.
4. `DataCache` is a repository: reads/writes CSV storage, returns Model instances. No business logic, no UI concerns.
5. Models are typed dataclasses. No raw dicts are passed between layers.
6. State flows downward. One `DataCache` instance and one `Config` instance, owned by the App and passed to screens.

---

## 13. Files to Split, Merge, Move, and Delete (Updated)

### Split

| File | Into | Reason |
|---|---|---|
| `tui.py` (2,086L) | `app.py`, `screens/overview.py`, `screens/sync.py`, `screens/dialogs.py`, `widgets/footer.py`, `formatters/cells.py`, `formatters/sections.py`, `styles/theme.tcss` | 7+ responsibilities |
| `cache.py` (845L) | `data/cache.py`, `services/metrics.py`, `services/sync.py`, `data/csv_writer.py` | 4 responsibilities |
| `command.py` (872L) | `screens/command.py`, `widgets/calendar.py` | `CalendarWidget` is independently useful |
| `neg.py` (243L) | `services/activity_logger.py`, `cli/logging.py` | TUI and CLI concerns mixed |
| `api.py` (286L) | `data/api_client.py`, `cli/quota.py` | Transport mixed with CLI output |

### Merge

| Files | Into | Reason |
|---|---|---|
| `rate_colors.py` + `category.py` | `models/theming.py` | Two small, config-driven model files (~90 lines combined) |

### Move (no logic changes)

| File | To | Reason |
|---|---|---|
| `period.py` | `state/period.py` | Pure state management; already well-scoped |
| `graph.py` | `widgets/graph.py` | Already a well-scoped Textual widget |
| `calc.py` | `services/calculator.py` | Business logic; rename clarifies purpose |

### Delete

| Target | Reason |
|---|---|
| `toggl.db`, `toggl_backfill.db` | Failed migration artefacts |
| `backfill.py` (552L) | Entire subsystem retired (SQLite-dependent) |
| `tests/unit/test_backfill.py` | Tests a retired module |
| Backfill orchestration in `tui.py` (~60L) | Calls into deleted module |
| Backfill references in `cache.py` (~25L) | References to deleted module |
| Dead code in `tui.py` (~430L) | Removed view refreshers, spark methods, dead handlers |
| `archive/TogglTrack.py.bak` (133 KB) | Git handles history |
| `archive/cli.py` | Unused CLI |
| `snapshots_savepoint.html` (678 KB) | Gitignore and delete |
| Empty `toggl/components/`, `toggl/managers/` | Populate or remove stubs |

---

## 14. Ideal Project Structure

```
toggl/
├── __init__.py                     # Minimal; does not trigger config loading
├── app.py                          # TogglTUI(App) — shell, navigation, bindings
├── const.py                        # File paths and constants (cleaned up)
│
├── models/
│   ├── __init__.py
│   ├── metrics.py                  # DayMetrics, WeekDashboardRow, ReportSections
│   ├── project.py                  # ProjectResult (name, hours, rate, pts)
│   ├── activity.py                 # LoggedActivity, ActivityAggregate
│   ├── sync_status.py              # SyncStatus
│   └── theming.py                  # CategoryDef, RateColor
│
├── state/
│   ├── __init__.py
│   ├── config.py                   # Config (immutable dataclass), load_config()
│   └── period.py                   # PeriodController (moved; no changes)
│
├── data/
│   ├── __init__.py
│   ├── cache.py                    # DataCache — CSV parse + typed queries ONLY
│   ├── csv_writer.py               # _patch_weekly_csv, _patch_daily_csv, _atomic_write
│   └── api_client.py               # HTTP transport, quota header tracking
│
├── services/
│   ├── __init__.py
│   ├── calculator.py               # calculate() — single canonical net calculation
│   ├── metrics.py                  # get_day_metrics(), get_week_dashboard(), get_report()
│   ├── recovery.py                 # get_recovery_rows()
│   ├── sync.py                     # sync_api_to_csv(), sync_current_week_light()
│   └── activity_logger.py          # log_activity_direct(mode) — replaces neg.py
│
├── screens/
│   ├── __init__.py
│   ├── overview.py                 # OverviewScreen(Screen)
│   ├── command.py                  # CommandScreen(Screen)
│   ├── sync.py                     # SyncScreen(Screen)
│   └── dialogs.py                  # BaseDialog, ConfirmScreen, input dialogs
│
├── widgets/
│   ├── __init__.py
│   ├── graph.py                    # GraphWidget (moved; no changes)
│   ├── calendar.py                 # CalendarWidget (decoupled; emits Messages only)
│   └── footer.py                   # ScrollableFooter
│
├── formatters/
│   ├── __init__.py
│   ├── cells.py                    # fmt_pts_rich, format_signed_rich, fmt_rate, etc.
│   ├── sections.py                 # render_category_section, render_logged_section
│   └── colors.py                   # SECTION_COLORS, _net_color, category/rate color maps
│
└── styles/
    └── theme.tcss                  # All CSS extracted from Python (~900 lines)
```

---

## 15. Refactoring Roadmap (Updated)

Ordered by impact divided by risk — highest value, lowest risk first.

### Phase 1: Delete and Clean Up (Near-Zero Risk, Immediate Impact)

| Task | Effort | Risk | Benefit |
|---|---|---|---|
| Delete `toggl.db`, `toggl_backfill.db` | 5m | None | Removes failed migration artefacts |
| Delete `backfill.py`, `test_backfill.py`; remove references in `tui.py` and `cache.py` | 2h | Very Low | ~650–700 lines deleted; `tui.py` and `cache.py` both shed 20–60 lines |
| Delete confirmed dead code in `tui.py` (spark methods, removed view refreshers, dead handlers) | 2h | Very Low | ~430 lines deleted; large readability gain |
| Extract CSS to `styles/theme.tcss` | 1h | Very Low | ~900 lines leave `tui.py`; enables Textual hot-reload |
| Delete `archive/`, `snapshots_savepoint.html`, empty scaffold dirs | 15m | None | Removes ~810 KB of dead weight |
| Extract formatters to `formatters/cells.py` + `formatters/sections.py` | 2h | Low | Breaks `tui ↔ command` circular dependency; ~200 lines leave `tui.py` |
| DRY: extract `render_logged_section(table, results, mode)` | 1h | Low | 6 identical blocks → 1 function |
| Move debug logs to `logs/`; update `.gitignore` | 15m | None | Clean data directory |
| **Introduce `DayMetrics` and `ProjectResult` dataclasses** | 2h | Low | Foundation for all type safety; simplifies every subsequent extraction |

> **On model introduction:** Per V3 reviewer feedback, models move from Phase 3 into Phase 1. They are small additions with no behaviour change, and they make every subsequent extraction significantly easier.

**Phase 1 result:** The three god classes shed substantial dead and misplaced code. The core logic that remains is more visible, more navigable, and more correctly separated. No behaviour changes. No tests change.

---

### Phase 2: Decouple and Extract (Low Risk, High Impact)

| Task | Effort | Risk | Benefit |
|---|---|---|---|
| Extract modal screens to `screens/dialogs.py` | 1h | Low | Dialogs become independently testable; pure extraction |
| Extract sync logic from `cache.py` to `services/sync.py` | 2h | Low | `cache.py` becomes a pure data layer; sync testable in isolation |
| DRY: merge `log_negative_direct` + `log_positive_direct` into `log_activity_direct(mode)` | 1h | Low | Eliminates ~90% duplicate code in `neg.py` |
| Single `DataCache` instance: App → screens via reactive property | 1h | Low | Eliminates dual-cache inconsistency |
| Break `CalendarWidget → CommandTab` coupling; emit Textual Messages | 3h | Medium | `CalendarWidget` reusable and independently testable |
| Define remaining model types (`ReportSections`, `WeekDashboardRow`, `SyncStatus`) | 2h | Low | Completes the typed data layer foundation |

---

### Phase 3: Service Layer Extraction (Medium–High Risk, Highest Long-Term Value)

| Task | Effort | Risk | Benefit |
|---|---|---|---|
| Extract `MetricsService`: move `get_day_metrics`, `get_week_dashboard`, `get_report_sections` out of `DataCache` | 4h | Medium | `DataCache` becomes a pure repository; metrics testable without CSV files |
| Dependency injection for `Config`: `calculate(projects, points)` instead of global read | 3h | Medium | Testable without monkeypatching; explicit dependencies |
| Extract `OverviewScreen`, `SyncScreen` as separate `Screen` classes | 6h | High | Each view testable in isolation; App shell shrinks to navigation only |
| Move remaining business logic from `CommandTab` into services | 4h | High | `CommandTab` becomes pure UI |

---

### Phase 4: Reactive State and Polish

| Task | Effort | Risk | Benefit |
|---|---|---|---|
| Replace `refresh_all_views()` with Textual reactive attributes | 4h | High | Stale UI becomes architecturally impossible |
| Async cache loading via Textual `Worker` | 3h | Medium | Eliminates potential main-thread block during CSV parse |
| Split CLI from TUI code in `neg.py` and `api.py` | 2h | Low | Clean CLI/TUI separation |
| Add type annotations to all public functions | 4h | Low | `mypy` compatibility; IDE support |

> **Note:** The SQLite migration recommendation from V3 Phase 5 is removed entirely. SQLite was attempted and abandoned. The project is CSV-only. Any future storage consideration is a separate decision, explicitly out of scope for this refactor.

---

## 16. Top 10 Highest-Priority Fixes (Updated)

| Priority | Fix | Why Now |
|---|---|---|
| **1** | Delete SQLite files and entire backfill subsystem (`backfill.py`, `test_backfill.py`, references in `tui.py` and `cache.py`) | Mandated; near-zero risk; ~650–700 lines deleted and two dead files removed |
| **2** | Delete ~430 lines of confirmed dead code in `tui.py` (spark methods, removed view refreshers, dead handlers) | Near-zero risk; large readability gain |
| **3** | Extract ~900 lines of CSS to `styles/theme.tcss` | Shrinks `tui.py` dramatically; enables Textual hot-reload |
| **4** | Extract formatters to `formatters/cells.py` + `formatters/sections.py` | Resolves the `tui.py ↔ command.py` circular dependency |
| **5** | Introduce `DayMetrics` and `ProjectResult` dataclasses | Foundation for all type safety work; unlocks every subsequent extraction |
| **6** | DRY: `render_logged_section()` — 6 copies → 1 function | Display tweak currently requires 6 edits in 2 files |
| **7** | Extract modal screens to `screens/dialogs.py` | Pure extraction; zero behaviour change; dialogs become testable |
| **8** | Extract sync logic from `cache.py` to `services/sync.py` | `cache.py` drops 165 lines; data layer no longer imports transport layer |
| **9** | Single `DataCache` instance (App → screens) | Fixes dual-cache inconsistency in ~10 lines |
| **10** | Break `CalendarWidget → CommandTab` parent reference; emit Textual Messages | `CalendarWidget` becomes reusable and independently testable |

After priorities 1–4, the three god classes are dramatically leaner. Priority 5 (models) unlocks clean extraction for all subsequent phases.

---

## 17. Architecture Score Breakdown (Final)

| Dimension | V1/V2 | V3 | V4 | Notes |
|---|---|---|---|---|
| **Separation of Concerns** | 2/10 | 2/10 | 2/10 | `tui.py`, `cache.py`, `command.py` each mix 4+ responsibilities |
| **Testability** | 3/10 | 4/10 | 4/10 | Four-tier test suite; architecture blocks true unit isolation |
| **DRY** | 3/10 | 3/10 | 3/10 | 6× logged-section; 6× net calculation; 3× neg/pos pairs |
| **Module Boundaries** | 3/10 | 3/10 | 3/10 | Sync in cache, CLI in neg, formatters in tui |
| **Type Safety** | 2/10 | 2/10 | 2/10 | Raw dicts throughout; `models/` empty |
| **Dead Code** | 2/10 | 2/10 | **1/10** | ~1,350 confirmed dead lines + ~810 KB dead files; entire subsystem retired |
| **Dependency Direction** | 4/10 | 4/10 | 4/10 | Circular `command ↔ tui`; global state |
| **Code Organisation** | 4/10 | 4/10 | 4/10 | Flat structure; empty scaffolding |
| **State Management** | 3/10 | 3/10 | 3/10 | Mutable globals; dual cache; manual view refresh |
| **Scalability** | 4/10 | 4/10 | 4/10 | New views require editing the god class |
| **Data Layer Clarity** | — | 3/10 | **2/10** | "Dual storage" was a mischaracterisation; SQLite was dead code; CSV-only but unstructured |

**Overall: 4/10**

The V3 reviewer correctly argued that 3.5/10 understated the project's positive attributes. The revision to 4/10 acknowledges the four-tier test suite, four well-scoped foundation modules, structured tooling, and `AGENTS.md` — which are uncommon in projects of this scale.

The SQLite finding is simultaneously good news and bad news. Good: the failed migration is now correctly identified and its deletion is straightforward and low-risk. Bad: it adds ~650 additional lines of confirmed dead code that were previously miscounted as "active dual storage," and it means the V3 data layer analysis was built on an incorrect premise.

**After Phase 1 cleanup** — deleting backfill, deleting dead `tui.py` code, extracting CSS, extracting formatters, and introducing models — the score rises to approximately **6/10**. No logic is moved. No tests are changed. No features are removed. The cleanup alone exposes a structurally sound codebase underneath the accumulated dead weight.
