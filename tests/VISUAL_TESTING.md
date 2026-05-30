# Visual Testing Guide

## Overview

This project includes three types of tests:
- **Unit tests** (90 tests): Test individual functions and classes
- **E2E tests** (19 tests): Test user workflows and interactions
- **Visual tests** (17 tests): Screenshot-based regression tests
- **UI quality tests** (17 tests): Accessibility, focus, and error handling

## Running Tests

### All Tests
```bash
pytest tests/
```

### Unit and E2E Tests Only (Recommended for CI)
```bash
pytest tests/unit tests/e2e
```

### Visual Tests
Visual tests use `pytest-textual-snapshot` to capture SVG screenshots and compare them against baselines.

**Important**: Visual snapshots may fail between runs due to dynamic CSS class names in the SVG output. This is a known limitation of the library.

#### Generate/Update Baselines
```bash
pytest tests/visual --snapshot-update
```

#### Run Visual Tests
```bash
pytest tests/visual
```

#### View Snapshot Report
When visual tests fail, a detailed HTML report is generated at `snapshot_report.html`. Open it in a browser to see side-by-side comparisons.

## Test Structure

```
tests/
├── unit/                    # Unit tests (fast, isolated)
│   ├── test_calc.py        # Calculation engine tests
│   ├── test_cache.py       # DataCache tests
│   ├── test_neg.py         # Negative/positive logging tests
│   ├── test_config.py      # Configuration tests
│   ├── test_heatmap_grid.py # Heatmap rendering tests
│   ├── test_backfill.py    # Backfill system tests
│   └── test_new_fixes.py   # Bug fix regression tests
├── e2e/                     # End-to-end tests (user workflows)
│   ├── test_tui.py         # Main TUI interaction tests
│   └── test_tui_edge.py    # Edge case tests
├── visual/                  # Visual regression tests
│   └── test_snapshots.py   # Screenshot comparison tests
├── ui_quality/              # UI quality tests
│   └── test_quality.py     # Accessibility, focus, error handling
└── conftest.py             # Shared fixtures
```

## Known Issues

### Visual Snapshot Instability

The visual snapshot tests may fail between runs even when the UI hasn't changed. This is because:

1. **Dynamic CSS class names**: The SVG output includes hashed class names (e.g., `terminal-1585111918-matrix`) that change between runs
2. **Timestamps**: Some views display current time/date which changes between runs
3. **Random IDs**: Textual generates random IDs for some elements

**Workaround**: 
- Run visual tests with `--snapshot-update` to regenerate baselines
- Only run visual tests manually or in a controlled environment
- Use unit and E2E tests for CI/CD pipelines

### Corrupted CSV Handling

The app currently crashes when loading corrupted CSV data (e.g., non-numeric values in the Hours column). This is documented in `test_corrupted_csv_handled` which is skipped with a note.

**TODO**: Add error handling in `cache._load_daily()` and `cache._load_weekly()` to skip invalid rows gracefully.

## Writing New Tests

### Unit Tests
Test individual functions in isolation:
```python
def test_calculate_points():
    result = calculate({"Project A": 2.0}, {"Project A": 1.5})
    assert result == [("Project A", 2.0, 1.5, 3.0)]
```

### E2E Tests
Test user workflows with the TUI:
```python
@pytest.mark.asyncio
async def test_navigate_to_week_view(tui_data):
    app = TogglTUI()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+right")
        assert app.active_view_index == 2
```

### Visual Tests
Capture screenshots for regression testing:
```python
def test_day_view_snapshot(snap_compare, app_with_data):
    assert snap_compare(app_with_data, terminal_size=(120, 40))
```

## Test Coverage

Current test coverage focuses on:
- ✅ Calculation engine (points, formatting, sorting)
- ✅ Data loading and caching
- ✅ Negative/positive action logging
- ✅ View navigation and switching
- ✅ Modal dialogs (negative/positive input)
- ✅ Empty state handling
- ✅ Keyboard navigation
- ⚠️ Corrupted data handling (documented, not fixed)
- ⚠️ Visual regression (unstable due to library limitations)

## CI/CD Recommendations

For continuous integration, run only unit and E2E tests:
```bash
pytest tests/unit tests/e2e -v
```

Visual tests should be run manually when making UI changes:
```bash
pytest tests/visual --snapshot-update
git add tests/visual/__snapshots__/
git commit -m "Update visual snapshots"
```
