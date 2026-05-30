"""TogglTUI — Textual terminal UI for TStat."""

from calendar import month_name
from datetime import date, datetime, timedelta

from rich.text import Text
from textual import on
from textual._work_decorator import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click, MouseScrollDown, MouseScrollUp
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, OptionList, Static, Tab, Tabs
from textual.worker import Worker, get_current_worker

from toggl.api import (
    API_RUN_STATS,
    TogglAPIError,
    TogglRateLimitError,
    _format_reset_window,
    _print_api_usage_summary,
    _reset_api_stats,
    check_quota,
    get_api_token,
)
from toggl.cache import (
    DataCache,
    _load_history,
    get_cache,
    get_current_week,
    get_last_updated_str,
    get_sunday_of_week,
    get_week_dates,
    get_week_str,
    needs_auto_update,
    reset_cache,
    sync_api_to_csv,
    sync_current_week_light,
)
from toggl.calc import (
    calculate,
    format_signed,
    get_negative_catalog_rows,
    get_positive_catalog_rows,
)
from toggl.config import (
    NEGATIVES,
    POINTS,
    POSITIVES,
    get_daily_target,
    load_runtime_settings,
)
from toggl.const import BLAME_W, SPARK_W, TASK_SHORT_NAMES, strip_ansi
from toggl.neg import (
    log_negative_direct,
    log_positive_direct,
)


def get_sync_status_data():
    import csv, os
    from toggl.const import CSV_FILE, DAILY_CSV_FILE

    history = _load_history()
    from toggl.api import API_RUN_STATS, get_projects_cache_age_days

    # Count actual weeks/days from CSV files (not from unwritten history keys)
    synced_weeks = 0
    synced_days = 0
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE) as f:
            synced_weeks = len({row["Week"] for row in csv.DictReader(f)})
    if os.path.exists(DAILY_CSV_FILE):
        with open(DAILY_CSV_FILE) as f:
            synced_days = len({row["Date"] for row in csv.DictReader(f)})

    backfill = {}
    try:
        from toggl.backfill import get_backfill_status
        backfill = get_backfill_status()
    except Exception:
        backfill = {"status": "error"}

    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": synced_weeks,
        "synced_days": synced_days,
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
        "backfill_status": backfill,
    }


def time_left_in_week():
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
# SPARK TABLE CELL RENDERER
# ──────────────────────────────────────────────


def _spark_net_rich(
    net, max_abs, bar_w=4, dim_zero=False, blame_tracked=0, blame_logged=0, blame_w=3
):
    """
    Return Rich markup for a net-points cell in the interactive spark tables.
    Positive → green bar on left of value.  Negative → red value + bar on right.
    When net < 0 and blame data is provided, a blame bar (red tracked + magenta
    logged) is appended after the net bar.
    """
    if net is None or (abs(net) < 0.05 and dim_zero):
        return "[dim]—[/]"
    if abs(net) < 0.05:
        return "[dim]0.0[/]"
    bar_len = max(1, round(abs(net) / max_abs * bar_w)) if max_abs > 0 else 1
    if net > 0:
        bar = "█" * bar_len
        return f"[#37d994]{bar} +{net}[/]"
    else:
        blame_total = blame_tracked + blame_logged
        if blame_total > 0 and blame_w > 0:
            net_bar_len = max(1, bar_len - blame_w)
            red_count = round(blame_tracked / blame_total * blame_w)
            mag_count = blame_w - red_count
            bar = "█" * net_bar_len
            blame = f"[#ff5f5f]{'█' * red_count}[/][#ff5fff]{'█' * mag_count}[/]"
            return f"[#ff5f5f]{net} {bar}[/]{blame}"
        bar = "█" * bar_len
        return f"[#ff5f5f]{net} {bar}[/]"


def fmt_rate(rate):
    if rate is None:
        return "—"
    r = int(rate) if rate == int(rate) else rate
    return f"×{r}"


HEATMAP_ROW_PREFIX = 6  # width of "  Mon " style row labels


def _heatmap_grid_start(year: int) -> date:
    """Monday on or before Jan 1 — column 0 of the yearly week grid."""
    jan1 = date(year, 1, 1)
    return jan1 - timedelta(days=jan1.weekday())


