# View Widget Extraction Design

**Goal:** Extract the Overview and Sync views from `TogglTUI` god-widget into standalone `Widget` subclasses, leaving the App as a pure tab navigator.

**Architecture:** Replace `Container(id="overview-view")` and `Container(id="sync-view")` with `OverviewPanel(Widget)` and `SyncPanel(Widget)`. Each Widget owns its own `compose`, `on_mount`, and refresh logic. The App composes these widgets, delegates refresh to them, and handles only tab navigation and global actions.

---

## 1. Architecture

### Current (monolithic)

```
TogglTUI (App)
  ├── compose() — builds ALL view content inline
  ├── refresh_overview_view() — 80 lines inline
  ├── refresh_sync_view() — 30 lines inline
  ├── _add_rows_mark_sections() — overview-only helper
  ├── _skip_section_rows() — overview-only handler
  ├── _resize_tables() — sync-table only (rest removed)
  ├── on_neg_log_btn(), on_pos_log_btn()
  └── Tab navigation, sync actions, log actions
```

### Target (extracted)

```
TogglTUI (App) — pure tab navigator
  ├── compose()
  │   ├── chrome (tabs, sync-status)
  │   ├── OverviewPanel(id="overview-view")
  │   ├── CommandTab(id="command-view")
  │   └── SyncPanel(id="sync-view")
  ├── Tab navigation: action_next/prev, on_tab_activated
  ├── Sync actions: action_sync_current_week, action_sync_full, _on_sync_done
  ├── Log actions: action_add_negative/positive
  ├── Zoom actions: action_cmd_zoom_in/out
  ├── _resize_tables() — sync-table only
  └── data loading: load_data, _do_auto_refresh

OverviewPanel(Widget)
  ├── compose(): categories-table, recovery-table, recent-log-table, insights, buttons
  ├── on_mount(): _setup_tables
  ├── refresh(data_cache): replaces refresh_overview_view()
  ├── _add_rows_mark_sections()
  ├── _skip_section_rows() handler
  ├── Log Neg/Pos button handlers (post App messages)
  └── CSS: keeps all #overview-* selectors

SyncPanel(Widget)
  ├── compose(): sync-table
  ├── on_mount(): _setup_tables
  ├── refresh(): replaces refresh_sync_view()
  └── CSS: keeps #sync-table selectors
```

### Data flow

```
App.load_data() → DataCache.load()
  → App.refresh_all_views()
    → OverviewPanel.refresh(data_cache, active_week)
    → CommandTab.refresh_all(data_cache)
    → SyncPanel.refresh()
```

---

## 2. Widget Boundaries

### OverviewPanel responsibilities

- Compose: categories table, recovery table, recent log table, insights panel, Log Neg/Pos buttons
- `refresh(data_cache, active_week)` — populate all tables with data
- `_setup_tables()` — add columns, set styles
- `_add_rows_mark_sections(table, rows)` — section header handling
- `_skip_section_rows()` event handler for category table
- Button handlers for `#btn-neg-log`, `#btn-pos-log` — post `LogNegRequested` / `LogPosRequested` messages
- All `#overview-*` CSS selectors move into `OverviewPanel` CSS

### SyncPanel responsibilities

- Compose: sync data table
- `refresh()` — call `get_sync_status_data()`, populate `#sync-table`
- `_setup_tables()` — add "Metric"/"Value" columns
- `#sync-table` CSS selectors move into `SyncPanel` CSS

### App stays with

- Chrome (tabs, sync-status), footer
- `CommandTab` (already a standalone widget)
- Tab navigation state machine (`active_view_index`, `action_next_view`, `action_prev_view`, `on_tab_activated`, `update_tabs`, `update_view_visibility`, `focus_active_view`)
- `refresh_all_views()`, `_refresh_view_by_index()` — delegates to each widget
- Data loading: `load_data()`, `_do_auto_refresh()`, `_on_auto_refresh_done()`
- Sync workflows: `action_sync_current_week`, `_do_sync_current_week`, `action_sync_full`, `_do_sync_full`, `_on_sync_done()`
- Log workflows: `action_add_negative`, `action_add_positive` (push screens)
- Zoom passthrough: `action_cmd_zoom_in/out`
- `_resize_tables()` — only `#sync-table` remains
- `on_resize`, `action_refresh_data`, `action_show_help`
- `ScrollableFooter` class

### App properties to remove

- `active_view_index`, `selected_day`, `_active_week` — stay
- `_data_cache` — stay (passed down to panels)
- `_table_resize_timer` — stay
- `_initialized` — stay

---

## 3. Messages

```python
class LogNegRequested(Message):
    """User clicked Log Neg button in OverviewPanel."""

class LogPosRequested(Message):
    """User clicked Log Pos button in OverviewPanel."""
```

App handles these to push the appropriate dialog screens.

---

## 4. File Changes

| File | Change |
|------|--------|
| `toggl/tui.py` | Remove `refresh_overview_view()`, `refresh_sync_view()`, `_add_rows_mark_sections()`, `_skip_section_rows()`, `on_neg_log_btn()`, `on_pos_log_btn()`. App `compose()` yields `OverviewPanel()` and `SyncPanel()` instead of inline containers. App `_resize_tables()` drops overview table refs. |
| `toggl/panels.py` (new) | Contains `OverviewPanel(Widget)` and `SyncPanel(Widget)`. Each with own compose, on_mount, refresh, helpers. |
| `toggl/styles/theme.tcss` | Move `#overview-*`, `#sync-table`, `.recovery-btn`, `#recovery-button-bar` CSS into respective widget CSS (using `DEFAULT_CSS`). Keep view `.view.-active` handling — App still controls visibility. |

---

## 5. Test Impact

| Test | Change |
|------|--------|
| `tests/e2e/test_tui.py` | No change: still queries `app.query_one("#sync-table")` etc. by ID |
| `tests/e2e/test_tui_edge.py` | No change: same IDs |
| `tests/ui_quality/test_quality.py` | Imports stay unchanged (query by ID) |
| `tests/unit/test_panels.py` (new) | Optional: test OverviewPanel/SyncPanel in isolation |

---

## 6. Error Handling

- All panel `refresh()` methods wrap internal exceptions with `logger.exception` (matching current `_refresh_view_by_index` pattern)
- If a panel is not mounted yet, `self.query_one(...)` raises — panels handle this gracefully (same as current `refresh_command_view` try/except)

---

## 7. CSS Changes

**theme.tcss**: Remove:
- All `#overview-*` selectors
- `#sync-table` selectors (moves to SyncPanel)
- `.recovery-btn`, `#recovery-button-bar` selectors
- Keep `.view`, `.-active` visibility toggles (App handles hiding/showing panels)
- Keep all global styles (DataTable, etc.)

**OverviewPanel.DEFAULT_CSS**: 
- All existing `#overview-*` selectors
- `.recovery-btn`, `#recovery-button-bar`
- Panel sizing (width/height)

**SyncPanel.DEFAULT_CSS**:
- `#sync-table` sizing (height 1fr, border, etc.)
- Panel sizing
