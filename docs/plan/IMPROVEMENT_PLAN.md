# IMPORTANT — IN PROGRESS

# Toggl TUI Upgrade Plan

> **Status:** All 6 steps complete. 28/28 tests passing. Awaiting user review.
> **Branch:** `ai-guidance` at `/Users/sai/Downloads/TUI/.worktrees/ai-guidance`
> **Repo root:** `/Users/sai/Downloads/TUI` (git)
> **Runner:** `python app.py` (entrypoint `app.py` → `TogglTrack.py` → `toggl/tui.py`)
> **Deps:** `textual>=0.86,<1.0` (in `requirements.txt`)
> **Test runner:** `pytest`
> **AI docs location:** `AGENTS.md`, `docs/ai/*`, `docs/plan/*`
> **Skill context:** Use `docs/ai/AI_GUIDELINES.md` for agent rules; `docs/ai/SLOP_RULES.md` for output constraints.

---

## Completed: Step 1 — AI Documentation

Files created on branch `ai-guidance`:
- `AGENTS.md` — repo overview for AI agents
- `docs/ai/README.md` — doc index
- `docs/ai/AI_GUIDELINES.md` — AI behavior rules
- `docs/ai/SLOP_RULES.md` — anti-slop checklist
- `docs/ai/AI_REVIEW_GUIDELINES.md` — spec compliance review checklist
- `docs/ai/CODE_REVIEW_GUIDELINES.md` — code quality review checklist
- `docs/plan/IMPROVEMENT_PLAN.md` — this file

All files use apply_patch (no commits yet). `.gitignore` updated with `.worktrees/` entry.

---

## Next: Step 2 — Backfill Subsystem

### 2a. New file: `toggl/backfill.py`

Create a new module at `toggl/backfill.py`. It must NOT import from `toggl/tui.py`.

#### SQLite DB at `data/toggl_backfill.db`

Schema — table `runs`:
```sql
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'started',   -- 'started', 'success', 'failed'
    started_at TEXT NOT NULL,                  -- ISO-8601
    finished_at TEXT,
    weeks_discovered INTEGER DEFAULT 0,
    weeks_backfilled INTEGER DEFAULT 0,
    api_requests_made INTEGER DEFAULT 0,
    stopped_reason TEXT                        -- 'quota', 'complete', 'error'
);
```

Schema — table `checkpoints`:
```sql
CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    earliest_week TEXT,            -- e.g. "2023-W01"
    last_completed_week TEXT,      -- last week successfully backfilled
    last_verified_at TEXT,         -- ISO-8601 timestamp
    last_verified_week TEXT,       -- most recently verified week
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
```

Only one row in `checkpoints` is active at a time (the one tied to the latest `run_id`).

#### Functions to implement in `toggl/backfill.py`:

1. `get_backfill_db_path() -> str` — returns `os.path.join(DATA_DIR, "toggl_backfill.db")`

2. `init_backfill_db()` — creates DB file + tables if not exist.

3. `find_earliest_week(token: str, projects_map: dict) -> str | None`
   - **Weekly binary search** between low=2023-01-01 and high=current week.
   - Fetch week data via `fetch_week_data(week_str, token, projects_map)` (from `toggl/cache.py`).
   - If week has data → search later half. If no data → search earlier half.
   - Return earliest week string that has data, or None.
   - **Important:** Reuse existing `fetch_week_data` from `cache.py` — do NOT reimplement API calls.

4. `find_missing_weeks(earliest_week: str) -> list[str]`
   - Scan all weeks from `earliest_week` to current week.
   - For each week: check if week exists in weekly CSV AND all 7 days exist in daily CSV.
   - Return list of week strings that are fully or partially missing.
   - **Gap detection:** Compare API week project names to CSV project names — if any project present in API data is missing from CSV for that week, the week is "missing" (needs merge).