def _heatmap_num_week_columns(year: int) -> int:
    grid_start = _heatmap_grid_start(year)
    end = date(year, 12, 31)
    return ((end - grid_start).days // 7) + 1


def _heatmap_cell_char(net, abs_max: float) -> str:
    if net is None:
        return "\u00b7"
    if abs_max <= 0:
        return "\u00b7"
    intensity = abs(net) / abs_max
    level = min(4, int(intensity * 5))
    shades = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585"]
    if net > 0:
        return f"[#37d994]{shades[level]}[/]"
    return f"[#ff5f5f]{shades[level]}[/]"


def build_yearly_heatmap_lines(
    year: int, day_net_map: dict[str, float], abs_max: float
) -> tuple[list[str], date, int]:
    """
    GitHub-style calendar: columns = weeks, rows = Mon..Sun.
    Header month labels align with week columns (2 chars per column).
    """
    grid_start = _heatmap_grid_start(year)
    num_weeks = _heatmap_num_week_columns(year)

    header = " " * HEATMAP_ROW_PREFIX
    for col in range(num_weeks):
        week_start = grid_start + timedelta(weeks=col)
        label = ""
        for m in range(1, 13):
            d1 = date(year, m, 1)
            if week_start <= d1 < week_start + timedelta(days=7):
                label = month_name[m][:3]
                break
        header += f"{label[:2]:<2}" if label else "\u00b7 "

    lines = [header]
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today = date.today()
    for dow in range(7):
        row = f"{day_labels[dow]:>5} "
        for col in range(num_weeks):
            cell = grid_start + timedelta(weeks=col, days=dow)
            if cell.year != year or cell > today:
                row += "\u00b7 "
            else:
                net = day_net_map.get(cell.strftime("%Y-%m-%d"))
                row += _heatmap_cell_char(net, abs_max) + " "
        lines.append(row)

    return lines, grid_start, num_weeks


def fmt_pts(pts):
    if pts is None:
        return "—"
    if pts == 0:
        return "0.0"
    return f"+{pts}" if pts > 0 else str(pts)


def format_signed_rich(value):
    if abs(value) < 0.05:
        value = 0.0
    if value > 0:
        return f"[#37d994]+{value:.1f}[/]"
    elif value < 0:
        return f"[#ff5f5f]{value:.1f}[/]"
    return "0.0"


def fmt_pts_rich(pts):
    if pts is None:
        return "—"
    if pts == 0:
        return "0.0"
    if pts > 0:
        return f"[#37d994]+{pts:.1f}[/]"
    return f"[#ff5f5f]{pts:.1f}[/]"


# ──────────────────────────────────────────────
# MODAL SCREENS
# ──────────────────────────────────────────────


class BaseDialog(ModalScreen):
    """Base modal dialog with consistent centered floating appearance.

    Provides a standard #dialog → #dialog-box structure with:
    - Centered layout (100% screen overlay → auto-sized box)
    - Consistent round #3d4f63 border, $accent on focus
    - Shared escape/cancel binding
    - border_title from the title argument

    Subclasses override ``body()`` to yield dialog content inside #dialog-box.
    Default action_cancel dismisses with None.
    """

    DEFAULT_CSS = """
    $accent: #63f3ff;

    BaseDialog {
        background: $background 60%;
    }

    #dialog {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #dialog-box {
        width: auto;
        height: auto;
        min-width: 60;
        max-width: 80;
        border: round #3d4f63;
        padding: 1 2;
        background: #0b1016;
    }

    #dialog-box:focus,
    #dialog-box:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    .dialog-body {
        margin-bottom: 1;
    }

    .dialog-help {
        color: #8d98a7;
        margin-top: 1;
    }

    #dialog-buttons {
        margin-top: 1;
        height: auto;
    }

    #btn-confirm:hover, #btn-cancel:hover {
        color: #d7dde8;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str):
        super().__init__()
        self._dialog_title = title

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield from self.body()

    def body(self) -> ComposeResult:
        """Override to yield dialog content inside #dialog-box."""
        return

    def on_mount(self):
        self.query_one("#dialog-box").border_title = (
            f"[b][#63f3ff]{self._dialog_title}[/][/]"
        )

    def action_cancel(self):
        self.dismiss(None)


class ConfirmScreen(BaseDialog):
    """Confirmation dialog (Yes / No)."""

    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("Y", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("N", "cancel", "Cancel"),
    ]

    def __init__(self, title, body):
        self._body_text = body
        super().__init__(title)

    def body(self) -> ComposeResult:
        yield Static(self._body_text, classes="dialog-body")
        with Horizontal(id="dialog-buttons"):
            yield Static("[Y/Enter] confirm", id="btn-confirm", classes="dialog-help")
            yield Static("  " "[N/Esc] cancel", id="btn-cancel", classes="dialog-help")

    @on(Click, "#btn-confirm")
    def on_confirm_click(self):
        self.dismiss(True)

    @on(Click, "#btn-cancel")
    def on_cancel_click(self):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class NegativeInputScreen(BaseDialog):
    """Pick a negative action to log."""

    def __init__(self):
        super().__init__("Log Negative")

    def body(self) -> ComposeResult:
        yield Static("Select a negative action to log.", classes="dialog-body")
        yield OptionList(id="negative-list")
        yield Static("[Esc] cancel", id="btn-cancel", classes="dialog-help")

    def on_mount(self):
        super().on_mount()
        option_list = self.query_one("#negative-list", OptionList)
        for name in NEGATIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#negative-list")
    def submit_negative(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    @on(Click, "#btn-cancel")
    def on_cancel_click(self):
        self.dismiss(None)


class PositiveInputScreen(BaseDialog):
    """Pick a positive action to log."""

    def __init__(self):
        super().__init__("Log Positive")

    def body(self) -> ComposeResult:
        yield Static("Select a positive action to log.", classes="dialog-body")
        yield OptionList(id="positive-list")
        yield Static("[Esc] cancel", id="btn-cancel", classes="dialog-help")

    def on_mount(self):
        super().on_mount()
        option_list = self.query_one("#positive-list", OptionList)
        for name in POSITIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#positive-list")
    def submit_positive(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    @on(Click, "#btn-cancel")
    def on_cancel_click(self):
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
    CSS = """
    $accent: #63f3ff;

    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #0b1016;
        color: #d7dde8;
    }

    #root {
        height: 1fr;
    }

    #chrome {
        layout: horizontal;
        height: auto;
        padding: 0 1;
    }

    .app-title {
        color: #63f3ff;
        text-style: bold;
        padding: 0 1;
        width: auto;
    }

    #view-tabs {
        width: 1fr;
        margin: 0 1;
    }

    #view-tabs > .-active {
        color: #63f3ff;
        text-style: bold;
    }

    #view-tabs > .-hidden {
        display: none;
    }

    #sync-status {
        color: #8d98a7;
        width: auto;
        padding: 0 1;
    }

    #main {
        height: 1fr;
    }

    #content {
        width: 1fr;
        height: 1fr;
        padding: 0;
    }

    .view {
        display: none;
        height: 1fr;
    }

    .view.-active {
        display: block;
    }

    DataTable {
        height: 1fr;
        border: round #3d4f63;
        background: #0b1016;
        color: #d7dde8;
    }

    DataTable:focus,
    DataTable:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    DataTable:focus > .datatable--cursor,
    DataTable:focus-within > .datatable--cursor {
        background: transparent;
        color: $accent;
        text-style: bold;
    }

    DataTable:focus > .datatable--fixed-cursor,
    DataTable:focus-within > .datatable--fixed-cursor {
        background: transparent;
        color: $accent;
    }

    DataTable > .datatable--cursor {
        background: transparent;
        color: #d7dde8;
    }

    DataTable > .datatable--fixed-cursor {
        background: transparent;
    }

    DataTable > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-rail {
        width: 34;
        min-width: 34;
        max-width: 34;
        border: none;
        padding: 0;
        display: block;
    }

    #spark-weeks-table {
        height: 1fr;
        min-height: 0;
        border: round #3d4f63;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-weeks-table:focus,
    #spark-weeks-table:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    #spark-weeks-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-days-table {
        height: auto;
        border: round #3d4f63;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-days-table:focus,
    #spark-days-table:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    #spark-catchup {
        height: auto;
        border: round #3d4f63;
        padding: 0 1;
        background: #0b1016;
    }

    #spark-catchup:focus,
    #spark-catchup:focus-within {
        border: round #fab387;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    Footer {
        background: #0b1016;
        color: #8d98a7;
    }

    Footer > FooterKey .footer-key--key {
        color: #e2b714;
    }

    Footer > FooterKey .footer-key--description {
        color: #8d98a7;
    }

    OptionList {
        background: #0b1016;
        color: #d7dde8;
        border: none;
        height: auto;
        max-height: 10;
    }

    OptionList > .option-list--option {
        padding: 0 1;
    }

    OptionList > .option-list--option-highlighted {
        background: #27323d;
        color: #63f3ff;
    }

    #heatmap-grid {
        height: 1fr;
        border: round #3d4f63;
        padding: 0 1;
        background: #0b1016;
    }

    #heatmap-grid:focus,
    #heatmap-grid:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    .heatmap-legend {
        height: auto;
        color: #8d98a7;
        padding: 0 1;
    }

    Toast {
        background: #0b1016;
        color: #d7dde8;
        border: round #3d4f63;
        padding: 0 1;
        margin: 1 1 0 0;
        height: auto;
    }
    Toast.-information {
        border: round #37d994;
    }
    Toast.-warning {
        border: round #e2b714;
    }
    Toast.-error {
        border: round #ff5f5f;
    }
    """

    BINDINGS = [
        Binding("ctrl+left", "prev_view", "Prev"),
        Binding("ctrl+right", "next_view", "Next"),
        Binding("q", "quit", "Quit", show=False),
        Binding("r", "refresh_data", "Refresh"),
        Binding("u", "sync_current_week", "Sync"),
        Binding("U", "sync_full", "Full Sync"),
        Binding("b", "backfill", "Backfill"),
        Binding("n", "add_negative", "Neg"),
        Binding("p", "add_positive", "Pos"),
    ]

    VIEWS = [
        "Overview",
        "Day",
        "Week",
        "Month",
        "Heatmap",
        "Negatives",
        "Positives",
        "Recovery",
        "Sync/Quota",
    ]

    def __init__(self):
        super().__init__()
        self._initialized = False
        self.active_view_index = 1  # Day view is the default landing view
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self._table_resize_timer = None
        self._data_cache: DataCache | None = None
        self._active_week = get_current_week()
        self._heatmap_grid_start: date | None = None
        self._heatmap_num_weeks: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Container(id="chrome"):
                yield Label("TStat v1.2.0", classes="app-title")
                tabs = Tabs(
                    *[Tab(view, id=f"tab-{index}") for index, view in enumerate(self.VIEWS)],
                    id="view-tabs",
                )
                tabs.can_focus = False
                yield tabs
                yield Static(id="sync-status", classes="sync-status")
            with Horizontal(id="main"):
                with Container(id="content"):
                    with Container(id="overview-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="overview-table"
                        )
                    with Container(id="day-view", classes="view -active"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="day-table"
                        )
                    with Container(id="week-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="week-table"
                        )
                        yield DataTable(
                            zebra_stripes=False,
                            cursor_type="row",
                            id="week-category-table",
                        )
                    with Container(id="month-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="month-table"
                        )
                    with Container(id="heatmap-view", classes="view"):
                        yield Static(id="heatmap-grid")
                        yield Label(id="heatmap-legend", classes="heatmap-legend")
                    with Container(id="negatives-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False,
                            cursor_type="row",
                            id="negatives-catalog-table",
                        )
                        yield DataTable(
                            zebra_stripes=False,
                            cursor_type="row",
                            id="negatives-log-table",
                        )
                    with Container(id="positives-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False,
                            cursor_type="row",
                            id="positives-catalog-table",
                        )
                        yield DataTable(
                            zebra_stripes=False,
                            cursor_type="row",
                            id="positives-log-table",
                        )
                    with Container(id="recovery-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="recovery-table"
                        )
                    with Container(id="sync-view", classes="view"):
                        yield DataTable(
                            zebra_stripes=False, cursor_type="row", id="sync-table"
                        )
                with Vertical(id="spark-rail"):
                    yield DataTable(
                        show_header=False,
                        cursor_type="row",
                        id="spark-weeks-table",
                        zebra_stripes=False,
                    )
                    yield DataTable(
                        show_header=False,
                        cursor_type="row",
                        id="spark-days-table",
                        zebra_stripes=False,
                    )
                    yield Static(id="spark-catchup")
        yield ScrollableFooter(show_command_palette=False)

    def on_mount(self):
        self._setup_tables()
        load_runtime_settings()
        # Set initial tab silently (prevent auto-activation of tab-0)
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"
        if needs_auto_update():
            self._do_auto_refresh()
        self.refresh_all_views()
        self.query_one(ScrollableFooter).refresh_bindings()

    @work(thread=True)
    def _do_auto_refresh(self):
        try:
            result = sync_current_week_light(auto_refresh=True, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError):
            result = {"success": False, "message": "API error during auto-refresh"}
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_auto_refresh_done, ok, message)

    def _on_auto_refresh_done(self, ok, message):
        load_runtime_settings()
        self.refresh_all_views()
        if ok:
            self.notify("Auto-refreshed stale data")
        else:
            self.notify(message or "Auto-refresh failed", severity="warning")

    def _setup_tables(self):
        week_table = self.query_one("#week-table", DataTable)
        week_table.add_columns("Day", "Date", "Hours", "Earned", "Pos", "Negs", "Net")

        week_category_table = self.query_one("#week-category-table", DataTable)
        week_category_table.add_columns("Category", "Hours", "Rate", "Points")

        overview_table = self.query_one("#overview-table", DataTable)
        overview_table.add_columns("Category", "Hours", "Rate", "Points")

        day_table = self.query_one("#day-table", DataTable)
        day_table.add_columns("Category", "Hours", "Rate", "Points")

        negatives_catalog = self.query_one("#negatives-catalog-table", DataTable)
        negatives_catalog.add_columns("Negative", "Points")

        negatives_log = self.query_one("#negatives-log-table", DataTable)
        negatives_log.add_columns("Date", "Negative", "Points")

        positives_catalog = self.query_one("#positives-catalog-table", DataTable)
        positives_catalog.add_columns("Positive", "Points")

        positives_log = self.query_one("#positives-log-table", DataTable)
        positives_log.add_columns("Date", "Positive", "Points")

        recovery_table = self.query_one("#recovery-table", DataTable)
        recovery_table.add_columns("Category", "Rate", "Hours Needed")

        sync_table = self.query_one("#sync-table", DataTable)
        sync_table.add_columns("Metric", "Value")

        month_table = self.query_one("#month-table", DataTable)
        month_table.add_columns("Month", "Hours", "Net")

        spark_weeks = self.query_one("#spark-weeks-table", DataTable)
        spark_weeks.add_columns("Label", "Net")

        spark_days = self.query_one("#spark-days-table", DataTable)
        spark_days.add_columns("Day", "Net")

        for table_id in [
            "#overview-table", "#day-table", "#week-table", "#month-table",
            "#negatives-catalog-table", "#negatives-log-table",
            "#positives-catalog-table", "#positives-log-table",
            "#recovery-table", "#sync-table",
        ]:
            try:
                t = self.query_one(table_id, DataTable)
                t.styles.min_height = 1
                t.show_cursor = True
            except Exception:
                pass

    def refresh_all_views(self):
        self._data_cache = DataCache.load()
        self.update_tabs()
        self.update_status_line()
        self.refresh_spark_tables()
        for idx in self._VIEW_REFRESH_MAP:
            self._refresh_view_by_index(idx)
        self.update_view_visibility()
        self._schedule_resize()

    _VIEW_REFRESH_MAP = {
        0: "refresh_overview_view",
        1: "refresh_day_view",
        2: "refresh_week_view",
        3: "refresh_month_view",
        4: "refresh_heatmap_view",
        5: "refresh_negatives_view",
        6: "refresh_positives_view",
        7: "refresh_recovery_view",
        8: "refresh_sync_view",
    }

    def _refresh_view_by_index(self, index):
        method_name = self._VIEW_REFRESH_MAP.get(index)
        if method_name:
            getattr(self, method_name)()

    def _schedule_resize(self):
        if self._table_resize_timer is not None:
            self._table_resize_timer.stop()
        self._table_resize_timer = self.set_timer(0.1, self._resize_tables)

    def update_tabs(self):
        tabs = self.query_one("#view-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            tabs.active = f"tab-{self.active_view_index}"

    def update_status_line(self):
        current_week = get_current_week()
        synced = get_last_updated_str()

        sync_widget = self.query_one("#sync-status", Static)
        sync_widget.update(f"\u27f3\u2002{synced}")

    def update_view_visibility(self):
        view_ids = [
            "#overview-view",
            "#day-view",
            "#week-view",
            "#month-view",
            "#heatmap-view",
            "#negatives-view",
            "#positives-view",
            "#recovery-view",
            "#sync-view",
        ]
        for index, view_id in enumerate(view_ids):
            widget = self.query_one(view_id, Container)
            widget.set_class(index == self.active_view_index, "-active")

    def focus_active_view(self):
        focus_targets = {
            0: "#overview-table",
            1: "#day-table",
            2: "#week-table",
            3: "#month-table",
            4: "#heatmap-grid",
            5: "#negatives-catalog-table",
            6: "#positives-catalog-table",
            7: "#recovery-table",
            8: "#sync-table",
        }
        selector = focus_targets.get(self.active_view_index)
        if selector:
            self.query_one(selector).focus()
        self.query_one(ScrollableFooter).refresh_bindings()

    # ── Spark tables ──

    def refresh_spark_tables(self):
        self._refresh_spark_weeks()
        self._refresh_spark_days()
        self._refresh_spark_catchup()

    def _refresh_spark_weeks(self):
        cache = self._data_cache
        table = self.query_one("#spark-weeks-table", DataTable)
        table.clear(columns=False)

        # Show ALL weeks that have data, from earliest to latest
        all_weeks = sorted(cache.weekly_data.keys())
        if not all_weeks:
            table.border_title = "[b][#63f3ff]Past Weeks[/][/]"
            return

        weeks_data = []

        for wk in all_weeks:
            wk_num = wk.split("W")[1]
            wk_label = f"W{int(wk_num)}"

            wk_projs = cache.get_week_projects(wk)
            if wk_projs:
                wk_results = calculate(wk_projs)
                wk_earned = sum(
                    r[3] for r in wk_results if r[3] is not None and r[3] > 0
                )
                wk_tracked_neg = sum(
                    abs(r[3]) for r in wk_results if r[3] is not None and r[3] < 0
                )
            else:
                wk_earned = 0.0
                wk_tracked_neg = 0.0

            wk_tracked, wk_logged = cache.get_week_neg_breakdown(wk)
            wk_logged_pos = cache.get_week_pos_breakdown(wk)
            wk_net = round(wk_earned - wk_tracked_neg - wk_logged + wk_logged_pos, 1)
            weeks_data.append((wk_label, wk, wk_net, wk_tracked, wk_logged))

        max_abs = max((abs(w[2]) for w in weeks_data), default=1) or 1

        for label, wk, net, tracked, logged in weeks_data:
            net_cell = _spark_net_rich(
                net, max_abs, blame_tracked=tracked, blame_logged=logged
            )
            table.add_row(label, net_cell, key=wk)

        n_weeks = len(weeks_data)
        table.border_title = f"[b][#63f3ff]Past Weeks ({n_weeks})[/][/]"

    def _refresh_spark_days(self):
        cache = self._data_cache
        table = self.query_one("#spark-days-table", DataTable)

        with table.prevent(DataTable.RowHighlighted):
            table.clear(columns=False)

            week_str = get_current_week()
            start_d, _ = get_week_dates(week_str)

            day_entries = []
            for i in range(7):
                d = start_d + timedelta(days=i)
                d_str = d.strftime("%Y-%m-%d")
                projs = cache.daily_data.get(d_str, {})
                neg_entries = cache.negatives_raw.get(d_str, [])
                pos_entries = cache.positives_raw.get(d_str, [])
                neg_cost = sum(e["points"] for e in neg_entries)
                pos_bonus = sum(e["points"] for e in pos_entries)
                results = calculate(projs)
                earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
                tracked_neg = sum(
                    abs(r[3]) for r in results if r[3] is not None and r[3] < 0
                )
                net = round(earned - tracked_neg - neg_cost + pos_bonus, 1)
                has_data = bool(projs or neg_entries or pos_entries)
                logged_neg = round(neg_cost, 1)
                day_entries.append(
                    (
                        d,
                        d_str,
                        net,
                        has_data,
                        tracked_neg,
                        logged_neg,
                        earned,
                        pos_bonus,
                    )
                )

            max_abs = (
                max(
                    (
                        abs(net)
                        for _, _, net, has, _, _, _, _ in day_entries
                        if has and abs(net) >= 0.05
                    ),
                    default=1,
                )
                or 1
            )

            cursor_row = None
            for i, (
                d,
                d_str,
                net,
                has_data,
                tracked_neg,
                logged_neg,
                earned,
                pos_bonus,
            ) in enumerate(day_entries):
                day_name = d.strftime("%a")
                is_today = d == date.today()

                if is_today:
                    label_cell = f"[bold #e2b714]{day_name} ◀[/]"
                elif not has_data:
                    label_cell = f"[dim]{day_name}[/]"
                else:
                    label_cell = day_name

                net_cell = _spark_net_rich(
                    net if has_data else None,
                    max_abs,
                    dim_zero=(not has_data),
                    blame_tracked=tracked_neg if has_data and net < 0 else 0,
                    blame_logged=logged_neg if has_data and net < 0 else 0,
                )

                table.add_row(label_cell, net_cell, key=d_str)

                if d_str == self.selected_day:
                    cursor_row = table.row_count - 1

            if cursor_row is not None:
                table.move_cursor(row=cursor_row)

        tw_num = week_str.split("W")[1]
        tw_label = f"W{int(tw_num)}"

        tw_total_neg = round(sum(dd[4] + dd[5] for dd in day_entries if dd[3]), 1)
        tw_total_pos = round(sum(dd[6] + dd[7] for dd in day_entries if dd[3]), 1)
        neg_val = (
            int(tw_total_neg) if tw_total_neg == int(tw_total_neg) else tw_total_neg
        )
        pos_val = (
            int(tw_total_pos) if tw_total_pos == int(tw_total_pos) else tw_total_pos
        )

        neg_s = f"[#ff5f5f]-{neg_val}[/]" if tw_total_neg > 0 else "[dim]-0[/]"
        pos_s = f"[#37d994]+{pos_val}[/]" if tw_total_pos > 0 else "[dim]+0[/]"

        table.border_title = f"[b][#63f3ff]This Week ({tw_label})[/][/]"
        table.border_subtitle = f"{pos_s} {neg_s}"

    def _refresh_spark_catchup(self):
        cache = self._data_cache
        all_time_data = cache.get_all_time_projects()
        if all_time_data:
            all_results = calculate(all_time_data)
            all_earned = sum(r[3] for r in all_results if r[3] is not None)
        else:
            all_earned = 0.0
        all_negatives = cache.get_negatives_for_context("ALL_TIME", "ALL")
        all_positives = cache.get_positives_for_context("ALL_TIME", "ALL")
        all_neg_pts = sum(r[3] for r in all_negatives)
        all_pos_pts = sum(r[3] for r in all_positives)
        lifetime_pts = round(all_earned + all_neg_pts + all_pos_pts, 1)

        catchup = self.query_one("#spark-catchup", Static)

        if lifetime_pts >= 0:
            pts_val = (
                int(lifetime_pts) if lifetime_pts == int(lifetime_pts) else lifetime_pts
            )
            text = Text()
            text.append(f"+{pts_val} pts", style="bold #37d994")
            catchup.update(text)
            catchup.border_title = "[b][#37d994]On Track[/][/]"
        else:
            deficit = abs(lifetime_pts)
            tl_raw = time_left_in_week()
            deficit_val = int(deficit) if deficit == int(deficit) else deficit

            group_colors_rich = ["#63f3ff", "#ff5fff", "#37d994", "#5fafff", "#e2b714"]
            rate_groups: dict[float, list[str]] = {}
            for task_name, rate in POINTS.items():
                if rate >= 1:
                    rate_groups.setdefault(rate, []).append(task_name)
            rates_sorted = sorted(rate_groups.keys(), reverse=True)

            text = Text()
            for i, rate in enumerate(rates_sorted):
                tasks = rate_groups[rate]
                hours_needed = deficit / rate
                h = int(hours_needed)
                m = int((hours_needed - h) * 60)
                h_str = f"{h}h {m:02d}m"
                rate_str = f"×{int(rate) if rate == int(rate) else rate}"
                short: list[str] = [TASK_SHORT_NAMES.get(t) or t for t in tasks]
                task_str = " ".join(short)
                color = group_colors_rich[i % len(group_colors_rich)]

                if i > 0:
                    text.append("\n")
                text.append(f" {rate_str:<3}", style="dim")
                text.append(f"{h_str}", style="#e2b714")
                text.append(f" {task_str}", style=color)

            catchup.update(text)
            catchup.border_title = (
                f"[b][#ff5f5f]Catch Up :[/][/] [#ff5f5f]{deficit_val} pts[/]"
            )
            catchup.border_subtitle = f"[#63f3ff]in {tl_raw}[/]"

    # ── View refresh methods ──

    def refresh_week_view(self):
        cache = self._data_cache
        week = self._active_week
        dashboard = cache.get_week_dashboard_rows(week)
        report = cache.get_report_sections(week, "WEEK")
        table = self.query_one("#week-table", DataTable)

        with table.prevent(DataTable.RowHighlighted):
            table.clear(columns=False)
            week_rows = []
            for row in dashboard["rows"]:
                neg_text = (
                    "—"
                    if row["negative_total"] == 0
                    else f"[#ff5f5f]-{row['negative_total']:.1f}[/]"
                )
                pos_text = (
                    "—"
                    if row["positive_total"] == 0
                    else f"[#37d994]+{row['positive_total']:.1f}[/]"
                )
                hour_text = "—" if row["hours"] == 0 else f"{row['hours']:.1f}h"
                earned_text = (
                    "—"
                    if row["hours"] == 0 and row["earned"] == 0
                    else format_signed_rich(row["earned"])
                )
                week_rows.append(
                    (
                        row["day"],
                        row["date_short"],
                        hour_text,
                        earned_text,
                        pos_text,
                        neg_text,
                        format_signed_rich(row["net"]),
                        row["date"],
                    )
                )
            for cells in week_rows:
                key = cells[7]
                table.add_row(*cells[:7], key=key)

            if dashboard["rows"]:
                today_str = date.today().strftime("%Y-%m-%d")
                row_dates = [r["date"] for r in dashboard["rows"]]
                if self.selected_day in row_dates:
                    default_date = self.selected_day
                elif today_str in row_dates:
                    default_date = today_str
                else:
                    default_date = dashboard["rows"][0]["date"]
                self.selected_day = default_date
                row_index = next(
                    i
                    for i, row in enumerate(dashboard["rows"])
                    if row["date"] == default_date
                )
                table.move_cursor(row=row_index, column=0)
        category_table = self.query_one("#week-category-table", DataTable)
        category_table.clear(columns=False)
        cat_rows = []
        for section_name in ("positive", "negative", "unscored"):
            rows = report[section_name]
            if rows:
                cat_rows.append((f"[{section_name.upper()}]", "", "", ""))
            for name, hours, rate, pts in rows:
                cat_rows.append(
                    (name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts))
                )
        if report["positive_results"]:
            cat_rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in report["positive_results"]:
                cat_rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if report["negative_results"]:
            cat_rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in report["negative_results"]:
                cat_rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        category_table.add_rows(cat_rows)
        summary = dashboard["summary"]
        week_hours = sum(r["hours"] for r in dashboard["rows"])
        wh_h = int(week_hours)
        wh_m = int((week_hours - wh_h) * 60)
        table.border_title = f"[b][#63f3ff]Week ({week})[/][/]   [#8d98a7]Tracked: {wh_h}hrs {wh_m:02d}min[/]"
        table.border_subtitle = (
            f"[#8d98a7]Week net: {format_signed_rich(summary['actual'])} pts[/]"
        )
        category_table.border_title = "[b][#63f3ff]Category Totals[/][/]"

    def refresh_overview_view(self):
        cache = self._data_cache
        report = cache.get_report_sections("ALL_TIME", "ALL")
        table = self.query_one("#overview-table", DataTable)
        table.clear(columns=False)
        rows = []
        for section_name in ("positive", "negative", "unscored"):
            section_rows = report[section_name]
            if section_rows:
                rows.append((f"[{section_name.upper()}]", "", "", ""))
            for name, hours, rate, pts in section_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if report["positive_results"]:
            rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in report["positive_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if report["negative_results"]:
            rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in report["negative_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        table.add_rows(rows)
        total_hours = report["total_hours"]
        th_h = int(total_hours)
        th_m = int((total_hours - th_h) * 60)
        table.border_title = f"[b][#63f3ff]Overview[/][/]   [#8d98a7]Total Time: {th_h}hrs {th_m:02d}min[/]"
        table.border_subtitle = f"[#8d98a7]Lifetime total {format_signed_rich(report['total_points'])} pts[/]"

    def refresh_day_view(self):
        cache = self._data_cache
        metrics = cache.get_day_metrics(self.selected_day)
        table = self.query_one("#day-table", DataTable)
        table.clear(columns=False)
        pos_rows = [r for r in metrics["results"] if r[3] is not None and r[3] >= 0]
        neg_rows = [r for r in metrics["results"] if r[3] is not None and r[3] < 0]
        unscored_rows = [r for r in metrics["results"] if r[3] is None]

        rows = []
        if pos_rows:
            rows.append(("[POSITIVE]", "", "", ""))
            for name, hours, rate, pts in pos_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if neg_rows:
            rows.append(("[NEGATIVE]", "", "", ""))
            for name, hours, rate, pts in neg_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        if metrics["positive_results"]:
            rows.append(("[LOGGED POSITIVE]", "", "", ""))
            for name, _, _, pts in metrics["positive_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if metrics["negative_results"]:
            rows.append(("[LOGGED NEGATIVE]", "", "", ""))
            for name, _, _, pts in metrics["negative_results"]:
                rows.append((name, "—", "logged", fmt_pts_rich(pts)))
        if unscored_rows:
            rows.append(("[UNSCORED]", "", "", ""))
            for name, hours, rate, pts in unscored_rows:
                rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
        table.add_rows(rows)
        dh = int(metrics["total_hours"])
        dm = int((metrics["total_hours"] - dh) * 60)
        table.border_title = f"[b][#63f3ff]Day ({self.selected_day})[/][/]   [#8d98a7]Tracked: {dh}hrs {dm:02d}min[/]"
        total_pos = round(metrics["earned"] + metrics["logged_positive"], 1)
        total_neg = round(metrics["tracked_negative"] + metrics["logged_negative"], 1)
        table.border_subtitle = (
            f"[#8d98a7]Pos [#37d994]+{total_pos:.1f}[/]   "
            f"Negs [#ff5f5f]-{total_neg:.1f}[/]   Net {format_signed_rich(metrics['net'])}[/]"
        )

    def refresh_negatives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#negatives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows(
            [
                (name, fmt_pts_rich(-points))
                for name, points in get_negative_catalog_rows()
            ]
        )
        recent = self.query_one("#negatives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_negative_log_rows()
        recent.add_rows(
            [
                (row["date"], row["name"], fmt_pts_rich(-row["points"]))
                for row in recent_rows
            ]
        )
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press n to log. Visible penalties: [#ff5f5f]-{total_recent:.0f}[/] pts[/]"

    def refresh_positives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#positives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows(
            [
                (name, fmt_pts_rich(points))
                for name, points in get_positive_catalog_rows()
            ]
        )
        recent = self.query_one("#positives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_positive_log_rows()
        recent.add_rows(
            [
                (row["date"], row["name"], fmt_pts_rich(row["points"]))
                for row in recent_rows
            ]
        )
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press p to log. Visible positives: [#37d994]+{total_recent:.0f}[/] pts[/]"

    def refresh_recovery_view(self):
        cache = self._data_cache
        data = cache.get_recovery_rows("ALL_TIME", "ALL")
        table = self.query_one("#recovery-table", DataTable)
        table.clear(columns=False)
        rows = []
        for row in data["rows"]:
            rate = row["rate"]
            color = (
                "[#37d994]"
                if rate >= 3
                else (
                    "[#ffd700]"
                    if rate >= 2
                    else ("[#63f3ff]" if rate >= 1 else "[#d7dde8]")
                )
            )
            rows.append(
                (
                    f"{color}{row['category']}[/]",
                    f"{color}{fmt_rate(rate)}[/]",
                    f"{color}{row['hours_needed']}[/]",
                )
            )
        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Recovery[/][/]"
        table.border_subtitle = (
            "[#8d98a7]Already non-negative.[/]"
            if not data["rows"]
            else f"[#8d98a7]Current total {format_signed_rich(data['total_points'])} pts[/]"
        )

    def refresh_sync_view(self):
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
            ("Current week", status["current_week"]),
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
        # ── Backfill section ──────────────────────────────────────────
        bf = status.get("backfill_status", {})
        bf_status = bf.get("status")
        weeks_done = bf.get("weeks_backfilled", 0)
        weeks_total = bf.get("weeks_discovered", 0) or bf.get("total_weeks", 0)
        weeks_left = bf.get("weeks_remaining", 0)
        requests_used = bf.get("requests_used", 0)
        requests_needed = bf.get("requests_needed", 0)

        if bf_status is None and not bf.get("earliest_week"):
            rows.append(("[b]Backfill[/b]", "[#8d98a7]Not yet run[/]"))
        else:
            # Status line
            status_labels = {
                "started": ("Running...", "#63f3ff"),
                "success": ("Complete", "#37d994"),
            }
            if bf_status == "failed":
                reason = bf.get("stopped_reason", "?")
                status_str = f"[#ffd700]Failed ({reason})[/]"
            elif bf_status in status_labels:
                label, color = status_labels[bf_status]
                status_str = f"[{color}]{label}[/]"
            else:
                status_str = bf_status or "[#8d98a7]—[/]"
            rows.append(("[b]Backfill[/b]", status_str))

            if weeks_total > 0:
                pct = min(100, int(weeks_done / weeks_total * 100))
                rows.append((" Progress",
                             f"[#d7dde8]{weeks_done}[/]/"
                             f"[#d7dde8]{weeks_total}[/] "
                             f"[#63f3ff]{pct}%[/]"))
                if weeks_left > 0:
                    rows.append((" Remaining",
                                 f"[#ffd700]{weeks_left}[/] "
                                 f"([#8d98a7]~{requests_needed} req[/])"))
            elif bf_status == "failed":
                rows.append((" Note",
                              "[#8d98a7]Press b to re-run[/]"))

            if requests_used > 0:
                rows.append((" Requests",
                             f"[#d7dde8]{requests_used} used[/], "
                             f"[#8d98a7]~{requests_needed} needed[/]"))

            # Live quota estimate for backfill
            q_rem = status.get("quota_remaining")
            q_limit = status.get("quota_limit")
            if q_rem is not None and weeks_left > 0:
                try:
                    q_rem_int = int(q_rem)
                    possible = min(q_rem_int, weeks_left)
                    limit_str = str(q_limit) if q_limit is not None else "?"
                    rows.append((" Quota",
                                 f"[#63f3ff]{q_rem_int}[/]/"
                                 f"{limit_str} "
                                 f"[#8d98a7]~{possible}w possible[/]"))
                except (ValueError, TypeError):
                    pass

        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Sync Status[/][/]"
        table.border_subtitle = (
            "[#8d98a7]u syncs current week. U refreshes projects and syncs 4 weeks.[/]"
        )

    def refresh_month_view(self):
        cache = self._data_cache
        if cache is None:
            return
        table = self.query_one("#month-table", DataTable)
        with table.prevent(DataTable.RowHighlighted):
            table.clear(columns=False)
            months = cache.get_monthly_aggregates(12)
            for m in months:
                net_str = format_signed_rich(m["net"])
                table.add_row(m["month"], f"{m['hours']:.1f}h", net_str, key=m["month"])
        table.border_title = "[b][#63f3ff]Month Overview (Last 12)[/][/]"

    def refresh_heatmap_view(self):
        cache = self._data_cache
        if cache is None:
            return
        grid = self.query_one("#heatmap-grid", Static)
        legend = self.query_one("#heatmap-legend", Label)

        year = date.today().year
        day_net_map = cache.get_yearly_day_net_map(year)

        if not day_net_map:
            grid.update("[dim]No data for this year yet.[/]")
            legend.update("")
            self._heatmap_grid_start = None
            self._heatmap_num_weeks = 0
            return

        values = sorted(day_net_map.values())
        n = len(values)
        p10_idx = max(0, int(n * 0.1))
        p90_idx = max(0, min(n - 1, int(n * 0.9)))
        p10 = values[p10_idx]
        p90 = values[p90_idx]
        abs_max = max(abs(p10), abs(p90))

        lines, grid_start, num_weeks = build_yearly_heatmap_lines(
            year, day_net_map, abs_max
        )
        self._heatmap_grid_start = grid_start
        self._heatmap_num_weeks = num_weeks

        grid.update("\n".join(lines))

        legend.update(
            f"[dim]Less[/] [dim]▁[/][#37d994]▂▃▄▅[/] [dim]More  •  "
            f"Red = negative  •  Green = positive  •  "
            f"P10={p10:.1f}  P90={p90:.1f}[/]"
        )
        grid.border_title = f"[b][#63f3ff]Heatmap \u2014 {year}[/][/]"

    # ── Event handlers ──

    @on(DataTable.RowHighlighted, "#week-table")
    def update_selected_day(self, event: DataTable.RowHighlighted):
        if event.row_key is None:
            return
        new_day = str(event.row_key.value)
        if new_day == self.selected_day:
            return
        self.selected_day = new_day
        self.refresh_day_view()
        self._sync_spark_days_cursor()

    @on(DataTable.RowHighlighted, "#spark-days-table")
    def spark_day_highlighted(self, event: DataTable.RowHighlighted):
        if event.row_key is None:
            return
        new_day = str(event.row_key.value)
        if new_day == self.selected_day:
            return
        self.selected_day = new_day
        self.refresh_day_view()
        self._sync_week_table_cursor()

    @on(DataTable.RowHighlighted, "#month-table")
    def month_row_highlighted(self, event: DataTable.RowHighlighted):
        if self.active_view_index != 3:
            return
        if event.row_key is None:
            return
        month_str = str(event.row_key.value)
        year_str, month_str_part = month_str.split("-")
        first = date(int(year_str), int(month_str_part), 1)
        week_str = get_week_str(first)
        self._active_week = week_str
        self.refresh_week_view()
        self.update_status_line()

    @on(Click, "#heatmap-grid")
    def heatmap_click(self, event: Click):
        year = date.today().year
        grid_start = self._heatmap_grid_start
        num_weeks = self._heatmap_num_weeks
        if grid_start is None or num_weeks <= 0:
            return
        col = (event.x - 1 - HEATMAP_ROW_PREFIX) // 2
        row = event.y - 1
        if not (0 <= row <= 6 and 0 <= col < num_weeks):
            return
        clicked_date = grid_start + timedelta(weeks=col, days=row)
        if clicked_date.year == year and clicked_date <= date.today():
            self.selected_day = clicked_date.strftime("%Y-%m-%d")
            self._active_week = get_week_str(clicked_date)
            self.refresh_week_view()
            self.refresh_day_view()
            self._sync_week_table_cursor()
            self.update_status_line()

    @on(Click, "#spark-catchup")
    def on_catchup_click(self):
        """Click catchup → navigate to Recovery view."""
        RECOVERY_INDEX = 7
        if self.active_view_index == RECOVERY_INDEX:
            return
        self.active_view_index = RECOVERY_INDEX
        self._refresh_view_by_index(RECOVERY_INDEX)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_line()
        self.focus_active_view()
        self._schedule_resize()

    def _sync_spark_days_cursor(self):
        table = self.query_one("#spark-days-table", DataTable)
        for i, key in enumerate(table.rows.keys()):
            if str(key.value) == self.selected_day:
                with table.prevent(DataTable.RowHighlighted):
                    table.move_cursor(row=i, animate=False)
                break

    def _sync_week_table_cursor(self):
        table = self.query_one("#week-table", DataTable)
        for i, key in enumerate(table.rows.keys()):
            if str(key.value) == self.selected_day:
                with table.prevent(DataTable.RowHighlighted):
                    table.move_cursor(row=i, animate=False)
                break

    @on(Tabs.TabActivated, "#view-tabs")
    def on_tab_activated(self, event: Tabs.TabActivated):
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

    def action_next_view(self):
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_line()
        self.focus_active_view()
        self._schedule_resize()

    def action_prev_view(self):
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.update_status_line()
        self.focus_active_view()
        self._schedule_resize()

    def action_nav_month_prev(self):
        if self.active_view_index == 3:
            table = self.query_one("#month-table", DataTable)
            cursor = table.cursor_row
            if cursor is None or cursor == 0:
                return
            table.move_cursor(row=cursor - 1, animate=False)

    def action_nav_month_next(self):
        if self.active_view_index == 3:
            table = self.query_one("#month-table", DataTable)
            cursor = table.cursor_row
            if cursor is None:
                table.move_cursor(row=0, animate=False)
            elif cursor < len(table.rows) - 1:
                table.move_cursor(row=cursor + 1, animate=False)

    def action_refresh_data(self):
        load_runtime_settings()
        self.refresh_all_views()
        self.notify("Reloaded local data")

    def action_show_help(self):
        self.notify(
            "Left/right switch views, n add negative, u sync, U full sync, "
            "b backfill, q quit"
        )

    def action_sync_current_week(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Syncing current week...")
                self._do_sync_current_week()

        self.push_screen(
            ConfirmScreen("Sync current week", "Run a current-week sync now?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_current_week(self):
        try:
            result = sync_current_week_light(prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_sync_done, ok, message, "Synced current week")

    def action_sync_full(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Syncing last 4 weeks...")
                self._do_sync_full()

        self.push_screen(
            ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"),
            after_confirm,
        )

    @work(thread=True)
    def _do_sync_full(self):
        try:
            result = sync_api_to_csv(4, prompt_on_warning=False)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        ok = result["success"]
        message = result.get("message", "")
        self.call_from_thread(self._on_sync_done, ok, message, "Synced last 4 weeks")

    def _on_sync_done(self, ok, message, success_msg):
        load_runtime_settings()
        reset_cache()
        self.refresh_all_views()
        if ok:
            self.notify(success_msg)
        else:
            self.notify(message or "Sync skipped", severity="warning")

    def action_backfill(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Starting backfill (pauses on quota, resumes automatically)...")
                self._do_backfill()

        self.push_screen(
            ConfirmScreen("Backfill", "Fetch all historical data from Toggl? "
                          "Pauses when quota runs out, resumes when quota resets."),
            after_confirm,
        )

    @work(thread=True)
    def _do_backfill(self):
        from toggl.backfill import run_backfill
        from toggl.api import get_api_token, get_projects_map

        try:
            token = get_api_token()
            projects_map = get_projects_map(token)
            result = run_backfill(token, projects_map)
        except (TogglRateLimitError, TogglAPIError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        except Exception as e:
            self.call_from_thread(
                self.notify, f"Backfill error: {e}", severity="error")
            return

        ok = result["status"] == "success"
        weeks = result.get("weeks_backfilled", 0)
        reason = result.get("stopped_reason", "")
        if ok:
            msg = f"Backfill complete ({weeks} weeks)"
        else:
            msg = f"Backfill stopped: {reason} ({weeks} weeks done)"
        self.call_from_thread(self._on_sync_done, ok, msg, msg)

    def action_add_negative(self):
        def after_input(value):
            if value:
                ok, message = log_negative_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(NegativeInputScreen(), after_input)

    def action_add_positive(self):
        def after_input(value):
            if value:
                ok, message = log_positive_direct(value)
                self.refresh_all_views()
                if ok:
                    self.notify(message)
                else:
                    self.notify(message, severity="error")

        self.push_screen(PositiveInputScreen(), after_input)

    def on_resize(self, event) -> None:
        new_size = event.size
        if new_size.width == 0 or new_size.height == 0:
            return
        self._schedule_resize()

    def _resize_tables(self):
        from rich.text import Text

        # ── Main content tables ────────────────────────────────────────────
        table_ids = [
            "#week-table",
            "#week-category-table",
            "#overview-table",
            "#day-table",
            "#negatives-catalog-table",
            "#negatives-log-table",
            "#positives-catalog-table",
            "#positives-log-table",
            "#recovery-table",
            "#sync-table",
        ]
        text_cols = {"Category", "Negative", "Positive", "Metric", "Value", "Cate"}

        rail_w = 34
        content_w = self.size.width - rail_w

        if content_w <= 0:
            return

        available_width = max(10, content_w - 2)

        for t_id in table_ids:
            try:
                table = self.query_one(t_id, DataTable)
            except Exception:
                continue

            if not table.columns:
                continue

            # Skip tables in hidden views to avoid forced reflows
            if not table.display:
                continue

            col_keys = list(table.columns.keys())
            n_cols = len(col_keys)
            cell_padding = table.cell_padding

            req_widths = {
                key: len(col.label.plain) for key, col in table.columns.items()
            }

            for row_idx in range(table.row_count):
                row_data = table.get_row_at(row_idx)
                for col_idx, col_key in enumerate(col_keys):
                    val = str(row_data[col_idx])
                    try:
                        cell_w = Text.from_markup(val).cell_len
                    except Exception:
                        cell_w = len(strip_ansi(val))
                    if cell_w > req_widths[col_key]:
                        req_widths[col_key] = cell_w

            total_padding = 2 * cell_padding * n_cols
            content_budget = available_width - total_padding
            total_req_content = sum(req_widths.values())

            expandable_keys = []
            fixed_keys = []
            for key, col in table.columns.items():
                label_str = col.label.plain
                if label_str in text_cols or label_str.startswith("Cat"):
                    expandable_keys.append(key)
                else:
                    fixed_keys.append(key)

            if not expandable_keys:
                expandable_keys = list(table.columns.keys())
                fixed_keys = []

            if content_budget >= total_req_content:
                extra = content_budget - total_req_content
                for key in fixed_keys:
                    table.columns[key].width = req_widths[key]
                    table.columns[key].auto_width = False
                expand_extra = extra // len(expandable_keys)
                rem = extra % len(expandable_keys)
                for i, key in enumerate(expandable_keys):
                    table.columns[key].width = (
                        req_widths[key] + expand_extra + (1 if i < rem else 0)
                    )
                    table.columns[key].auto_width = False
            else:
                min_widths = {
                    key: max(3, len(col.label.plain))
                    for key, col in table.columns.items()
                }
                total_min = sum(min_widths.values())

                if content_budget <= total_min:
                    base_w = content_budget // n_cols
                    rem = content_budget % n_cols
                    for i, key in enumerate(table.columns.keys()):
                        table.columns[key].width = max(
                            1, base_w + (1 if i < rem else 0)
                        )
                        table.columns[key].auto_width = False
                else:
                    remaining = content_budget
                    widths = dict(min_widths)
                    remaining -= total_min

                    for key in fixed_keys:
                        extra = min(req_widths[key] - min_widths[key], remaining)
                        if extra > 0:
                            widths[key] += extra
                            remaining -= extra

                    if remaining > 0 and expandable_keys:
                        expand_extra = remaining // len(expandable_keys)
                        rem = remaining % len(expandable_keys)
                        for i, key in enumerate(expandable_keys):
                            widths[key] += expand_extra + (1 if i < rem else 0)

                    for key, w in widths.items():
                        table.columns[key].width = w
                        table.columns[key].auto_width = False

            table._require_update_dimensions = True
            table.refresh(layout=True)
            table.scroll_to(x=0, animate=False)

        # ── Spark rail tables (fixed 34-char rail) ─────────────────────────
        # These are independent of the main content area.  Give the label col
        # a fixed 4-char width; the Net col gets whatever remains.
        SPARK_RAIL_W = 34
        for t_id in ("#spark-weeks-table", "#spark-days-table"):
            try:
                table = self.query_one(t_id, DataTable)
            except Exception:
                continue
            if not table.columns:
                continue
            if not table.display:
                continue

            col_keys = list(table.columns.keys())
            cell_padding = table.cell_padding
            # DataTable border = 2 chars; 2*padding per column
            inner_w = SPARK_RAIL_W - 2
            total_padding = 2 * cell_padding * len(col_keys)
            content_budget = max(8, inner_w - total_padding)

            label_w = 6
            net_w = max(4, content_budget - label_w)

            for i, key in enumerate(col_keys):
                table.columns[key].width = label_w if i == 0 else net_w
                table.columns[key].auto_width = False

            table._require_update_dimensions = True
            table.refresh(layout=True)
            table.scroll_to(x=0, animate=False)
