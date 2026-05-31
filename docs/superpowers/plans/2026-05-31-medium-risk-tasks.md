# Medium-Risk Architecture Tasks

> **For agentic workers:** Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract business logic from DataCache into a MetricsService, clean up config dependencies, and add async cache loading.

**Architecture:** UI → MetricsService → DataCache (unidirectional). MetricsService is a pure service layer above DataCache that composes query results. No memoization (DataCache caches at file level). Async Worker for background cache loading.

**Tech Stack:** Python 3.11, Textual Worker

---

### Task 1: Extract MetricsService from DataCache

**Files:**
- Create: `toggl/services/metrics.py`
- Modify: `toggl/cache.py` (remove 3 methods, add delegating wrappers)
- Modify: `toggl/command.py` (use MetricsService instead of DataCache)
- Modify: `toggl/tui.py` (use MetricsService instead of DataCache)
- Create: `tests/unit/test_metrics.py`
- Modify: `tests/unit/test_cache.py` (remove tests for moved methods, add delegation tests)

**Architecture rule:**
- `MetricsService` imports and uses `DataCache` (one-directional)
- `DataCache` must NOT import `MetricsService`
- No circular imports
- No memoization/caching in MetricsService — DataCache already handles caching

**Methods to move from DataCache to MetricsService:**

1. `get_day_metrics(self, day_date: str) -> dict[str, Any]` → `MetricsService.get_day_metrics(day_date: str) -> dict[str, Any]`
2. `get_week_dashboard_rows(self) -> list[dict[str, Any]]` → `MetricsService.get_week_dashboard_rows() -> list[dict[str, Any]]`
3. `get_report_sections(self, *args, **kwargs)` → `MetricsService.get_report_sections(*args, **kwargs)`

- [ ] **Step 1: Write failing tests for MetricsService**

Create `tests/unit/test_metrics.py`:

```python
"""Tests for MetricsService."""
from datetime import date
import pytest
from toggl.services.metrics import MetricsService
from toggl.cache import DataCache


# Use existing conftest fixtures: tmp_data_dir, sample_config, sample_daily_csv, sample_weekly_csv
@pytest.mark.usefixtures("tmp_data_dir", "sample_config", "sample_daily_csv", "sample_weekly_csv")
class TestMetricsService:
    def test_get_day_metrics(self):
        """get_day_metrics returns expected shape."""
        cache = DataCache.load()
        svc = MetricsService(cache)
        result = svc.get_day_metrics("2023-01-02")
        assert isinstance(result, dict)
        assert "net" in result
        assert "positive" in result
        assert "negative" in result
        assert "has_data" in result

    def test_get_day_metrics_returns_zeroes_for_missing_day(self):
        """A day with no data returns zero values, has_data=False."""
        cache = DataCache.load()
        svc = MetricsService(cache)
        result = svc.get_day_metrics("2099-12-31")
        assert result["net"] == 0.0
        assert result["has_data"] is False

    def test_get_week_dashboard_rows_shape(self):
        """get_week_dashboard_rows returns a list of dicts with expected keys."""
        cache = DataCache.load()
        svc = MetricsService(cache)
        rows = svc.get_week_dashboard_rows()
        assert isinstance(rows, list)
        if rows:
            row = rows[0]
            assert "date" in row
            assert "net" in row

    def test_get_report_sections_shape(self):
        """get_report_sections returns expected section keys."""
        cache = DataCache.load()
        svc = MetricsService(cache)
        result = svc.get_report_sections("ALL_TIME", "ALL")
        assert "positive" in result
        assert "negative" in result
        assert "unscored" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_metrics.py -x -v
```
Expected: ImportError — no module `toggl.services.metrics`.

- [ ] **Step 3: Create `toggl/services/metrics.py`**

