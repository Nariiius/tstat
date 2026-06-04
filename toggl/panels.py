"""OverviewPanel and SyncPanel — standalone view widgets for TogglTUI."""

from __future__ import annotations

import logging
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Static

from toggl.widgets.auto_width_table import AutoWidthDataTable

from toggl.cache import DataCache
from toggl.api import API_RUN_STATS, _format_reset_window
from toggl.formatters import (
    _fmt_recovery_cells,
    _fmt_tree_cells,
    _fmt_project_tree,
    _render_category_section,
    fmt_pts_rich,
    format_signed_rich,
    SECTION_COLORS,
    build_category_rows,
)
from toggl.services.metrics import MetricsService
from toggl.services.insights_bundle import InsightsBundle
from toggl.widgets.insights import (
    DetailedInsightsWidget,
    PlaybookScrollPane,
    format_overview_playbook,
)

logger = logging.getLogger("TStat")


def get_sync_status_data() -> dict[str, Any]:
    import csv, os
    from toggl.const import CSV_FILE, DAILY_CSV_FILE
    from toggl.services.sync import _load_history
    from toggl.api import API_RUN_STATS, get_projects_cache_age_days
    from toggl.cache import get_last_updated_str, get_current_week

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


def compact_sync_status() -> str:
    """One-line Rich-markup sync/quota summary for the Insights tab footer."""
    status = get_sync_status_data()
    parts: list[str] = []

    parts.append(f"[#8d98a7]sync[/] {status['last_updated']}")
    parts.append(f"[#8d98a7]{status['synced_weeks']}w/{status['synced_days']}d cached[/]")

    cache_age = status["projects_cache_age_days"]
    if cache_age is not None:
        age_str = f"{cache_age:.0f}d" if cache_age < 90 else "stale"
        parts.append(f"[#8d98a7]projects {age_str}[/]")
    else:
        parts.append("[#ff5f5f]no projects cache[/]")

    remaining = status["quota_remaining"]
    limit = status["quota_limit"]
    if remaining is not None and limit is not None:
        color = "#ff5f5f" if remaining < 5 else "#8d98a7"
        parts.append(f"[{color}]{remaining}/{limit} quota[/]")
    else:
        parts.append("[#8d98a7]quota unknown[/]")

    return "  ".join(parts)


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
        yield AutoWidthDataTable(
            zebra_stripes=False, cursor_type="row", id="sync-table"
        )

    def on_mount(self) -> None:
        table = self.query_one("#sync-table", AutoWidthDataTable)
        table.add_columns("Metric", "Value")
        table.styles.min_height = 1
        table.show_cursor = True

    def refresh_data(self) -> None:
        """Reload sync status data and repopulate the table."""
        status = get_sync_status_data()
        table = self.query_one("#sync-table", AutoWidthDataTable)
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


class LogNegRequested(Message):
    """User clicked Log Neg button in OverviewPanel."""


class LogPosRequested(Message):
    """User clicked Log Pos button in OverviewPanel."""