5. `backfill_week(week_str: str, token: str, projects_map: dict) -> dict`
   - Fetch week data via `fetch_week_data(week_str, token, projects_map)`.
   - Call existing `_patch_weekly_csv(week_str, weekly_data)` and `_patch_daily_csv(week_str, daily_data)` from `cache.py`.
   - Return `{"success": True}` or `{"success": False, "reason": "quota"}`.

6. `run_backfill(token: str, projects_map: dict) -> dict`
   - Main orchestration function.
   - Create a `runs` entry with status `'started'`.
   - Call `find_earliest_week` if no checkpoint exists yet.
   - Call `find_missing_weeks` to get list.
   - For each missing week: call `backfill_week`. If quota exhausted (`TogglRateLimitError`), stop and mark `stopped_reason='quota'`.
   - On completion: update `runs` status to `'success'` and `checkpoints`.
   - Return summary dict.

7. `get_backfill_status() -> dict`
   - Read latest run + checkpoint from DB.
   - Return `{"status", "earliest_week", "last_completed_week", "weeks_backfilled", "total_weeks"}`.

8. `verify_backfill_needed() -> list[str]`
   - Quick check: scan weekly CSV for weeks, cross-ref daily CSV.
   - If any week has fewer daily entries than expected (7 days × projects), flag it.
   - Return missing week strings.
   - **No API calls** — just CSV scanning.

#### Quota handling:
- Import `_confirm_sync_quota` from `toggl/api.py`.
- Before each backfill API call, check if remaining quota > 2.
- If quota is exhausted, catch `TogglRateLimitError` (also from `toggl/api.py`), mark run as `stopped_reason='quota'`, return partial results.

#### Integration points:
- `toggl/cache.py` already exports: `fetch_week_data`, `_patch_weekly_csv`, `_patch_daily_csv`, `get_week_dates`, `get_week_str`, `get_sunday_of_week`.
- `toggl/api.py` exports: `_confirm_sync_quota`, `TogglRateLimitError`, `TogglAPIError`, `get_api_token`, `get_projects_map`.

---

### 2b. Update `toggl/const.py`

Add to file paths:
```python
BACKFILL_DB = os.path.join(DATA_DIR, "toggl_backfill.db")
```

### 2c. Update `toggl/cache.py`

Add precomputed metrics for the current year (needed by later steps):
- `get_yearly_day_net_map(year: int) -> dict[str, float]` — returns `{ "2026-01-15": 3.2, ... }` for every day in the given year with data.
- `get_monthly_aggregates(last_n_months: int = 12) -> list[dict]` — iterate last N months, aggregate daily data into month-level: `{"month": "2026-01", "hours": 120.5, "net": 15.3}`.
- These should precompute once per cache load (e.g. computed in `load()` or lazily cached).

### 2d. Update `toggl/tui.py` (minimal)

- In `get_sync_status_data()`, add backfill status: `"backfill_status": get_backfill_status()`.
- In `refresh_sync_view()`, add rows for backfill status.
- Add a new binding `B` for backfill (optional — we can wire it into the existing sync flow).

### 2e. Update `toggl/api.py`

- Export `TogglRateLimitError` (already done) and ensure it's importable from the backfill module.

---

## Step 3 — DataCache Upgrades

### Changes to `toggl/cache.py`

Already partially covered in 2c. Full list:
- `get_yearly_day_net_map(year: int) -> dict[str, float]`
- `get_monthly_aggregates(last_n_months: int = 12) -> list[dict]`
- Cache these in `__init__` instance vars (e.g. `self._yearly_day_net: dict[int, dict] = {}`).
- Compute lazily on first access, not in `load()`.

---

## Step 4 — TUI Upgrades

### New files (no — changes to `toggl/tui.py`)

#### VIEWS array update
Add `"Month"` and `"Heatmap"` to `VIEWS = ["Overview", "Day", "Week", "Month", "Heatmap", "Negatives", "Positives", "Recovery", "Sync/Quota"]`.

#### Month view
- New container with id `"month-view"` and class `"view"`.
- DataTable with columns: `Month`, `Hours`, `Net`.
- 12 rows (last 12 months).
- Data from `cache.get_monthly_aggregates(12)`.
- Cursor highlight updates selected month → update Week view to first week of selected month.
- Month nav: `Shift+↑` / `Shift+↓` (with `{` / `}` fallback keys).

