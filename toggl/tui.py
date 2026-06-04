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
from textual._work_decorator import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp, Resize
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Static, Tab, Tabs

from toggl.widgets.icons import ICON
from toggl.widgets.loading import LoadingWidget, ProgressIndicator

from toggl.api import (
    TogglAPIError,
    TogglRateLimitError,
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
# ──────────────────────────────────────────────
# SPLASH SCREEN
# ──────────────────────────────────────────────


class SplashScreen(ModalScreen[None]):
    """Startup splash screen shown during initial data loading."""

    DEFAULT_CSS = """
    SplashScreen {
        background: #0b1016;
        align: center middle;
    }
    SplashScreen > Container {
        width: auto;
        height: auto;
        border: round #3d4f63;
        padding: 2 4;
        background: #0b1016;
        align: center middle;
    }
    #splash-logo {
        color: #63f3ff;
        text-style: bold;
        text-align: center;
        width: auto;
    }
    #splash-subtitle {
        color: #8d98a7;
        text-align: center;
        width: auto;
        margin-top: 1;
    }
    #splash-progress-bar {
        width: 30;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        from textual.containers import Container as Ctr
        with Ctr():
            yield Static(
                "\n".join([
                    "  \u2554" + "\u2550" * 28 + "\u2557",
                    "  \u2551     " + "\u2502" * 3 + " \u2502" * 3 + "   \u2551",
                    "  \u2551        \u2502\u2502      \u2551",
                    "  \u2551      \u2502\u2502\u2502\u2502\u2502\u2502    \u2551",
                    "  \u2551     \u2502\u2502  \u2502\u2502     \u2551",
                    "  \u2551    \u2502\u2502    \u2502\u2502    \u2551",
                    "  \u2551  " + "\u2502" * 14 + "  \u2551",
                    "  \u255a" + "\u2550" * 28 + "\u255d",
                    "",
                    "       Life Points TUI",
                    "          v1.3.1",
                ]),
                id="splash-logo",
            )
            yield Static("Loading data...", id="splash-subtitle")
            yield ProgressIndicator(width=30, id="splash-progress-bar")

    def set_progress(self, ratio: float) -> None:
        try:
            self.query_one("#splash-progress-bar", ProgressIndicator).set_progress(ratio)
        except Exception:
            pass

    def dismiss_splash(self) -> None:
        self.dismiss(None)


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

    def __init__(self) -> None:
        super().__init__()
        self._initialized = False
        self.active_view_index = 1  # Command tab is the default landing view
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self._table_resize_timer = None
        self._active_week = get_current_week()
        self._sync_in_progress = False
        self._metrics: MetricsService | None = None
        self._insights_service: InsightsBundleService | None = None
        self._insights_generation_id = 0

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
                    yield InsightsPanel(id="insights-view", classes="view")
                with Vertical(id="spark-rail"):
                    pass
        yield ScrollableFooter(show_command_palette=False)

    def on_mount(self) -> None:
        load_runtime_settings()
        # Set initial tab silently (prevent auto-activation of tab-0)
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"
        # Refresh footer BEFORE pushing splash screen so query_one still
        # finds widgets on the main screen.
        self.query_one(ScrollableFooter).refresh_bindings()
        # Show splash screen while data loads (skip in tests / headless mode)
        import sys
        if "pytest" not in sys.modules and not self.is_headless:
            self._splash = SplashScreen()
            self.push_screen(self._splash)
        # Defer data loading to ensure child widget on_mount() has run
        # so their DataTables have columns set up before refresh.
        self.call_later(self.load_data)

        # Check for auto-sync immediately after mounting and then every 60 seconds
        # (Skip in testing environments to prevent visual test notifications)
        if "pytest" not in sys.modules:
            self.call_later(self.check_auto_sync)
            self.set_interval(60, self.check_auto_sync)

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
        if cache is not None and not self._is_splash_active:
            self.refresh_all_views()

    def watch_insights_bundle(self, bundle: InsightsBundle | None) -> None:
        if bundle is not None and not self._is_splash_active:
            try:
                self.refresh_overview_view()
                self.refresh_command_view()
                self.refresh_insights_view()
            except Exception:
                pass

    @property
    def _is_splash_active(self) -> bool:
        """True while the splash screen is still visible."""
        return hasattr(self, '_splash') and self._splash is not None

    def watch__progress_stage(self, stage: str) -> None:
        """Refresh Insights tab whenever compute progress stage changes."""
        try:
            self.refresh_insights_view()
        except Exception:
            pass

    @work(thread=False, exclusive=True)
    async def load_data(self) -> None:
        """Load cache data asynchronously (I/O runs in thread pool)."""
        import asyncio

        # Animate splash progress
        if hasattr(self, '_splash') and self._splash is not None:
            self._splash.set_progress(0.2)

        cache = await asyncio.to_thread(DataCache.load)

        if hasattr(self, '_splash') and self._splash is not None:
            self._splash.set_progress(0.5)

        self._metrics = self._build_metrics(cache)
        self.data_cache = cache
        self._insights_service = self._build_insights_service(cache, self._metrics)
        cached = self._insights_service.try_load_cache()
        if cached:
            self.insights_bundle = cached

        if hasattr(self, '_splash') and self._splash is not None:
            self._splash.set_progress(0.75)

        self._compute_insights_in_background()

        # Allow splash to show for at least 0.5s then dismiss
        if hasattr(self, '_splash') and self._splash is not None:
            self._splash.set_progress(1.0)
            self.set_timer(0.3, self._dismiss_splash)

    def _dismiss_splash(self) -> None:
        """Dismiss the splash screen if still visible."""
        try:
            if hasattr(self, '_splash') and self._splash is not None:
                self._splash.dismiss_splash()
                self._splash = None
                # Data loaded while splash was up — refresh now
                self.refresh_all_views()
        except Exception:
            pass

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
        self._sync_in_progress = True
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
        self._sync_in_progress = False
        load_runtime_settings()
        reset_cache()
        cache = get_cache()
        self._metrics = self._build_metrics(cache)
        self.data_cache = cache
        if cache:
            self._insights_service = self._build_insights_service(cache, self._metrics)
            self._compute_insights_in_background()
        if ok:
            self.notify("Auto-refreshed stale data")
        else:
            self.notify(message or "Auto-refresh failed", severity="warning")

    def refresh_all_views(self) -> None:
        if self.data_cache is None:
            logger.debug("[SYNC] refresh_all_views: deferred — data not loaded yet")
            return
        logger.debug("[SYNC] refresh_all_views: start")
        self.update_tabs()
        self.update_status_line()
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
        self._run_insight_compute(gen_id)

    @work(thread=True)
    def _run_insight_compute(self, gen_id: int) -> None:
        try:
            svc = self._insights_service
            if svc is None:
                return
            bundle = svc.compute(
                on_progress=lambda stage: self.call_from_thread(
                    self._set_progress_stage, stage
                )
            )
            self.call_from_thread(self._on_insights_computed, bundle, gen_id)
        except Exception:
            logger.exception("Insights bundle computation failed")

    def _set_progress_stage(self, stage: str) -> None:
        self._progress_stage = stage

    def _on_insights_computed(self, bundle: InsightsBundle, gen_id: int) -> None:
        if gen_id < self._insights_generation_id:
            return
        self._insights_generation_id = gen_id
        if self._insights_service:
            self._insights_service.save_cache(bundle)
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

    def update_status_line(self) -> None:
        current_week = get_current_week()
        synced = get_last_updated_str()

        sync_widget = self.query_one("#sync-status", Static)

        # Determine sync age for color coding
        try:
            # Parse sync timestamp to determine freshness
            if synced and synced != "never":
                from datetime import datetime
                for fmt in ("%d %b %Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                    try:
                        sync_dt = datetime.strptime(synced, fmt)
                        age_hours = (datetime.now() - sync_dt).total_seconds() / 3600
                        if age_hours < 1:
                            sync_widget.set_class(True, "sync-fresh")
                        elif age_hours < 24:
                            sync_widget.set_class(True, "sync-warn")
                        else:
                            sync_widget.set_class(True, "sync-stale")
                        break
                    except ValueError:
                        continue
            else:
                sync_widget.set_class(True, "sync-stale")
        except Exception:
            pass

        # Use arrow-circle icon for sync status
        sync_icon = ICON["sync"]
        sync_widget.update(f"{sync_icon}\u2002{synced}")

        # If sync is in progress, start spinning animation
        if self._sync_in_progress:
            self._start_sync_spin()
        else:
            self._stop_sync_spin()

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
            bundle = self.insights_bundle
            loading = self._insights_generation_id > 0 and (
                bundle is None or not bundle.playbook.headline
            )
            panel.refresh_data(
                self.data_cache,
                self._active_week,
                self._metrics,
                bundle,
                insights_loading=loading and bundle is None,
                progress_stage=self._progress_stage if loading else "",
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
            bundle = self.insights_bundle
            loading = self._insights_generation_id > 0 and bundle is None
            panel.refresh_data(
                bundle,
                is_loading=loading,
                progress_stage=self._progress_stage if loading else "",
            )
        except Exception:
            pass

    @on(Tabs.TabActivated, "#view-tabs")
    def on_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id and event.tab.id.startswith("tab-"):
            # Guard against stale events: verify this tab is actually active.
            # If the splash screen is up, #view-tabs won't be in the DOM.
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
        self.load_data()  # reload via async worker
        self.notify("Reloading local data...")

    def action_show_help(self) -> None:
        self.notify(
            "Left/right switch views, n add negative, u sync, U full sync, "
            "q quit"
        )

    def _set_sync_inactive(self) -> None:
        self._sync_in_progress = False
        self._stop_sync_spin()
        self.update_status_line()

    # ── Sync spinner animation ──────────────────────────────────────

    def _start_sync_spin(self) -> None:
        """Start the sync symbol spinning animation."""
        if hasattr(self, '_spin_timer') and self._spin_timer is not None:
            return  # Already spinning
        self._spin_frame = 0
        self._spin_timer = self.set_interval(0.15, self._advance_sync_spin)

    def _stop_sync_spin(self) -> None:
        """Stop the sync symbol spinning animation."""
        if hasattr(self, '_spin_timer') and self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    def _advance_sync_spin(self) -> None:
        """Advance the spin frame."""
        frames = ICON["spin_frames"]
        self._spin_frame = (getattr(self, '_spin_frame', 0) + 1) % len(frames)
        try:
            sync_widget = self.query_one("#sync-status", Static)
            synced = get_last_updated_str()
            sync_widget.update(f"{frames[self._spin_frame]}\u2002{synced}")
        except Exception:
            pass

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
            if is_active and not widget.has_class("-active"):
                # Fade in the newly active view
                widget.styles.animate("opacity", value=1.0, duration=0.2)
            widget.set_class(is_active, "-active")

    def action_sync_current_week(self) -> None:
        if self._sync_in_progress:
            self.notify("Sync already in progress...", severity="warning")
            return
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
        self._sync_in_progress = True
        try:
            result = sync_current_week_light(prompt_on_warning=False)
            logger.debug("[SYNC] sync_current_week_light returned: %s", result)
            ok = result["success"]
            message = result.get("message", "")
            logger.debug("[SYNC] calling _on_sync_done: ok=%s, message=%s", ok, message)
            self.call_from_thread(self._on_sync_done, ok, message, "Synced current week")
        except (TogglRateLimitError, TogglAPIError) as e:
            logger.exception("[SYNC] Toggl API error during sync")
            self.call_from_thread(self.notify, str(e), severity="error")
            self.call_from_thread(self._set_sync_inactive)
        except Exception as e:
            logger.exception("[SYNC] Unexpected error in sync worker")
            self.call_from_thread(self.notify, f"Sync error: {e}", severity="error")
            self.call_from_thread(self._set_sync_inactive)

    def action_sync_full(self) -> None:
        if self._sync_in_progress:
            self.notify("Sync already in progress...", severity="warning")
            return
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
        self._sync_in_progress = True
        try:
            result = sync_api_to_csv(4, prompt_on_warning=False)
            ok = result["success"]
            message = result.get("message", "")
            self.call_from_thread(self._on_sync_done, ok, message, "Synced last 4 weeks")
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            self.call_from_thread(self._set_sync_inactive)
        except Exception as e:
            self.call_from_thread(self.notify, f"Sync error: {e}", severity="error")
            self.call_from_thread(self._set_sync_inactive)

    def _on_sync_done(self, ok: bool, message: str, success_msg: str) -> None:
        logger.debug("[SYNC] _on_sync_done: ok=%s, message=%s", ok, message)
        self._sync_in_progress = False
        load_runtime_settings()
        reset_cache()
        cache = get_cache()
        self._metrics = self._build_metrics(cache)
        self.data_cache = cache
        if cache:
            self._insights_service = self._build_insights_service(cache, self._metrics)
            self._compute_insights_in_background()
        if ok:
            self.notify(success_msg)
        else:
            self.notify(message or "Sync skipped", severity="warning")

    def action_add_negative(self) -> None:
        def after_input(value: dict | None) -> None:
            if value:
                ok, message = log_activity_direct(value["name"], "negative", value["date"])
                self.load_data()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(NegativeInputScreen(), after_input)

    def action_add_positive(self) -> None:
        def after_input(value: dict | None) -> None:
            if value:
                ok, message = log_activity_direct(value["name"], "positive", value["date"])
                self.load_data()  # reload cache → watch_data_cache refreshes views
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

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
