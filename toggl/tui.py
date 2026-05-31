"""TogglTUI — Textual terminal UI for TStat."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger("TStat")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    from toggl.const import DATA_DIR
    log_path = os.path.join(DATA_DIR, "sync_debug.log")
    fh = logging.FileHandler(log_path, mode="a")
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

from rich.text import Text
from textual import on
from textual._work_decorator import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click, MouseScrollDown, MouseScrollUp, Resize
from textual.widgets import DataTable, Footer, Label, Static, Tab, Tabs
from textual.worker import Worker, get_current_worker

from toggl.api import (
    TogglAPIError,
    TogglRateLimitError,
    _reset_api_stats,
    get_api_token,
)
from toggl.cache import (
    DataCache,
    get_cache,
    get_current_week,
    get_last_updated_str,
    needs_auto_update,
    reset_cache,
    sync_api_to_csv,
    sync_current_week_light,
)
from toggl.config import (
    load_runtime_settings,
)
from toggl.command import CommandTab
from toggl.panels import LogNegRequested, LogPosRequested, OverviewPanel, SyncPanel
from toggl.neg import (
    log_negative_direct,
    log_positive_direct,
)

from toggl.screens.dialogs import (
    ConfirmScreen,
    NegativeInputScreen,
    PositiveInputScreen,
)


def time_left_in_week() -> str:
    from datetime import datetime, timedelta

    now = datetime.now()
    days_until_saturday = (5 - now.weekday()) % 7
    saturday = now + timedelta(days=days_until_saturday)
    end = saturday.replace(hour=23, minute=59, second=59, microsecond=999999)
    diff = end - now
    if diff.total_seconds() < 0:
        return ""
    days, sec = diff.days, diff.seconds
    hr = sec // 3600
    mn = (sec % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hr > 0:
        parts.append(f"{hr}h")
    parts.append(f"{mn}m")
    return " ".join(parts)


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# MAIN TUI APP
# ──────────────────────────────────────────────


class ScrollableFooter(Footer):
    """Footer with horizontal scroll enabled without visible scrollbar.

    Unmodified mouse wheel scrolls horizontally (fallback when vertical
    scrolling is not possible, e.g. single-row footer).
    """

    @property
    def allow_horizontal_scroll(self) -> bool:
        return self.is_scrollable

    def _on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if event.delta_x:
            # Touchpad horizontal swipe — scroll in delta_x direction
            if self.allow_horizontal_scroll:
                self._clear_anchor()
                moved = (
                    self._scroll_right_for_pointer(animate=False)
                    if event.delta_x > 0
                    else self._scroll_left_for_pointer(animate=False)
                )
                if moved:
                    event.stop()
        elif event.ctrl or event.shift:
            if self.allow_horizontal_scroll:
                self._clear_anchor()
                if self._scroll_right_for_pointer(animate=False):
                    event.stop()
        else:
            if self.allow_vertical_scroll:
                self._clear_anchor()
                if self._scroll_down_for_pointer(animate=False):
                    event.stop()
            elif self.allow_horizontal_scroll:
                # Fall back to horizontal when vertical can't scroll
                self._clear_anchor()
                if self._scroll_right_for_pointer(animate=False):
                    event.stop()

    def _on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if event.delta_x:
            # Touchpad horizontal swipe — scroll in delta_x direction
            if self.allow_horizontal_scroll:
                self._clear_anchor()
                moved = (
                    self._scroll_right_for_pointer(animate=False)
                    if event.delta_x > 0
                    else self._scroll_left_for_pointer(animate=False)
                )
                if moved:
                    event.stop()
        elif event.ctrl or event.shift:
            if self.allow_horizontal_scroll:
                self._clear_anchor()
                if self._scroll_left_for_pointer(animate=False):
                    event.stop()
        else:
            if self.allow_vertical_scroll:
                self._clear_anchor()
                if self._scroll_up_for_pointer(animate=False):
                    event.stop()
            elif self.allow_horizontal_scroll:
                # Fall back to horizontal when vertical can't scroll
                self._clear_anchor()
                if self._scroll_left_for_pointer(animate=False):
                    event.stop()


class TogglTUI(App):
    CSS_PATH = "styles/theme.tcss"

    BINDINGS = [
        Binding("ctrl+left", "prev_view", "Prev"),
        Binding("ctrl+right", "next_view", "Next"),
        Binding("q", "quit", "Quit", show=False),
        Binding("r", "refresh_data", "Refresh"),
        Binding("u", "sync_current_week", "Sync"),
        Binding("U", "sync_full", "Full Sync"),
        Binding("n", "add_negative", "Neg"),
        Binding("p", "add_positive", "Pos"),
        Binding("z", "cmd_zoom_in", "Zoom+", show=False),
        Binding("Z", "cmd_zoom_out", "Zoom-", show=False),
    ]

    VIEWS = [
        "Overview",
        "Command",
        "Sync/Quota",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._initialized = False
        self.active_view_index = 0  # Overview view is the default landing view
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self._table_resize_timer = None
        self._data_cache: DataCache | None = None
        self._active_week = get_current_week()

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Container(id="chrome"):
                yield Label("TStat v1.3.1", classes="app-title")
                tabs = Tabs(
                    *[Tab(view, id=f"tab-{index}") for index, view in enumerate(self.VIEWS)],
                    id="view-tabs",
                )
                tabs.can_focus = False
                yield tabs
                yield Static(id="sync-status", classes="sync-status")
            with Horizontal(id="main"):
                with Container(id="content"):
                    yield OverviewPanel(id="overview-view", classes="view")
                    with Container(id="command-view", classes="view"):
                        yield CommandTab()
                    yield SyncPanel(id="sync-view", classes="view")
                with Vertical(id="spark-rail"):
                    pass
        yield ScrollableFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self._setup_tables()
        load_runtime_settings()
        # Set initial tab silently (prevent auto-activation of tab-0)
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"
        if needs_auto_update():
            self._do_auto_refresh()
        # Defer data loading to ensure child widget on_mount() has run
        # so their DataTables have columns set up before refresh.
        self.call_later(self.load_data)
        self.query_one(ScrollableFooter).refresh_bindings()

    @work(thread=False, exclusive=True)
    async def load_data(self) -> None:
        """Load cache data in background worker."""
        self._data_cache = DataCache.load()
        self.refresh_all_views()

    @work(thread=True)
    def _do_auto_refresh(self) -> None:
        try:
            result = sync_current_week_light(auto_refresh=True, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError):
            result = {"success": False, "message": "API error during auto-refresh"}
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_auto_refresh_done, ok, message)

    def _on_auto_refresh_done(self, ok: bool, message: str) -> None:
        load_runtime_settings()
        self.refresh_all_views()
        if ok:
            self.notify("Auto-refreshed stale data")
        else:
            self.notify(message or "Auto-refresh failed", severity="warning")

    def _setup_tables(self) -> None:
        # All view tables are now managed by their respective widget panels.
        pass

    def refresh_all_views(self) -> None:
        if self._data_cache is None:
            logger.debug("[SYNC] refresh_all_views: deferred — data not loaded yet")
            return
        logger.debug("[SYNC] refresh_all_views: start")
        self.update_tabs()
        self.update_status_line()
        for idx in self._VIEW_REFRESH_MAP:
            self._refresh_view_by_index(idx)
        self.update_view_visibility()
        self._schedule_resize()
        logger.debug("[SYNC] refresh_all_views: done")

    _VIEW_REFRESH_MAP = {
        0: "refresh_overview_view",
        1: "refresh_command_view",
        2: "refresh_sync_view",
    }

    def _refresh_view_by_index(self, index: int) -> None:
        method_name = self._VIEW_REFRESH_MAP.get(index)
        if method_name:
            logger.debug("[SYNC] _refresh_view_by_index(%d) → %s", index, method_name)
            try:
                getattr(self, method_name)()
            except Exception as e:
                logger.exception("[SYNC] %s FAILED", method_name)

    def _schedule_resize(self) -> None:
        if self._table_resize_timer is not None:
            self._table_resize_timer.stop()
        self._table_resize_timer = self.set_timer(0.1, self._resize_tables)

    def update_tabs(self) -> None:
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"

    def update_status_line(self) -> None:
        current_week = get_current_week()
        synced = get_last_updated_str()

        sync_widget = self.query_one("#sync-status", Static)
        sync_widget.update(f"\u27f3\u2002{synced}")

    def update_view_visibility(self) -> None:
        view_ids = [
            "#overview-view",
            "#command-view",
            "#sync-view",
        ]
        for index, view_id in enumerate(view_ids):
            widget = self.query_one(view_id, Container)
            widget.set_class(index == self.active_view_index, "-active")

    def focus_active_view(self) -> None:
        focus_targets = {
            0: "#overview-categories-table",
            1: "#command-container",
            2: "#sync-table",
        }
        selector = focus_targets.get(self.active_view_index)
        if selector:
            self.query_one(selector).focus()
        self.query_one(ScrollableFooter).refresh_bindings()

    # ── Helpers ──

    def refresh_overview_view(self) -> None:
        """Refresh the Overview dashboard panel."""
        try:
            panel = self.query_one(OverviewPanel)
            panel.refresh_data(self._data_cache, self._active_week)
        except Exception:
            pass  # Panel may not be mounted yet
    def refresh_command_view(self) -> None:
        """Refresh the Command tab's graph and controls."""
        try:
            cmd_tab = self.query_one(CommandTab)
            cmd_tab.data_cache = self._data_cache
            cmd_tab.refresh_all()
        except Exception:
            pass  # Container may not be mounted yet

    def refresh_sync_view(self) -> None:
        """Refresh the Sync/Quota panel."""
        try:
            panel = self.query_one(SyncPanel)
            panel.refresh_data()
        except Exception:
            pass  # Panel may not be mounted yet
    @on(Tabs.TabActivated, "#view-tabs")
    def on_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id and event.tab.id.startswith("tab-"):
            # Guard against stale events: verify this tab is actually active
            tabs = self.query_one("#view-tabs", Tabs)
            if tabs.active != event.tab.id:
                return
            new_index = int(event.tab.id.rsplit("-", 1)[1])
            if new_index == self.active_view_index:
                return
            self.active_view_index = new_index
            self._refresh_view_by_index(self.active_view_index)
            self.update_tabs()
            self.update_view_visibility()
            self.update_status_line()
            self.focus_active_view()
            self._schedule_resize()

    def action_next_view(self) -> None:
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_line()
        self.focus_active_view()
        self._schedule_resize()

    def action_prev_view(self) -> None:
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_line()
        self.focus_active_view()
        self._schedule_resize()

    def action_refresh_data(self) -> None:
        load_runtime_settings()
        self._data_cache = DataCache.load()
        self.refresh_all_views()
        self.notify("Reloaded local data")

    def action_show_help(self) -> None:
        self.notify(
            "Left/right switch views, n add negative, u sync, U full sync, "
            "q quit"
        )

    def action_sync_current_week(self) -> None:
        logger.debug("[SYNC] action_sync_current_week: user pressed 'u'")
        def after_confirm(confirmed: bool) -> None:
            if confirmed:
                self.notify("Syncing current week...")
                self._do_sync_current_week()

        self.push_screen(
            ConfirmScreen("Sync current week", "Run a current-week sync now?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_current_week(self) -> None:
        logger.debug("[SYNC] _do_sync_current_week: starting")
        try:
            result = sync_current_week_light(prompt_on_warning=False)
            logger.debug("[SYNC] sync_current_week_light returned: %s", result)
        except (TogglRateLimitError, TogglAPIError) as e:
            logger.exception("[SYNC] Toggl API error during sync")
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        except Exception as e:
            logger.exception("[SYNC] Unexpected error in sync worker")
            self.call_from_thread(self.notify, f"Sync error: {e}", severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        logger.debug("[SYNC] calling _on_sync_done: ok=%s, message=%s", ok, message)
        self.call_from_thread(self._on_sync_done, ok, message, "Synced current week")

    def action_sync_full(self) -> None:
        def after_confirm(confirmed: bool) -> None:
            if confirmed:
                self.notify("Syncing last 4 weeks...")
                self._do_sync_full()

        self.push_screen(
            ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_full(self) -> None:
        try:
            result = sync_api_to_csv(4, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_sync_done, ok, message, "Synced last 4 weeks")

    def _on_sync_done(self, ok: bool, message: str, success_msg: str) -> None:
        logger.debug("[SYNC] _on_sync_done: ok=%s, message=%s", ok, message)
        load_runtime_settings()
        reset_cache()
        self._data_cache = get_cache()
        try:
            self.refresh_all_views()
            logger.debug("[SYNC] refresh_all_views completed")
        except Exception as e:
            logger.exception("[SYNC] refresh_all_views FAILED")
            self.notify(f"View refresh error: {e}", severity="error")
            return
        if ok:
            self.notify(success_msg)
        else:
            self.notify(message or "Sync skipped", severity="warning")
    def action_add_negative(self) -> None:
        def after_input(value: str | None) -> None:
            if value:
                ok, message = log_negative_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(NegativeInputScreen(), after_input)

    def action_add_positive(self) -> None:
        def after_input(value: str | None) -> None:
            if value:
                ok, message = log_positive_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(PositiveInputScreen(), after_input)

    def action_cmd_zoom_in(self) -> None:
        if self.active_view_index == 1:
            self.query_one(CommandTab)._on_zoom_in()

    def action_cmd_zoom_out(self) -> None:
        if self.active_view_index == 1:
            self.query_one(CommandTab)._on_zoom_out()


    @on(LogNegRequested)
    def on_log_neg_requested(self) -> None:
        self.action_add_negative()

    @on(LogPosRequested)
    def on_log_pos_requested(self) -> None:
        self.action_add_positive()

    def on_resize(self, event: Resize) -> None:
        new_size = event.size
        if new_size.width == 0 or new_size.height == 0:
            return
        self._schedule_resize()

    def _resize_tables(self) -> None:
        """Resize tables. SyncPanel handles its own sizing."""
