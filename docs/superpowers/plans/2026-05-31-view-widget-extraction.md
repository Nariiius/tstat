# View Widget Extraction Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Extract Overview and Sync views from `TogglTUI` into standalone `Widget` subclasses.

**Architecture:** New `OverviewPanel(Widget)` and `SyncPanel(Widget)` in `panels.py`. Each owns its compose, mount, refresh lifecycle. App becomes a tab navigator that yields these widgets and delegates refresh to them.

**Tech Stack:** Python 3.11, Textual

---

### Task 1: Create `toggl/panels.py` with `SyncPanel`

**Files:**
- Create: `toggl/panels.py` (sync panel section)
- Modify: `toggl/tui.py` (import, compose, refresh, resize)
- Modify: `toggl/styles/theme.tcss` (sync-table CSS moves)

- [ ] **Step 1: Add SyncPanel to panels.py**

Create `toggl/panels.py`:

```python
"""OverviewPanel and SyncPanel — standalone view widgets for TogglTUI."""

from __future__ import annotations

import logging
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Static

from toggl.api import API_RUN_STATS, _format_reset_window
from toggl.formatters import (
    _fmt_recovery_cells,
    _fmt_section_header,
    _fmt_tree_cells,
    _fmt_project_tree,
    fmt_pts_rich,
    format_signed_rich,
    SECTION_COLORS,
)
from toggl.services.metrics import MetricsService

logger = logging.getLogger("TStat")


def get_sync_status_data() -> dict[str, Any]:
    import csv, os
    from toggl.const import CSV_FILE, DAILY_CSV_FILE
    from toggl.services.sync import _load_history
    from toggl.api import API_RUN_STATS, get_projects_cache_age_days, get_last_updated_str, get_current_week

    history = _load_history()

    synced_weeks = 0
    synced_days = 0
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE) as f:
            synced_weeks = len({row["Week"] for row in csv.DictReader(f)})
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE) as f:
            synced_days = len({row["Date"] for row in csv.DictReader(f)})

    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": synced_weeks,
        "synced_days": synced_days,
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
    }


class SyncPanel(Container):
    """Sync/Quota status panel.

    Shows current week, last updated, cache age, sync counts,
    API usage stats, and quota status.
    """

    DEFAULT_CSS = """
    SyncPanel {
        height: 1fr;
    }
    #sync-table {
        height: 1fr;
        border: round #3d4f63;
        background: #0b1016;
    }
    #sync-table:focus,
    #sync-table:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }
    #sync-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }
    #sync-table > .datatable--cursor,
    #sync-table > .datatable--fixed-cursor {
        background: #1e2a36;
    }
    """

    def compose(self) -> ComposeResult:
        yield DataTable(
            zebra_stripes=False, cursor_type="row", id="sync-table"
        )

    def on_mount(self) -> None:
        table = self.query_one("#sync-table", DataTable)
        table.add_columns("Metric", "Value")
        table.styles.min_height = 1
        table.show_cursor = True

    def refresh(self) -> None:
        """Reload sync status data and repopulate the table."""
        status = get_sync_status_data()
        table = self.query_one("#sync-table", DataTable)
        table.clear(columns=False)
        cache_age = status["projects_cache_age_days"]
        remaining = (
            status["quota_remaining"]
            if status["quota_remaining"] is not None
            else "Unknown"
        )
        limit = (
            status["quota_limit"] if status["quota_limit"] is not None else "Unknown"
        )
        rows = [
            ("Current week", str(status["current_week"])),
            ("Last updated", status["last_updated"]),
            (
                "Projects cache",
                "missing" if cache_age is None else f"{cache_age:.1f} days old",
            ),
            ("Synced weeks", str(status["synced_weeks"])),
            ("Synced days", str(status["synced_days"])),
            ("Requests made", str(API_RUN_STATS["requests_made"])),
            ("Quota remaining", f"{remaining}/{limit}"),
            ("Quota resets in",
             _format_reset_window(status["quota_resets_in"])
             if status["quota_resets_in"] is not None
             else "—"),
        ]
        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Sync Status[/][/]"
        table.border_subtitle = (
            "[#8d98a7]u syncs current week. U refreshes projects and syncs 4 weeks.[/]"
        )
```