#### Heatmap view
- New container with id `"heatmap-view"` and class `"view"`.
- Render a GitHub-style contribution grid for the current year.
- **Data:** `cache.get_yearly_day_net_map(current_year)`.
- **Scale:** Global (across all days in year). Clamp color intensity at 10th/90th percentile.
- **Colors:** Diverging red (negative) → white (zero) → green (positive).
- Uses Textual widgets — likely a custom `Static` with Rich renderable or a `DataTable`.
- **Tooltip:** Show in footer status line: date, net, hours, pos/neg breakdown when a day cell is hovered/selected.
- **Legend:** Compact row above grid showing intensity scale.
- **Selection:** Clicking a day cell updates `selected_day` → refreshes Day view + Week view.
- **Spark cursor sync:** Spark days cursor stays synced with selected_day (already works via existing mechanism).

#### Global navigation
- `←` / `→`: navigate days (already works)
- `↑` / `↓`: navigate weeks (already works)
- `Shift+↑` / `Shift+↓`: navigate months (new)
- Fallback keys for month: `{` / `}` if Shift+arrow conflicts.
- **Context banner:** A new `Static` widget at the top showing current context like `"Day: 2026-01-15"` or `"Week: 2026-W03"` or `"Month: 2026-01"` depending on active view.

#### Visual polish
- Reduce row padding in tables (tighter layout).
- Sync/Quota view: add backfill status rows (from `get_backfill_status()`).

---

## Step 5 — Tests

### File structure
```
tests/
  __init__.py
  conftest.py         — shared fixtures
  unit/
    __init__.py
    test_backfill.py   — merge logic, binary search, db schema
  e2e/
    __init__.py
    test_tui.py        — Textual Pilot E2E flow
```

### `tests/conftest.py`
- Fixtures:
  - `tmp_data_dir(tmp_path)` — creates a temp dir, monkeypatches `toggl.const.DATA_DIR` and all CSV/DB paths.
  - `sample_weekly_csv(tmp_data_dir)` — writes a minimal weekly CSV with known test data.
  - `sample_daily_csv(tmp_data_dir)` — writes a minimal daily CSV.
  - `sample_config(tmp_data_dir)` — writes a minimal `toggl_config.json` with point values.
  - `stub_api(monkeypatch)` — monkeypatches `toggl.api.toggl_request` or `fetch_week_data` to return canned responses.

### `tests/unit/test_backfill.py`
Write first (TDD), test:
- `init_backfill_db()` creates tables.
- `find_earliest_week()` with binary search on stubbed API.
- `find_missing_weeks()` vs complete and incomplete datasets.
- `backfill_week()` merges correctly into CSVs.
- `verify_backfill_needed()` detects gaps.

### `tests/e2e/test_tui.py`
- First E2E flow: Week ↔ Day sync.
  - Use Textual `pilot` to launch the app.
  - Navigate to Week view, ensure Day view updates on row highlight.
  - Test basic view switching via `Tab` / `Shift+Tab`.

---

## Detailed file reference

### `toggl/cache.py` exports
```python
# Helpers
get_week_dates(week_str) -> (date, date)
get_week_str(d) -> str
get_sunday_of_week(d) -> date
get_current_week() -> str
get_iso_format(d, is_end) -> str
fetch_week_data(week_str, token, projects_map) -> (dict, dict)   # weekly_data, daily_data

# CSV patch functions
_patch_weekly_csv(week_str, weekly_data)  # merges rows
_patch_daily_csv(week_str, daily_data)    # merges rows

# History helpers
_load_history() -> dict
_save_history(history)
get_last_updated_str() -> str
needs_auto_update() -> bool
_atomic_write(path, content_str)

# Cache
DataCache (class) — see full source at toggl/cache.py
get_cache() -> DataCache
reset_cache()
```

