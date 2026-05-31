# Phase 2: Decouple and Extract — Architecture Remediation

> **For agentic workers:** Use subagent-driven-development or executing-plans to implement this plan task-by-task.

**Goal:** Complete 6 decoupling/extraction tasks to slim neg.py, cache.py, tui.py, command.py — DRY duplicated code, extract dialogs and sync service, define typed models, single DataCache, decouple CalendarWidget.

**Architecture:** Pure extraction — no behavior changes. Screens → `toggl/screens/dialogs.py`. Sync → `toggl/services/sync.py`. Models → `toggl/models/metrics.py`. CalendarWidget emits Textual Messages.

**Tech Stack:** Python 3.11, Textual, Rich

---

### Task 1: DRY log_negative_direct + log_positive_direct into log_activity_direct(mode)

**Files:**
- Modify: `toggl/neg.py`
- Test: `tests/unit/test_neg.py`

Introduce a parameterized `log_activity_direct(name, mode)` that replaces ~90% of the duplicated code. Keep `log_positive_direct`/`log_negative_direct` as wrappers.

### Task 2: Single DataCache Instance

**Files:**
- Modify: `toggl/tui.py`
- Modify: `toggl/command.py`

Store cache on `TogglTUI._data_cache`, pass to `CommandTab.data_cache` property before `refresh_all()`.

### Task 3: Define Model Types

**Files:**
- Create: `toggl/models/__init__.py`
- Create: `toggl/models/metrics.py`

`DayMetrics`, `ProjectResult`, `ReportSections`, `WeekDashboardRow`, `SyncStatus` dataclasses.

### Task 4: Extract Modal Screens

**Files:**
- Create: `toggl/screens/__init__.py`, `toggl/screens/dialogs.py`
- Modify: `toggl/tui.py`, test files

Move `BaseDialog`, `ConfirmScreen`, `NegativeInputScreen`, `PositiveInputScreen` from tui.py.

### Task 5: Extract Sync Logic

**Files:**
- Create: `toggl/services/__init__.py`, `toggl/services/sync.py`
- Modify: `toggl/cache.py`, `toggl/tui.py`

Move `_load_history` from cache.py to services/sync.py.

### Task 6: Break CalendarWidget-CommandTab Coupling

**Files:**
- Modify: `toggl/command.py`

CalendarWidget emits `NavToDate` and `ClickDay` Textual Messages. CommandTab handles them with `@on` decorators.