```python
"""Service layer — business logic composed from data sources."""
from __future__ import annotations

from typing import Any

from toggl.cache import DataCache


class MetricsService:
    """Business logic layer above DataCache.

    Composes query results from DataCache into higher-level metrics.
    No memoization needed — DataCache handles its own caching.
    """

    def __init__(self, cache: DataCache):
        self._cache = cache

    def get_day_metrics(self, day_date: str) -> dict[str, Any]:
        """Return day metrics for a single day."""
        return self._cache.get_day_metrics(day_date)

    def get_week_dashboard_rows(self) -> list[dict[str, Any]]:
        """Return rows for the week dashboard."""
        return self._cache.get_week_dashboard_rows()

    def get_report_sections(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return report sections by category."""
        return self._cache.get_report_sections(*args, **kwargs)
```

- [ ] **Step 4: Run tests — should pass**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_metrics.py -x -v
```
Expected: All tests pass.

- [ ] **Step 5: Update conftest.py to expose metrics_service fixture**

Add to `tests/conftest.py`:

```python
@pytest.fixture
def metrics_service(tmp_data_dir, sample_config, sample_daily_csv, sample_weekly_csv):
    """Create a MetricsService with DataCache loaded from sample data."""
    from toggl.cache import DataCache
    from toggl.services.metrics import MetricsService
    return MetricsService(DataCache.load())
```

- [ ] **Step 6: Migrate DataCache method implementations to MetricsService**

Move the bodies of `DataCache.get_day_metrics`, `DataCache.get_week_dashboard_rows`, and `DataCache.get_report_sections` from `cache.py` to `MetricsService` in `metrics.py`.

Keep delegating wrappers in `DataCache` that forward to a `MetricsService` instance for backward compatibility:

```python
# In cache.py, at module level (lazy import to avoid circular dependency)
def _get_metrics_service():
    from toggl.services.metrics import MetricsService
    return MetricsService

# In DataCache class:
def get_day_metrics(self, day_date: str) -> dict[str, Any]:
    return _get_metrics_service()(self).get_day_metrics(day_date)
```

Wait — this creates a circular dependency risk since MetricsService imports DataCache. Instead, the delegating wrappers in DataCache should call the implementation directly (keeping the original code inline). Better approach:

**Approach:** Do NOT add delegating wrappers in DataCache. The moved methods simply no longer exist on DataCache. All callers are updated to use MetricsService.

Files to update:
1. Move method implementations from `DataCache` to `MetricsService`
2. Remove the methods from `DataCache`
3. Update all callers in `tui.py`, `command.py`
4. Update tests in `test_cache.py`

**Detailed method mapping:**

```python
# From cache.py DataCache.get_day_metrics → metrics.py MetricsService.get_day_metrics
def get_day_metrics(self, day_date: str) -> dict[str, Any]:
    dl = self._load_daily()
    for d in dl:
        if d["date"] == day_date:
            return {
                "date": day_date,
                "positive": d["positive"],
                "negative": d["negative"],
                "net": d["net"],
                "tracked": d.get("tracked", 0.0),
                "logged": d.get("logged", 0.0),
                "has_data": d.get("has_data", True),
            }
    return {"date": day_date, "positive": 0.0, "negative": 0.0, "net": 0.0,
            "tracked": 0.0, "logged": 0.0, "has_data": False}

# From cache.py DataCache.get_week_dashboard_rows → metrics.py MetricsService.get_week_dashboard_rows
# Returns list[dict[str, Any]] with week-level rollups