- [ ] **Step 2: Verify file parses**

```bash
cd /Users/sai/Downloads/TUI && python -c "from toggl.panels import SyncPanel; print('OK')"
```
Expected: OK

- [ ] **Step 3: Update tui.py — import and use SyncPanel**

In `toggl/tui.py`:

Replace the `Container(id="sync-view", classes="view")` block in `compose()`:
```python
# Old:
with Container(id="sync-view", classes="view"):
    yield DataTable(
        zebra_stripes=False, cursor_type="row", id="sync-table"
    )

# New:
yield SyncPanel(id="sync-view", classes="view")
```

Add import at top:
```python
from toggl.panels import SyncPanel
```

Replace `refresh_sync_view()` method:
```python
def refresh_sync_view(self) -> None:
    """Refresh the Sync/Quota panel."""
    try:
        panel = self.query_one(SyncPanel)
        panel.refresh()
    except Exception:
        pass  # Panel may not be mounted yet
```

Remove `get_sync_status_data()` function from tui.py (now lives in panels.py).

Remove `_format_reset_window` and `API_RUN_STATS` imports from tui.py imports (they're used by SyncPanel now). Keep them if used elsewhere.

Remove `_format_reset_window` from the `from toggl.api import` line in tui.py (only used by sync view).

Remove `API_RUN_STATS` from imports only if it's not used elsewhere. Check first:
```bash
cd /Users/sai/Downloads/TUI && rg "API_RUN_STATS" toggl/tui.py
```

Update `_resize_tables()` to use `SyncPanel` instead of `#sync-table` if needed — actually keep `#sync-table` reference since it still queries by ID within the mounted widget.

Remove the sync-table from `_setup_tables()` — SyncPanel handles its own on_mount setup now. Remove lines:
```python
sync_table = self.query_one("#sync-table", DataTable)
sync_table.add_columns("Metric", "Value")
```
And remove `"#sync-table"` from the `for table_id in [...]` loop.

- [ ] **Step 4: Remove sync-table CSS from theme.tcss**

Delete these lines from `toggl/styles/theme.tcss` (there are no explicit `#sync-table` selectors, only global DataTable styles — keep those):

There are no explicit `#sync-table` selectors in the CSS, so no CSS removal needed for sync.

- [ ] **Step 5: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass (16 snapshot failures are pre-existing).

---

### Task 2: Add `OverviewPanel` to `panels.py`

**Files:**
- Modify: `toggl/panels.py` (add OverviewPanel class)
- Modify: `toggl/tui.py` (import, compose, refresh)

- [ ] **Step 1: Add OverviewPanel class**

Append to `toggl/panels.py`:

```python
class LogNegRequested(Message):
    """User clicked Log Neg button in OverviewPanel."""

class LogPosRequested(Message):
    """User clicked Log Pos button in OverviewPanel."""


class OverviewPanel(Container):
    """Overview dashboard panel — categories, recovery, recent log, insights.

    Composes four sub-panels:
      - Categories table (scored project summary)
      - Recovery table (hours needed to recover)
      - Recent activity log
      - Insights widget
    """

    DEFAULT_CSS = """
    OverviewPanel {
        height: 1fr;
    }
    #overview-dashboard {
        height: 1fr;
    }
    #overview-left {
        width: 60%;
        height: 1fr;
    }
    #overview-right {
        width: 40%;
        height: 1fr;
    }
    #overview-recovery-container {
        height: 45%;
        border: round #3d4f63;
        background: #0b1016;
    }
    #overview-recovery-container:focus-within {
        border: round #63f3ff;
    }
    #overview-recovery-table {
        height: 1fr;
        border: none;
    }
    #recovery-button-bar {
        height: auto;
        align: center middle;
        padding: 0 1;
        margin: 0;
    }
    .recovery-btn {
        background: transparent;
        border: none;
        padding: 0 1;
        margin: 0;
        min-width: 0;
        height: 1;
        text-style: bold;
    }
    #btn-neg-log {
        color: #ff5f5f;
    }
    #btn-neg-log:hover {
        color: #ff8080;
        background: #1e2a36;
    }
    #btn-pos-log {
        color: #37d994;
    }
    #btn-pos-log:hover {
        color: #5be8ae;
        background: #1e2a36;
    }
    #overview-insights {
        height: 1fr;
        min-height: 5;
        border: round #3d4f63;
        padding: 0 1;
        background: #0b1016;
        text-align: center;
        content-align: center middle;
    }
    #overview-insights:focus {
        border: round #63f3ff;
    }
    #overview-categories-table {
        height: 1fr;
    }
    #overview-recent-log-wrapper {
        height: 1fr;
        min-height: 4;
        border: round #3d4f63;
    }
    #overview-recent-log-wrapper:focus-within {
        border: round #63f3ff;
    }
    #overview-recent-log-table {
        height: 1fr;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="overview-dashboard"):
            with Vertical(id="overview-left"):
                yield DataTable(
                    zebra_stripes=False, cursor_type="row", id="overview-categories-table"
                )
                yield Static(id="overview-insights")
            with Vertical(id="overview-right"):
                with Vertical(id="overview-recovery-container"):
                    yield DataTable(
                        zebra_stripes=False, cursor_type="row", id="overview-recovery-table"
                    )
                with Vertical(id="overview-recent-log-wrapper"):
                    yield DataTable(
                        zebra_stripes=False, cursor_type="row", id="overview-recent-log-table"
                    )
                    with Horizontal(id="recovery-button-bar"):
                        yield Button("Log Neg", id="btn-neg-log", classes="recovery-btn")
                        yield Button("Log Pos", id="btn-pos-log", classes="recovery-btn")

    def on_mount(self) -> None:
        rec_table = self.query_one("#overview-recovery-table", DataTable)
        rec_table.add_columns("Category", "Rate", "Amount")
        for col in rec_table.columns.values():
            col.text_align = "center"

        cat_table = self.query_one("#overview-categories-table", DataTable)
        cat_table.add_columns("Category", "Hours", "Rate", "Points")
        for col in cat_table.columns.values():
            col.text_align = "center"

        log_table = self.query_one("#overview-recent-log-table", DataTable)
        log_table.add_columns("Date", "Name", "Points")
        log_table.can_focus = True
        log_table.cursor_type = "row"
        for col in log_table.columns.values():
            col.text_align = "center"

        self.query_one("#overview-insights", Static).can_focus = True

        for table_id in [
            "#overview-recovery-table", "#overview-categories-table",
            "#overview-recent-log-table",
        ]:
            try:
                t = self.query_one(table_id, DataTable)
                t.styles.min_height = 1
                t.show_cursor = True
            except Exception:
                pass

    def refresh(self, cache, active_week: str) -> None:
        """Reload all overview panels from the given DataCache."""
        try:
            self._refresh_categories(cache, active_week)
            self._refresh_recovery(cache)
            self._refresh_recent_log(cache)
            self._refresh_insights(cache, active_week)
        except Exception:
            logger.exception("OverviewPanel.refresh failed")

    def _refresh_categories(self, cache, active_week: str) -> None:
        report = MetricsService(cache).get_report_sections("ALL_TIME", "ALL")
        cat_table = self.query_one("#overview-categories-table", DataTable)
        cat_table.clear(columns=False)
        rows = []
        for section_name in ("positive", "negative", "unscored"):
            section_rows = report[section_name]
            if section_rows:
                rows.append(
                    (_fmt_section_header(f"• {section_name.upper()}"),
                     Text(""), Text(""), Text(""))
                )
            rows.extend(
                _render_category_section(
                    section_rows, _fmt_project_tree, _fmt_tree_cells,
                    section_color=SECTION_COLORS.get(section_name.upper(), ""),
                )
            )
        if report["positive_results"]:
            rows.append((_fmt_section_header("• LOGGED POSITIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(report["positive_results"]):
                is_last = (i == len(report["positive_results"]) - 1)
                prefix = "└ " if is_last else "├ "
                rows.append((Text.assemble((prefix, SECTION_COLORS["LOGGED POSITIVE"]), (name, "")), Text(f"×{count}"), fmt_pts_rich(per_event), fmt_pts_rich(total)))
        if report["negative_results"]:
            rows.append((_fmt_section_header("• LOGGED NEGATIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(report["negative_results"]):
                is_last = (i == len(report["negative_results"]) - 1)
                prefix = "└ " if is_last else "├ "
                rows.append((Text.assemble((prefix, SECTION_COLORS["LOGGED NEGATIVE"]), (name, "")), Text(f"×{count}"), fmt_pts_rich(per_event), fmt_pts_rich(total)))
        self._add_rows_mark_sections(cat_table, rows)
        total_hours = report["total_hours"]
        th_h = int(total_hours)
        th_m = int((total_hours - th_h) * 60)
        cat_table.border_title = f"[b][#63f3ff]Lifetime[/][/]   [#8d98a7]{th_h}hrs {th_m:02d}min[/]"
        cat_table.border_subtitle = f"[#8d98a7]Total {format_signed_rich(report['total_points'])} pts[/]"

    def _refresh_recovery(self, cache) -> None:
        recovery_data = cache.get_recovery_rows("ALL_TIME", "ALL")
        rec_table = self.query_one("#overview-recovery-table", DataTable)
        rec_table.clear(columns=False)
        if recovery_data["rows"]:
            recovery_tuples = [
                (r["category"], 0, r["rate"], r["hours_needed"])
                for r in recovery_data["rows"]
            ]
            rec_rows = _render_category_section(
                recovery_tuples, _fmt_project_tree, _fmt_recovery_cells
            )
            rec_table.add_rows(rec_rows)
        rec_container = self.query_one("#overview-recovery-container")
        rec_container.border_title = "[b][#63f3ff]Recovery[/][/]"

    def _refresh_recent_log(self, cache) -> None:
        log_table = self.query_one("#overview-recent-log-table", DataTable)
        log_table.clear(columns=False)
        neg_rows = cache.get_negative_log_rows(limit=30)
        pos_rows = cache.get_positive_log_rows(limit=30)
        combined = []
        for r in neg_rows:
            combined.append({"date": r["date"], "name": r["name"], "points": -r["points"]})
        for r in pos_rows:
            combined.append({"date": r["date"], "name": r["name"], "points": r["points"]})
        combined.sort(key=lambda r: r["date"], reverse=True)
        for entry in combined[:15]:
            pts = entry["points"]
            name_style = "[#37d994]" if pts >= 0 else "[#ff5f5f]"
            log_table.add_row(
                entry["date"],
                Text.from_markup(f"{name_style}{entry['name']}[/]"),
                fmt_pts_rich(pts),
            )
        log_table.move_cursor(row=0)
        self.query_one("#overview-recent-log-wrapper").border_title = "[b][#63f3ff]Recent Activity[/][/]"

    def _refresh_insights(self, cache, active_week: str) -> None:
        insights = self.query_one("#overview-insights", Static)
        week_report = MetricsService(cache).get_report_sections(active_week, "WEEK")
        net = week_report["total_points"]
        insights.update(
            "[#8d98a7]Coming soon™[/]\n\n"
            "[dim]Dynamic insights, trend analysis,\n"
            "and other fancy pants features\n"
            "will appear here. Eventually.\n\n"
            "We heard you like data so we\n"
            "put data in your data.[/]"
        )
        insights.border_title = "[b][#63f3ff]Insights[/][/]"
        insights.border_subtitle = f"[#8d98a7]Week net {format_signed_rich(net)} pts[/]"

    # ── Section-skipping helpers ──

    def _add_rows_mark_sections(self, table: DataTable, rows: list[Any]) -> None:
        """Add rows, marking section headers with keys so cursor skips them."""
        for row in rows:
            first = row[0]
            if isinstance(first, Text) and str(first).startswith("•"):
                table.add_row(*row, key=f"_section_{len(table.rows)}")
            else:
                table.add_row(*row)

    @on(DataTable.RowHighlighted, "#overview-categories-table")
    def _skip_section_rows(self, event: DataTable.RowHighlighted) -> None:
        """Skip past section-header rows so they can't be selected."""
        if event.row_key is None:
            return
        key = str(event.row_key.value)
        if not key.startswith("_section_"):
            return
        table = event.control
        table_keys = list(table.rows.keys())
        total = len(table_keys)
        idx = next(i for i, k in enumerate(table_keys) if str(k.value) == key)
        target = idx + 1 if idx < total - 1 else idx - 1
        if target >= 0:
            table.move_cursor(row=target)

    @on(Button.Pressed, "#btn-neg-log")
    def _on_neg_log(self) -> None:
        self.post_message(LogNegRequested())

    @on(Button.Pressed, "#btn-pos-log")
    def _on_pos_log(self) -> None:
        self.post_message(LogPosRequested())
```

Add the missing imports at the top of panels.py:
```python
from textual.message import Message
from textual.widgets import Button  # already imported
```

- [ ] **Step 2: Verify file parses**

```bash
cd /Users/sai/Downloads/TUI && python -c "from toggl.panels import OverviewPanel, SyncPanel; print('OK')"
```
Expected: OK

- [ ] **Step 3: Update tui.py compose — yield OverviewPanel**

Replace the inline overview content in `compose()`:

```python
# Old:
with Container(id="overview-view", classes="view"):
    with Horizontal(id="overview-dashboard"):
        with Vertical(id="overview-left"):
            yield DataTable(
                zebra_stripes=False, cursor_type="row", id="overview-categories-table"
            )
            yield Static(id="overview-insights")
        with Vertical(id="overview-right"):
            with Vertical(id="overview-recovery-container"):
                yield DataTable(
                    zebra_stripes=False, cursor_type="row", id="overview-recovery-table"
                )
            with Vertical(id="overview-recent-log-wrapper"):
                yield DataTable(
                    zebra_stripes=False, cursor_type="row", id="overview-recent-log-table"
                )
                with Horizontal(id="recovery-button-bar"):
                    yield Button("Log Neg", id="btn-neg-log", classes="recovery-btn")
                    yield Button("Log Pos", id="btn-pos-log", classes="recovery-btn")

# New:
yield OverviewPanel(id="overview-view", classes="view")
```

Add import at top of tui.py:
```python
from toggl.panels import OverviewPanel, SyncPanel
```

- [ ] **Step 4: Update tui.py — refresh_overview_view delegates**

Replace `refresh_overview_view()` method:

```python
def refresh_overview_view(self) -> None:
    """Refresh the Overview dashboard panel."""
    try:
        panel = self.query_one(OverviewPanel)
        panel.refresh(self._data_cache, self._active_week)
    except Exception:
        pass  # Panel may not be mounted yet
```

- [ ] **Step 5: Remove extracted methods from tui.py**

Delete these methods from TogglTUI:
- `_add_rows_mark_sections` (moved to OverviewPanel)
- `_skip_section_rows` (moved to OverviewPanel)
- `on_neg_log_btn` (moved to OverviewPanel)
- `on_pos_log_btn` (moved to OverviewPanel)

- [ ] **Step 6: Update tui.py imports — remove unused**

Remove these from imports if no longer used in tui.py:
- Any formatter functions only used by overview (check: `_fmt_section_header`, `_render_category_section`, `_fmt_project_tree`, `_fmt_tree_cells`, `_fmt_recovery_cells`, `fmt_pts_rich`, `format_signed_rich`, `SECTION_COLORS`)
- `MetricsService` import (used by overview panel now)

Actually, some of these may still be used in tui.py by the sync view or command view. Let's check:
```bash
cd /Users/sai/Downloads/TUI && rg "_fmt_section_header|_render_category_section|_fmt_project_tree|_fmt_tree_cells|_fmt_recovery_cells|fmt_pts_rich|format_signed_rich|SECTION_COLORS|MetricsService" toggl/tui.py
```
Keep any that are still referenced outside the removed methods. Remove those that aren't.

- [ ] **Step 7: Handle LogNegRequested / LogPosRequested messages in App**

Add to TogglTUI:

```python
from toggl.panels import LogNegRequested, LogPosRequested

@on(LogNegRequested)
def on_log_neg_requested(self, event: LogNegRequested) -> None:
    self.action_add_negative()

@on(LogPosRequested)
def on_log_pos_requested(self, event: LogPosRequested) -> None:
    self.action_add_positive()
```

- [ ] **Step 8: Remove overview CSS from theme.tcss**

Delete lines 216-300 from `toggl/styles/theme.tcss` (all `#overview-*`, `.recovery-btn`, `#recovery-button-bar` selectors).

- [ ] **Step 9: Remove overview tables from _setup_tables()**

Delete from `tui.py` `_setup_tables()`:
```python
overview_recovery = self.query_one("#overview-recovery-table", DataTable)
overview_recovery.add_columns("Category", "Rate", "Amount")
for col in overview_recovery.columns.values():
    col.text_align = "center"

overview_cat = self.query_one("#overview-categories-table", DataTable)
overview_cat.add_columns("Category", "Hours", "Rate", "Points")
for col in overview_cat.columns.values():
    col.text_align = "center"

overview_log = self.query_one("#overview-recent-log-table", DataTable)
overview_log.add_columns("Date", "Name", "Points")
overview_log.can_focus = True
overview_log.cursor_type = "row"
for col in overview_log.columns.values():
    col.text_align = "center"

self.query_one("#overview-insights", Static).can_focus = True
```

Also remove overview table IDs from the `for table_id in [...]` loop:
```python
# Keep only:
for table_id in [
    "#overview-recovery-table", "#overview-categories-table",
    "#overview-recent-log-table",
]:
```
Actually remove this entire loop since all overview tables are now in OverviewPanel's on_mount.

- [ ] **Step 10: Clean up unused tui.py imports**

Now that overview and sync are extracted, review the import block and remove any symbols no longer used in tui.py:

```bash
cd /Users/sai/Downloads/TUI && python -c "import py_compile; py_compile.compile('toggl/tui.py', doraise=True); print('OK')"
```

Fix any `F821` undefined-name errors by running:
```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Let failures guide what to fix.

- [ ] **Step 11: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass (16 snapshot failures pre-existing).

---

### Task 3: Final Cleanup & Verification

**Files:**
- Verify: `toggl/tui.py`, `toggl/panels.py`, `toggl/styles/theme.tcss`

- [ ] **Step 1: Remove dead imports**

Run:
```bash
cd /Users/sai/Downloads/TUI && python -c "from toggl.tui import TogglTUI; print('tui OK')"
cd /Users/sai/Downloads/TUI && python -c "from toggl.panels import OverviewPanel, SyncPanel; print('panels OK')"
```

- [ ] **Step 2: Verify e2e tests pass**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/e2e/ -x -q
```

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -v
```
Expected: All non-snapshot tests pass.

- [ ] **Step 4: Check line counts**

```bash
cd /Users/sai/Downloads/TUI && wc -l toggl/tui.py toggl/panels.py
```
Expected: tui.py significantly reduced (was 870 lines, now ~550). panels.py ~280 lines.