class ManageRequested(Message):
    """User clicked Manage button in OverviewPanel."""


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
    #overview-recovery-table,
    #overview-recovery-table:focus,
    #overview-recovery-table:focus-within {
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
        background: #0b1016;
        border: none;
        padding: 0;
        margin: 0;
        min-width: 4;
        height: 1;
        color: #8d98a7;
        text-style: bold;
    }
    #btn-neg-log {
        color: #ff5f5f;
    }
    #btn-neg-log:hover {
        color: #ff8080;
        background: #1e2a36;
        border: none;
    }
    #btn-pos-log {
        color: #37d994;
    }
    #btn-pos-log:hover {
        color: #5be8ae;
        background: #1e2a36;
        border: none;
    }
    #btn-manage {
        color: #63f3ff;
    }
    #btn-manage:hover {
        color: #8de8ff;
        background: #1e2a36;
        border: none;
    }
    #overview-insights {
        height: 1fr;
        min-height: 5;
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
    #overview-recent-log-table,
    #overview-recent-log-table:focus,
    #overview-recent-log-table:focus-within {
        height: 1fr;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="overview-dashboard"):
            with Vertical(id="overview-left"):
                yield AutoWidthDataTable(
                    zebra_stripes=False, cursor_type="row", id="overview-categories-table"
                )
                yield PlaybookScrollPane(id="overview-insights")
            with Vertical(id="overview-right"):
                with Vertical(id="overview-recovery-container"):
                    yield AutoWidthDataTable(
                        zebra_stripes=False, cursor_type="row", id="overview-recovery-table"
                    )
                with Vertical(id="overview-recent-log-wrapper"):
                    yield AutoWidthDataTable(
                        zebra_stripes=False, cursor_type="row", id="overview-recent-log-table"
                    )
                    with Horizontal(id="recovery-button-bar"):
                        yield Button("Log Neg", id="btn-neg-log", classes="recovery-btn")
                        yield Button("Log Pos", id="btn-pos-log", classes="recovery-btn")
                        yield Button("Manage", id="btn-manage", classes="recovery-btn")

    def on_mount(self) -> None:
        rec_table = self.query_one("#overview-recovery-table", DataTable)
        rec_table.add_columns("Category", "Rate", "Amount")
        for col in rec_table.columns.values():
            col.text_align = "center"
        rec_table.styles.border = ("none", None)

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
        log_table.styles.border = ("none", None)


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

    def refresh_data(
        self,
        cache: DataCache,
        active_week: str,
        metrics: MetricsService,
        insights_bundle: InsightsBundle | None = None,
        *,
        insights_loading: bool = False,
        progress_stage: str = "",
    ) -> None:
        """Reload all overview panels from the given DataCache."""
        try:
            self._refresh_categories(cache, active_week, metrics)
            self._refresh_recovery(metrics)
            self._refresh_recent_log(cache)
            self._refresh_insights(
                insights_bundle,
                insights_loading=insights_loading,
                progress_stage=progress_stage,
            )
        except Exception:
            logger.exception("OverviewPanel.refresh_data failed")

    def _refresh_categories(self, cache: DataCache, active_week: str, metrics: MetricsService) -> None:
        report = metrics.get_report_sections("ALL_TIME", "ALL")
        cat_table = self.query_one("#overview-categories-table", DataTable)
        cat_table.clear(columns=False)
        rows = build_category_rows(report)
        self._add_rows_mark_sections(cat_table, rows)
        total_hours = report["total_hours"]
        th_h = int(total_hours)
        th_m = int((total_hours - th_h) * 60)
        cat_table.border_title = f"[b][#63f3ff]Lifetime[/][/]   [#8d98a7]{th_h}hrs {th_m:02d}min[/]"
        cat_table.border_subtitle = f"[#8d98a7]Total {format_signed_rich(report['total_points'])} pts[/]"

    def _refresh_recovery(self, metrics: MetricsService) -> None:
        recovery_data = metrics.get_recovery_rows("ALL_TIME", "ALL")
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

    def _refresh_recent_log(self, cache: DataCache) -> None:
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

    def _refresh_insights(
        self,
        insights_bundle: InsightsBundle | None,
        *,
        insights_loading: bool = False,
        progress_stage: str = "",
    ) -> None:
        insights = self.query_one("#overview-insights", PlaybookScrollPane)
        subtitle = ""
        if insights_bundle and insights_bundle.playbook.context.get("today_net") is not None:
            net = insights_bundle.playbook.context["today_net"]
            subtitle = f"[#8d98a7]Today {format_signed_rich(net)}[/]"
        insights.set_markup(
            format_overview_playbook(
                insights_bundle,
                is_loading=insights_loading,
                progress_stage=progress_stage,
            ),
            border_title="[b][#63f3ff]Playbook[/][/]",
            border_subtitle=subtitle,
        )

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

    @on(Button.Pressed, "#btn-manage")
    def _on_manage(self) -> None:
        self.post_message(ManageRequested())


class InsightsPanel(Container):
    """Insights tab — playbook, coach, and compact sync/quota footer."""

    DEFAULT_CSS = """
    InsightsPanel {
        height: 1fr;
    }
    #insights-panel-inner {
        height: 1fr;
        min-height: 0;
    }
    #insights-detail-widget {
        height: 1fr;
        min-height: 0;
    }
    #insights-sync-line {
        height: auto;
        min-height: 1;
        padding: 0 1;
        text-align: center;
        content-align: center middle;
        border: none;
        background: #0b1016;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="insights-panel-inner"):
            yield DetailedInsightsWidget(id="insights-detail-widget")
            yield Static(id="insights-sync-line")

    def refresh_data(
        self,
        insights_bundle: InsightsBundle | None = None,
        *,
        is_loading: bool = False,
        progress_stage: str = "",
        sync_summary: str | None = None,
    ) -> None:
        widget = self.query_one(DetailedInsightsWidget)
        widget.set_bundle(
            insights_bundle,
            is_loading=is_loading,
            progress_stage=progress_stage,
        )
        sync_line = self.query_one("#insights-sync-line", Static)
        sync_line.update(sync_summary or compact_sync_status())