# From cache.py DataCache.get_report_sections → metrics.py MetricsService.get_report_sections
# Returns dict[str, Any] with positive/negative/unscored sections
```

**IMPORTANT:** Copy the FULL method body for each. These are substantial methods (15-60 lines each). Do not abbreviate.

- [ ] **Step 7: Update all callers**

**In `toggl/tui.py`:**
- Replace `cache.get_day_metrics(...)` with `MetricsService(cache).get_day_metrics(...)`
- Replace `cache.get_week_dashboard_rows()` with `MetricsService(cache).get_week_dashboard_rows()`
- Replace `cache.get_report_sections(...)` with `MetricsService(cache).get_report_sections(...)`
- Add `from toggl.services.metrics import MetricsService`

**In `toggl/command.py`:**
- Similar replacements
- Same import

**In `toggl/cache.py`:**
- Remove the 3 method definitions from `DataCache` class

- [ ] **Step 8: Update tests for changed API**

**In `tests/unit/test_cache.py`:**
- Remove tests for `get_day_metrics`, `get_week_dashboard_rows`, `get_report_sections`
- Add delegation tests if keeping wrappers

**In `tests/unit/test_metrics.py`:**
- Tests already pass from Step 2 (they were written first)

- [ ] **Step 9: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

---

### Task 2: Clean Up Config Dependency

**Files:**
- Modify: `toggl/cache.py`
- Modify: `toggl/services/metrics.py`
- (No test changes needed — behavior is identical)

**Goal:** Remove direct global `from toggl.config import POINTS, NEGATIVES, POSITIVES, CATEGORY_REGISTRY, RATE_COLORS` reads in `cache.py` and `metrics.py`. Instead, pass config values through constructor/parameters.

This requires reading `cache.py` to find which config globals are used by the methods being extracted, and injecting them correctly.

- [ ] **Step 1: Audit config usage in cache.py**

```bash
cd /Users/sai/Downloads/TUI && rg "from toggl.config import|toggl.config\." toggl/cache.py | head -20
```
Identify which config values are used by the methods staying in DataCache and the methods moving to MetricsService.

- [ ] **Step 2: Pass config to MetricsService constructor**

For any config values needed by MetricsService methods:

```python
class MetricsService:
    def __init__(self, cache: DataCache, negatives: dict | None = None, positives: dict | None = None):
        self._cache = cache
        self._negatives = negatives or NEGATIVES
        self._positives = positives or POSITIVES
```

- [ ] **Step 3: Audit cache.py remaining config dependencies**

For remaining DataCache methods that still read config globals directly, extract them as constructor parameters with defaults from the global.

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

---

### Task 3: Async Cache Loading via Textual Worker

**Files:**
- Modify: `toggl/tui.py`
- (No new files — just app shell changes)

**Goal:** Replace the synchronous `DataCache.load()` call in `on_mount` and `refresh_all_views` with a Textual `Worker` that loads data asynchronously, showing a loading indicator while the data loads.

- [ ] **Step 1: Add async loading with Worker**

In `toggl/tui.py`, add:

```python
from textual.worker import Worker

class TogglTUI(App):
    def on_mount(self):
        # ... existing setup ...
        self.load_data()
        # Don't call refresh_all_views() immediately — Worker callback handles it

    @work(thread=False, exclusive=True)
    async def load_data(self) -> None:
        """Load cache data in background worker."""
        self._data_cache = DataCache.load()
        self.refresh_all_views()
```

The `on_mount` currently calls:
1. `self._setup_tables()` — still synchronous, runs immediately
2. `load_runtime_settings()` — still synchronous
3. Tab setup — still synchronous
4. `needs_auto_update()` check — still synchronous
5. `self.refresh_all_views()` — moves to async worker (remove from on_mount)

- [ ] **Step 2: Add loading indicator**

Show a Static with loading text in compose if cache not ready, or use a screen-level approach:

```python
# In compose, add loading overlay
with Container(id="loading-overlay"):
    yield Static("Loading data...", id="loading-text")
```

Hide it when data loads in the worker callback.

- [ ] **Step 3: Handle refresh_all_views when worker is running**

If the worker is still running and user triggers a refresh, either:
- Skip the refresh (worker will handle it)
- Or cancel and restart

Best approach: check if worker is done in `refresh_all_views`:

```python
def refresh_all_views(self):
    if self._data_cache is None:
        return  # Worker hasn't finished yet
    # ... existing refresh code ...
```

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass (some e2e snapshot tests may need adjustments for timing).

---

### Final Verification

- [ ] **Run full suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -v
```
Expected: All tests pass.