### `toggl/api.py` exports
```python
TogglRateLimitError, TogglAPIError
get_api_token() -> str
get_projects_map(token) -> dict
is_projects_cache_stale() -> bool
_confirm_sync_quota(token, estimated, label, prompt) -> bool
_reset_api_stats()
API_RUN_STATS (dict with 'remaining', 'limit', 'resets_in')
```

### `toggl/const.py` paths (all under `DATA_DIR`)
```python
CSV_FILE = DATA_DIR/toggl_data.csv           # weekly
DAILY_CSV_FILE = DATA_DIR/toggl_daily.csv     # daily
NEGATIVES_CSV_FILE = DATA_DIR/toggl_negatives.csv
POSITIVES_CSV_FILE = DATA_DIR/toggl_positives.csv
HISTORY_FILE = DATA_DIR/toggl_sync_history.json
PROJECTS_FILE = DATA_DIR/toggl_projects.json
BACKFILL_DB = DATA_DIR/toggl_backfill.db      # NEW
```

### CSV schemas
**Weekly** (`toggl_data.csv`): `Week,Project,Hours`
**Daily** (`toggl_daily.csv`): `Date,Project,Hours`
**Negatives** (`toggl_negatives.csv`): `Date,Negative,Points`
**Positives** (`toggl_positives.csv`): `Date,Positive,Points`

---

## Key architectural rules

1. **`toggl/backfill.py`** must be self-contained — it imports from `cache.py` and `api.py` only, never from `tui.py`.
2. **DataCache** owns all data aggregation. TUI views call DataCache methods, never access raw CSVs.
3. **Backfill merges only missing rows** — never duplicates or overwrites existing data. Check by comparing API project names to CSV project names per week.
4. **Quota safety** — every sync operation checks `_confirm_sync_quota` before making API calls. Backfill stops if quota < 2 remaining.
5. **No git commits** without explicit user request. Files changes via `apply_patch` or `write` tool.
6. **TDD** — write failing test first, then implementation code.
7. **Non-interactive shell** — no editors, pagers, or interactive prompts.
8. **`data/` directory** is gitignored (as are all CSVs). Tests use `tmp_path` fixtures.

---

## AI agent handoff instructions

If continuing this work from a compressed or new session:

1. **Verify branch:** check you're on `ai-guidance` in the worktree at `/Users/sai/Downloads/TUI/.worktrees/ai-guidance`.
2. **Read this plan fully** — understand what's done vs pending.
3. **Update `IMPROVEMENT_PLAN.md`** as you complete steps (change status lines).
4. **Prefer subagent-driven development:** dispatch implementer subagent → spec reviewer → code quality reviewer per task.
5. **Use TDD:** write test → watch fail → implement → watch pass → refactor.
6. **Do NOT commit** unless user explicitly asks.
7. **AI docs are in `AGENTS.md` and `docs/ai/*`** — follow them.
8. **Worktree `.gitignore`** already has `.worktrees/` entry (added during Step 1).

---

## Execution checklist

- [x] **1. AI docs** — AGENTS.md, docs/ai/*, docs/plan/*, .gitignore update
- [x] **2a. `toggl/backfill.py`** — DB schema, binary search, missing detection, merge, orchestration
- [x] **2b. `toggl/const.py`** — add `BACKFILL_DB` path
- [x] **2c. `toggl/cache.py`** — yearly day net map, monthly aggregates
- [x] **2d. `toggl/tui.py`** — backfill status in sync view
- [x] **3. DataCache full** — precompute methods done
- [x] **4a. Month view** — container, table, 12 months, navigation
- [x] **4b. Heatmap view** — GitHub grid, tooltip, legend, selection → Day/Week sync
- [x] **4c. Navigation** — month nav, context banner
- [x] **4d. Polish** — reduced padding, context banner
- [x] **5a. `tests/conftest.py`** — fixtures
- [x] **5b. `tests/unit/test_backfill.py`** — unit tests
- [x] **5c. `tests/e2e/test_tui.py`** — first E2E flow
