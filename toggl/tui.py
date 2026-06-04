"""TogglTUI — Textual terminal UI for TStat."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
logger = logging.getLogger("TStat")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    from toggl.const import DATA_DIR
    log_path = os.path.join(DATA_DIR, "sync_debug.log")
    fh = logging.FileHandler(log_path, mode="a")
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

from textual import on
from textual.geometry import Offset
from textual._work_decorator import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Enter, Leave, MouseMove, MouseScrollDown, MouseScrollUp, Resize
from textual.reactive import reactive
from textual.widgets import Footer, Label, Static, Tab, Tabs

from toggl.const import __version__
from toggl.widgets.icons import ICON, ICON_GAP, icon_text, spinner_frame

from toggl.api import (
    TogglAPIError,
    TogglRateLimitError,
)
from toggl.cache import (
    DataCache,
    format_time_ago_short,
    get_cache,
    get_current_week,
    get_last_api_sync_time,
    needs_auto_update,
    reset_cache,
)
from toggl.services.sync import sync_api_to_csv, sync_current_week_light
from toggl.config import (
    Config,
    load_runtime_settings,
    POINTS,
    NEGATIVES,
    POSITIVES,
    RECOVERY_IGNORE,
    get_daily_target,
)
from toggl.services.metrics import MetricsService
from toggl.services.insights_bundle import InsightsBundle, InsightsBundleService
from toggl.command import CommandTab
from toggl.panels import (
    InsightsPanel,
    LogNegRequested,
    LogPosRequested,
    ManageRequested,
    OverviewPanel,
    compact_sync_status_parts,
)
from toggl.widgets.insights import format_command_playbook_line
from toggl.widgets.tables import CategoryTable
from toggl.neg import log_activity_direct

from toggl.screens.dialogs import (
    ConfirmScreen,
    NegativeInputScreen,
    PositiveInputScreen,
)
from toggl.screens.manage import ManageScreen


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
        Binding("r", "refresh_data", "Refresh", show=False),
        Binding("u", "sync_current_week", "Sync", show=False),
        Binding("U", "sync_full", "Full Sync", show=False),
        Binding("n", "add_negative", "Neg"),
        Binding("p", "add_positive", "Pos"),
        Binding("m", "manage_logs", "Manage"),
        Binding("z", "cmd_zoom_in", "Zoom+", show=False),
        Binding("Z", "cmd_zoom_out", "Zoom-", show=False),
    ]

    VIEWS = [
        "Overview",
        "Command",
        "Insights",
    ]

    # Reactive state: triggers watch_data_cache on every assignment
    data_cache: reactive[DataCache | None] = reactive[DataCache | None](None)
    insights_bundle: reactive[InsightsBundle | None] = reactive[InsightsBundle | None](None)
    _progress_stage: reactive[str] = reactive("")
    _insights_computing: reactive[bool] = reactive(False)

    def __init__(self, *, preloaded_cache: DataCache | None = None) -> None:
        super().__init__()
        self._preloaded_cache = preloaded_cache
        self._initialized = False
        self.active_view_index = 1  # Command tab is the default landing view
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self._table_resize_timer = None
        self._active_week = get_current_week()
        self._sync_in_progress = False
        self._spin_timer = None
        self._metrics: MetricsService | None = None
        self._insights_service: InsightsBundleService | None = None
        self._insights_generation_id = 0
        self._reload_local_at: datetime | None = None
        self._reload_cache_at: datetime | None = None
        self._reload_api_at: datetime | None = None
        self._reload_anim = {"local": False, "cache": False, "api": False}
        self._status_message = ""
        self._status_severity = "information"
        self._status_clear_timer = None
        self._reload_tick_timer = None
        self._chip_tips: dict[str, str] = {}
        self._tip_show_timer = None
        self._hover_tip_chip: Static | None = None
        self._hover_tip_visible = False

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Container(id="chrome"):
                yield Label(f"TStat v{__version__}", classes="app-title")
                tabs = Tabs(
                    *[Tab(view, id=f"tab-{index}") for index, view in enumerate(self.VIEWS)],
                    id="view-tabs",
                )
                tabs.can_focus = False
                yield tabs
                with Horizontal(id="reload-status"):
                    yield Static("", id="reload-local", classes="reload-chip")
                    yield Static("", id="reload-cache", classes="reload-chip")
                    yield Static("", id="reload-api", classes="reload-chip")
            with Horizontal(id="main"):
                with Container(id="content"):
                    yield OverviewPanel(id="overview-view", classes="view")
                    with Container(id="command-view", classes="view"):
                        yield CommandTab()
                    yield InsightsPanel(id="insights-view", classes="view")
                with Vertical(id="spark-rail"):
                    pass
        with Horizontal(id="bottom-bar"):
            yield ScrollableFooter(show_command_palette=False, id="app-footer")
            with Horizontal(id="status-tray"):
                yield Static("", id="status-message-inline")
                yield Static("", id="meta-coverage", classes="status-meta-chip")
                yield Static("", id="meta-projects", classes="status-meta-chip")
                yield Static("", id="meta-quota", classes="status-meta-chip")
        yield Static("", id="hover-tip")

    def on_mount(self) -> None:
        load_runtime_settings()
        # Set initial tab silently (prevent auto-activation of tab-0)
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"
        self.query_one(ScrollableFooter).refresh_bindings()
        self._reload_api_at = get_last_api_sync_time()
        self._setup_status_tooltips()
        self.update_status_bar()
        self._reschedule_reload_tick()
        # Defer data loading to ensure child widget on_mount() has run
        # so their DataTables have columns set up before refresh.
        self.call_later(self.load_data)

        # Check for auto-sync immediately after mounting and then every 60 seconds
        # (Skip in testing environments to prevent visual test notifications)
        import sys
        if "pytest" not in sys.modules:
            self.call_later(self.check_auto_sync)
            self.set_interval(60, self.check_auto_sync)

    def _setup_status_tooltips(self) -> None:
        self._chip_tips = {
            "reload-local": (
                "Local CSV cache\n"
                "Time since local data was reloaded\n"
                "Shortcut: r"
            ),
            "reload-cache": (
                "Insights cache\n"
                "Time since playbook data was loaded or saved\n"
                "Updates after reload and compute"
            ),
            "reload-api": (
                "Toggl API sync\n"
                "Time since the last API fetch\n"
                "Shortcuts: u (week)  U (full)"
            ),
            "meta-coverage": (
                "Sync coverage\n"
                "Weeks and days stored in local CSV files"
            ),
            "meta-projects": (
                "Projects cache\n"
                "Age of the cached Toggl project list"
            ),
            "meta-quota": (
                "API quota\n"
                "Hourly Toggl requests remaining / limit"
            ),
        }

    def _format_hover_tip(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        head = f"[#63f3ff]{lines[0]}[/]"
        if len(lines) == 1:
            return head
        body = "\n".join(f"[#8d98a7]{line}[/]" for line in lines[1:])
        return f"{head}\n{body}"

    def _status_chip_for_point(self, screen_x: int, screen_y: int) -> Static | None:
        """Return a status/reload chip under the screen coordinates, if any."""
        try:
            widget, _ = self.screen.get_widget_at(screen_x, screen_y)
        except Exception:
            return None
        node = widget
        while node is not None:
            if isinstance(node, Static) and node.id in self._chip_tips:
                return node
            node = node.parent
        return None

    def _position_hover_tip(self, chip: Static) -> None:
        """Place the hover tip fully inside the screen (bottom chips clip easily)."""
        try:
            tip = self.query_one("#hover-tip", Static)
            chip_r = chip.region
            if chip_r.width <= 0 or chip_r.height <= 0:
                return
            tip.refresh(layout=True)
            tip_h = max(1, tip.outer_size.height)
            tip_w = max(1, tip.outer_size.width)
            screen = self.screen.size
            margin = 1

            chip_mid = chip_r.y + chip_r.height // 2
            prefer_above = chip_mid > screen.height // 2
            above_y = chip_r.y - tip_h - margin
            below_y = chip_r.y + chip_r.height + margin
            placements = (
                (above_y, below_y) if prefer_above else (below_y, above_y)
            )
            y = None
            for candidate in placements:
                if candidate >= 0 and candidate + tip_h <= screen.height:
                    y = candidate
                    break
            if y is None:
                y = max(0, min(above_y, screen.height - tip_h))

            if chip_r.right >= screen.width - 2:
                x = chip_r.right - tip_w
            else:
                x = chip_r.x
            x = max(0, min(x, screen.width - tip_w))

            tip.absolute_offset = Offset(x, y)
        except Exception:
            pass

    def _schedule_hover_tip(self, chip: Static) -> None:
        self._hover_tip_chip = chip
        if self._tip_show_timer is not None:
            self._tip_show_timer.stop()
        self._tip_show_timer = self.set_timer(0.35, self._show_hover_tip)

    def _show_hover_tip(self) -> None:
        self._tip_show_timer = None
        chip = self._hover_tip_chip
        if chip is None or not chip.id:
            return
        pos = self.app.mouse_position
        if pos is not None and self._status_chip_for_point(*pos) is not chip:
            self._hide_hover_tip()
            return
        text = self._chip_tips.get(chip.id)
        if not text:
            return
        tip = self.query_one("#hover-tip", Static)
        tip.update(self._format_hover_tip(text))
        tip.display = True
        self._hover_tip_visible = True
        self._position_hover_tip(chip)
        self.call_after_refresh(self._position_hover_tip, chip)

    def _hide_hover_tip(self) -> None:
        if self._tip_show_timer is not None:
            self._tip_show_timer.stop()
            self._tip_show_timer = None
        self._hover_tip_chip = None
        self._hover_tip_visible = False
        try:
            tip = self.query_one("#hover-tip", Static)
            tip.display = False
            tip.absolute_offset = None
            tip.update("")
        except Exception:
            pass

    @on(Enter, ".reload-chip, .status-meta-chip")
    def _on_status_chip_enter(self, event: Enter) -> None:
        chip = event.control
        if not isinstance(chip, Static) or not chip.id:
            return
        if chip.id not in self._chip_tips:
            return
        self._schedule_hover_tip(chip)

    @on(Leave, ".reload-chip, .status-meta-chip")
    def _on_status_chip_leave(self, event: Leave) -> None:
        if self._hover_tip_chip is event.control:
            self._hide_hover_tip()

    @on(MouseMove)
    def _on_mouse_move_hover_tip(self, event: MouseMove) -> None:
        """Keep tooltip visibility in sync with the pointer (Leave can be missed)."""
        if not self._chip_tips:
            return
        chip = self._status_chip_for_point(event.screen_x, event.screen_y)
        if chip is not None:
            if chip is not self._hover_tip_chip:
                self._schedule_hover_tip(chip)
            elif self._hover_tip_visible:
                self._position_hover_tip(chip)
            return
        if self._hover_tip_visible or self._hover_tip_chip or self._tip_show_timer:
            self._hide_hover_tip()

    def _needs_second_reload_ticks(self) -> bool:
        now = datetime.now()
        for at in (self._reload_local_at, self._reload_cache_at, self._reload_api_at):
            if at is None:
                continue
            if (now - at).total_seconds() < 60:
                return True
        return False

    def _reschedule_reload_tick(self) -> None:
        if self._reload_tick_timer is not None:
            self._reload_tick_timer.stop()
        interval = 1.0 if self._needs_second_reload_ticks() else 60.0
        self._reload_tick_timer = self.set_timer(interval, self._on_reload_age_tick)

    def _on_reload_age_tick(self) -> None:
        self.update_status_bar()
        self._reschedule_reload_tick()

    def show_status(
        self,
        message: str,
        *,
        severity: str = "information",
        timeout: float = 5.0,
    ) -> None:
        """Thread-safe status bar wrapper (usable from ``call_from_thread``)."""
        self.post_status(message, severity=severity, timeout=timeout)

    def post_status(
        self,
        message: str,
        *,
        severity: str = "information",
        timeout: float = 5.0,
    ) -> None:
        """Show a transient message pinned to the right of the bottom bar."""
        self._status_message = message
        self._status_severity = severity
        self.update_status_bar()
        if self._status_clear_timer is not None:
            self._status_clear_timer.stop()
        self._status_clear_timer = self.set_timer(timeout, self._clear_status_message)

    def _clear_status_message(self) -> None:
        self._status_message = ""
        self._status_severity = "information"
        self.update_status_bar()

    def _mark_local_reload(self) -> None:
        self._reload_local_at = datetime.now()
        self.update_status_bar()
        self._reschedule_reload_tick()

    def _mark_cache_reload(self) -> None:
        self._reload_cache_at = datetime.now()
        self.update_status_bar()
        self._reschedule_reload_tick()

    def _mark_api_reload(self) -> None:
        self._reload_api_at = datetime.now()
        self.update_status_bar()
        self._reschedule_reload_tick()

    def _is_segment_animating(self, kind: str) -> bool:
        if kind == "api" and self._sync_in_progress:
            return True
        return self._reload_anim.get(kind, False)

    def _pulse_reload(self, kind: str) -> None:
        self._reload_anim[kind] = True
        self._ensure_reload_spin()
        self.update_status_bar()

    def _pulse_all_reloads(self) -> None:
        for kind in self._reload_anim:
            self._reload_anim[kind] = True
        self._ensure_reload_spin()
        self.update_status_bar()

    def _stop_pulse(self, kind: str) -> None:
        self._reload_anim[kind] = False
        self._ensure_reload_spin()
        self.update_status_bar()

    def _ensure_reload_spin(self) -> None:
        if any(self._reload_anim.values()) or self._sync_in_progress:
            self._start_reload_spin()
        else:
            self._stop_reload_spin()

    def _reload_segment(self, kind: str, icon_key: str, at: datetime | None) -> str:
        age = format_time_ago_short(at)
        if self._is_segment_animating(kind):
            glyph = spinner_frame(getattr(self, "_spin_frame", 0))
            return f"[#63f3ff]{glyph}{ICON_GAP}{age}[/]"
        return icon_text(icon_key, age)

    def update_status_bar(self) -> None:
        try:
            msg_widget = self.query_one("#status-message-inline", Static)
            meta_coverage = self.query_one("#meta-coverage", Static)
            meta_projects = self.query_one("#meta-projects", Static)
            meta_quota = self.query_one("#meta-quota", Static)
            reload_local = self.query_one("#reload-local", Static)
            reload_cache = self.query_one("#reload-cache", Static)
            reload_api = self.query_one("#reload-api", Static)
        except Exception:
            return

        if self._status_message:
            colors = {
                "information": "#8d98a7",
                "warning": "#e2b714",
                "error": "#ff5f5f",
            }
            prefixes = {"information": "", "warning": "WARN: ", "error": "ERR: "}
            color = colors.get(self._status_severity, "#8d98a7")
            prefix = prefixes.get(self._status_severity, "")
            msg_widget.update(f"[{color}]{prefix}{self._status_message}[/]")
        else:
            msg_widget.update("")

        if self.data_cache is not None:
            coverage, projects, quota = compact_sync_status_parts()
            meta_coverage.update(coverage)
            meta_projects.update(projects)
            meta_quota.update(quota)
        else:
            meta_coverage.update("")
            meta_projects.update("")
            meta_quota.update("")

        reload_local.update(
            self._reload_segment("local", "reload_local", self._reload_local_at)
        )
        reload_cache.update(
            self._reload_segment("cache", "reload_cache", self._reload_cache_at)
        )
        reload_api.update(
            self._reload_segment("api", "reload_api", self._reload_api_at)
        )
        if self._hover_tip_visible and self._hover_tip_chip is not None:
            pos = self.app.mouse_position
            if pos and self._status_chip_for_point(*pos) is self._hover_tip_chip:
                self._position_hover_tip(self._hover_tip_chip)
            else:
                self._hide_hover_tip()

    def _build_metrics(self, cache: DataCache) -> MetricsService:
        """Create MetricsService from a DataCache instance using current config globals."""
        return MetricsService(
            cache,
            dict(POINTS),
            dict(NEGATIVES),
            dict(POSITIVES),
            list(RECOVERY_IGNORE),
            get_daily_target,
        )

    def _build_insights_service(
        self, cache: DataCache, metrics: MetricsService
    ) -> InsightsBundleService:
        return InsightsBundleService(metrics, cache, Config.load(), get_daily_target)

    def watch_data_cache(self, cache: DataCache | None) -> None:
        """Reactively refresh all views when data_cache changes."""
        if cache is not None:
            self.refresh_all_views()

    def watch_insights_bundle(self, bundle: InsightsBundle | None) -> None:
        if bundle is not None:
            try:
                self.refresh_overview_view()
                self.refresh_command_view()
                self.refresh_insights_view()
            except Exception:
                pass

    def watch__progress_stage(self, stage: str) -> None:
        """Refresh playbook panes whenever compute progress stage changes."""
        if not self._insights_computing:
            return
        try:
            self.refresh_overview_view()
            self.refresh_insights_view()
        except Exception:
            pass

    @work(thread=False, exclusive=True)
    async def load_data(self) -> None:
        """Load cache data asynchronously (I/O runs in thread pool)."""
        import asyncio

        self._pulse_all_reloads()
        try:
            if self._preloaded_cache is not None:
                cache = self._preloaded_cache
                self._preloaded_cache = None
            else:
                cache = await asyncio.to_thread(DataCache.load)

            self._metrics = self._build_metrics(cache)
            self.data_cache = cache
            self._insights_service = self._build_insights_service(cache, self._metrics)
            cached = self._insights_service.try_load_cache()
            if cached:
                self.insights_bundle = cached
                self._mark_cache_reload()

            self._compute_insights_in_background()
            self._mark_local_reload()
            self._stop_pulse("local")
        except Exception:
            self._stop_pulse("local")
            if not self._sync_in_progress:
                self._stop_pulse("cache")
                self._stop_pulse("api")
            raise

    def check_auto_sync(self) -> None:
        """Periodic auto-sync check running in background."""
        if self._sync_in_progress:
            logger.debug("[SYNC] check_auto_sync: sync already in progress, skipping auto-refresh check")
            return
        try:
            if needs_auto_update():
                logger.debug("[SYNC] check_auto_sync: auto-refresh is needed, starting background job")
                self._do_auto_refresh()
            else:
                logger.debug("[SYNC] check_auto_sync: cache is up-to-date")
        except Exception as e:
            logger.exception("[SYNC] Exception during check_auto_sync")

    @work(thread=True)
    def _do_auto_refresh(self) -> None:
        logger.debug("[SYNC] _do_auto_refresh: starting background auto-refresh thread")
        self.call_from_thread(self._set_sync_active)
        try:
            result = sync_current_week_light(auto_refresh=True, prompt_on_warning=False)
            logger.debug("[SYNC] _do_auto_refresh: result = %s", result)
            ok = result.get("success", False)
            message = result.get("message", "")
            self.call_from_thread(self._on_auto_refresh_done, ok, message)
        except (TogglRateLimitError, TogglAPIError) as e:
            logger.exception("[SYNC] Toggl API error during auto-refresh")
            self.call_from_thread(self._on_auto_refresh_done, False, f"API error: {e}")
        except Exception as e:
            logger.exception("[SYNC] Unexpected exception during auto-refresh")
            self.call_from_thread(self._on_auto_refresh_done, False, f"Unexpected error: {e}")

    def _on_auto_refresh_done(self, ok: bool, message: str) -> None:
        load_runtime_settings()
        self._pulse_reload("local")
        reset_cache()
        cache = get_cache()
        self._metrics = self._build_metrics(cache)
        self.data_cache = cache
        if cache:
            self._insights_service = self._build_insights_service(cache, self._metrics)
            self._compute_insights_in_background()
        if ok:
            self._mark_api_reload()
            self._mark_local_reload()
            self.show_status("Pulled fresh data from Toggl automatically.")
        else:
            self.show_status(
                message or "Could not refresh stale data.",
                severity="warning",
            )
        self._stop_pulse("local")
        self._set_sync_inactive()

    def refresh_all_views(self) -> None:
        if self.data_cache is None:
            logger.debug("[SYNC] refresh_all_views: deferred — data not loaded yet")
            return
        logger.debug("[SYNC] refresh_all_views: start")
        self.update_tabs()
        self.update_status_bar()
        for idx in self._VIEW_REFRESH_MAP:
            self._refresh_view_by_index(idx)
        self.update_view_visibility()
        self.focus_active_view()
        self._schedule_resize()
        logger.debug("[SYNC] refresh_all_views: done")

    _VIEW_REFRESH_MAP = {
        0: "refresh_overview_view",
        1: "refresh_command_view",
        2: "refresh_insights_view",
    }

    def _compute_insights_in_background(self) -> None:
        if self._insights_service is None:
            return
        gen_id = self._insights_generation_id + 1
        self._insights_generation_id = gen_id
        self._insights_computing = True
        self._progress_stage = ""
        self._pulse_reload("cache")
        if not self._sync_in_progress:
            self._pulse_reload("api")
        try:
            self.refresh_overview_view()
            self.refresh_insights_view()
        except Exception:
            pass
        self._run_insight_compute(gen_id)

    @work(thread=True)
    def _run_insight_compute(self, gen_id: int) -> None:
        try:
            svc = self._insights_service
            if svc is None:
                self.call_from_thread(self._on_insights_compute_failed)
                return
            bundle = svc.compute(
                on_progress=lambda stage: self.call_from_thread(
                    self._set_progress_stage, stage
                )
            )
            self.call_from_thread(self._on_insights_computed, bundle, gen_id)
        except Exception:
            logger.exception("Insights bundle computation failed")
            self.call_from_thread(self._on_insights_compute_failed)

    def _on_insights_compute_failed(self) -> None:
        self._insights_computing = False
        self._progress_stage = ""
        self._stop_pulse("cache")
        if not self._sync_in_progress:
            self._stop_pulse("api")
        try:
            self.refresh_overview_view()
            self.refresh_insights_view()
        except Exception:
            pass

    def _set_progress_stage(self, stage: str) -> None:
        self._progress_stage = stage

    def _on_insights_computed(self, bundle: InsightsBundle, gen_id: int) -> None:
        if gen_id < self._insights_generation_id:
            return
        self._insights_generation_id = gen_id
        self._insights_computing = False
        self._progress_stage = ""
        if self._insights_service:
            self._insights_service.save_cache(bundle)
        self._mark_cache_reload()
        self._stop_pulse("cache")
        if not self._sync_in_progress:
            self._stop_pulse("api")
        self.insights_bundle = bundle

    def _refresh_view_by_index(self, index: int) -> None:
        method_name = self._VIEW_REFRESH_MAP.get(index)
        if method_name:
            logger.debug("[SYNC] _refresh_view_by_index(%d) -> %s", index, method_name)
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

    def focus_active_view(self) -> None:
        focus_targets = {
            0: "#overview-categories-table",
            1: "#cmd-graph",
            2: "#insights-detail-widget",
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
            panel.refresh_data(
                self.data_cache,
                self._active_week,
                self._metrics,
                self.insights_bundle,
                insights_loading=self._insights_computing,
                progress_stage=self._progress_stage if self._insights_computing else "",
            )
        except Exception:
            pass  # Panel may not be mounted yet

    def refresh_command_view(self) -> None:
        """Refresh the Command tab's graph and controls."""
        try:
            cmd_tab = self.query_one(CommandTab)
            cmd_tab.data_cache = self.data_cache
            cmd_tab.metrics = self._metrics
            cmd_tab.refresh_all()
            self._refresh_command_playbook_line(cmd_tab)
        except Exception:
            pass  # Container may not be mounted yet

    def _refresh_command_playbook_line(self, cmd_tab: CommandTab) -> None:
        if cmd_tab.period.mode != "month":
            return
        line = format_command_playbook_line(self.insights_bundle)
        if not line:
            return
        try:
            cat_table = cmd_tab.query_one(CategoryTable)
            cat_table.border_subtitle = f"[#8d98a7]{line}[/]"
        except Exception:
            pass

    def refresh_insights_view(self) -> None:
        try:
            panel = self.query_one(InsightsPanel)
            panel.refresh_data(
                self.insights_bundle,
                is_loading=self._insights_computing,
                progress_stage=self._progress_stage if self._insights_computing else "",
            )
        except Exception:
            pass

    @on(Tabs.TabActivated, "#view-tabs")
    def on_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id and event.tab.id.startswith("tab-"):
            # Guard against stale tab events during early mount.
            try:
                tabs = self.query_one("#view-tabs", Tabs)
            except Exception:
                return
            if tabs.active != event.tab.id:
                return
            new_index = int(event.tab.id.rsplit("-", 1)[1])
            if new_index == self.active_view_index:
                return
            self.active_view_index = new_index
            self._refresh_view_by_index(self.active_view_index)
            self.update_tabs()
            self.update_view_visibility()
            self.update_status_bar()
            self.focus_active_view()
            self._schedule_resize()

    def action_next_view(self) -> None:
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_bar()
        self.focus_active_view()
        self._schedule_resize()

    def action_prev_view(self) -> None:
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_bar()
        self.focus_active_view()
        self._schedule_resize()

    def action_refresh_data(self) -> None:
        load_runtime_settings()
        self.load_data()
        self.show_status("Reading local CSV cache...")

    def action_show_help(self) -> None:
        self.show_status(
            "Ctrl+Left/Right switch views  n negative  p positive  "
            "u sync  U full sync  m manage  r reload  q quit",
            timeout=8.0,
        )

    def _set_sync_inactive(self) -> None:
        self._sync_in_progress = False
        for kind in self._reload_anim:
            self._reload_anim[kind] = False
        self._ensure_reload_spin()
        self.update_status_bar()

    def _set_sync_active(self) -> None:
        """Mark sync in progress and spin all reload indicators."""
        self._sync_in_progress = True
        self._pulse_all_reloads()

    # ── Reload spinner animation ────────────────────────────────────

    def _start_reload_spin(self) -> None:
        if self._spin_timer is not None:
            return
        self._spin_frame = 0
        self._spin_timer = self.set_interval(0.15, self._advance_reload_spin)

    def _stop_reload_spin(self) -> None:
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    def _advance_reload_spin(self) -> None:
        frames = ICON["spinner_frames"]
        self._spin_frame = (getattr(self, "_spin_frame", 0) + 1) % len(frames)
        self.update_status_bar()

    # ── Tab fade transition ─────────────────────────────────────────

    def update_view_visibility(self) -> None:
        view_ids = [
            "#overview-view",
            "#command-view",
            "#insights-view",
        ]
        for index, view_id in enumerate(view_ids):
            widget = self.query_one(view_id, Container)
            is_active = (index == self.active_view_index)
            widget.set_class(is_active, "-active")

    def action_sync_current_week(self) -> None:
        if self._sync_in_progress:
            self.show_status("Wait for the current sync to finish.", severity="warning")
            return
        logger.debug("[SYNC] action_sync_current_week: user pressed 'u'")
        def after_confirm(confirmed: bool) -> None:
            if confirmed:
                self.show_status("Fetching this week's entries from Toggl...")
                self._do_sync_current_week()

        self.push_screen(
            ConfirmScreen("Sync current week", "Run a current-week sync now?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_current_week(self) -> None:
        logger.debug("[SYNC] _do_sync_current_week: starting")
        self.call_from_thread(self._set_sync_active)
        try:
            result = sync_current_week_light(prompt_on_warning=False)
            logger.debug("[SYNC] sync_current_week_light returned: %s", result)
            ok = result["success"]
            message = result.get("message", "")
            logger.debug("[SYNC] calling _on_sync_done: ok=%s, message=%s", ok, message)
            self.call_from_thread(self._on_sync_done, ok, message, "Synced current week")
        except (TogglRateLimitError, TogglAPIError) as e:
            logger.exception("[SYNC] Toggl API error during sync")
            self.call_from_thread(
                self.show_status, str(e), severity="error"
            )
            self.call_from_thread(self._set_sync_inactive)
        except Exception as e:
            logger.exception("[SYNC] Unexpected error in sync worker")
            self.call_from_thread(
                self.show_status,
                f"Sync error: {e}",
                severity="error",
            )
            self.call_from_thread(self._set_sync_inactive)

    def action_sync_full(self) -> None:
        if self._sync_in_progress:
            self.show_status("Wait for the current sync to finish.", severity="warning")
            return
        def after_confirm(confirmed: bool) -> None:
            if confirmed:
                self.show_status("Refreshing projects and syncing the last 4 weeks...")
                self._do_sync_full()

        self.push_screen(
            ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_full(self) -> None:
        self.call_from_thread(self._set_sync_active)
        try:
            result = sync_api_to_csv(4, prompt_on_warning=False)
            ok = result["success"]
            message = result.get("message", "")
            self.call_from_thread(self._on_sync_done, ok, message, "Synced last 4 weeks")
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(
                self.show_status, str(e), severity="error"
            )
            self.call_from_thread(self._set_sync_inactive)
        except Exception as e:
            self.call_from_thread(
                self.show_status,
                f"Sync error: {e}",
                severity="error",
            )
            self.call_from_thread(self._set_sync_inactive)

    def _on_sync_done(self, ok: bool, message: str, success_msg: str) -> None:
        logger.debug("[SYNC] _on_sync_done: ok=%s, message=%s", ok, message)
        load_runtime_settings()
        self._pulse_reload("local")
        reset_cache()
        cache = get_cache()
        self._metrics = self._build_metrics(cache)
        self.data_cache = cache
        if cache:
            self._insights_service = self._build_insights_service(cache, self._metrics)
            self._compute_insights_in_background()
        if ok:
            self._mark_api_reload()
            self._mark_local_reload()
            self.show_status(success_msg)
        else:
            self.show_status(
                message or "Sync was skipped or returned no changes.",
                severity="warning",
            )
        self._stop_pulse("local")
        self._set_sync_inactive()

    def action_add_negative(self) -> None:
        def after_input(value: dict | None) -> None:
            if value:
                ok, message = log_activity_direct(value["name"], "negative", value["date"])
                self.load_data()
                if ok:
                    self.show_status(message)
                else:
                    self.show_status(message, severity="error")

        self.push_screen(NegativeInputScreen(), after_input)

    def action_add_positive(self) -> None:
        def after_input(value: dict | None) -> None:
            if value:
                ok, message = log_activity_direct(value["name"], "positive", value["date"])
                self.load_data()  # reload cache → watch_data_cache refreshes views
                if ok:
                    self.show_status(message)
                else:
                    self.show_status(message, severity="error")

        self.push_screen(PositiveInputScreen(), after_input)

    def action_manage_logs(self) -> None:
        """Open the log management modal."""
        def after_manage(dismissed: bool | None) -> None:
            self.load_data()  # Reload cache in case entries were changed

        self.push_screen(ManageScreen(), after_manage)

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

    @on(ManageRequested)
    def on_manage_requested(self) -> None:
        self.action_manage_logs()

    def on_resize(self, event: Resize) -> None:
        new_size = event.size
        if new_size.width == 0 or new_size.height == 0:
            return
        self._schedule_resize()

    def _resize_tables(self) -> None:
        """Resize tables. SyncPanel handles its own sizing."""
