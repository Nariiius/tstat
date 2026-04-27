"""TogglTUI — Textual terminal UI for TogglTrack."""

from datetime import datetime, date, timedelta

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static, OptionList
from textual.worker import Worker, get_current_worker
from textual._work_decorator import work

from toggl.const import TASK_SHORT_NAMES, SPARK_W, BLAME_W, strip_ansi
from toggl.config import POINTS, NEGATIVES, POSITIVES, get_daily_target, load_runtime_settings
from toggl.cache import (
    DataCache, get_cache, reset_cache,
    get_current_week, get_week_dates, get_sunday_of_week, get_week_str,
    needs_auto_update, get_last_updated_str, _load_history,
    sync_current_week_light, sync_api_to_csv,
)
from toggl.calc import calculate, format_signed, get_negative_catalog_rows, get_positive_catalog_rows
from toggl.api import (
    API_RUN_STATS, _reset_api_stats, _print_api_usage_summary, _format_reset_window,
    get_api_token, check_quota,
    TogglRateLimitError, TogglAPIError,
)
from toggl.neg import (
    log_positive_direct, log_negative_direct,
)
def get_sync_status_data():
    history = _load_history()
    from toggl.api import get_projects_cache_age_days, API_RUN_STATS
    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": history.get("synced_weeks", {}),
        "synced_days": history.get("synced_days", {}),
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
    }

def time_left_in_week():
    from datetime import datetime, timedelta
    now = datetime.now()
    sunday = now + timedelta(days=(6 - now.weekday()))
    end = sunday.replace(hour=23, minute=59, second=59)
    diff = end - now
    if diff.total_seconds() < 0:
        return ""
    days, sec = diff.days, diff.seconds
    hr = sec // 3600
    mn = (sec % 3600) // 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hr > 0: parts.append(f"{hr}h")
    parts.append(f"{mn}m")
    return " ".join(parts)


# ──────────────────────────────────────────────
# SPARK TABLE CELL RENDERER
# ──────────────────────────────────────────────

def _spark_net_rich(net, max_abs, bar_w=4, dim_zero=False,
                     blame_tracked=0, blame_logged=0, blame_w=3):
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
    bar = "█" * bar_len
    if net > 0:
        return f"[#37d994]{bar} +{net}[/]"
    else:
        blame_total = blame_tracked + blame_logged
        if blame_total > 0 and blame_w > 0:
            red_count = round(blame_tracked / blame_total * blame_w)
            mag_count = blame_w - red_count
            blame = f"[#ff5f5f]{'█' * red_count}[/][#ff5fff]{'█' * mag_count}[/]"
            return f"[#ff5f5f]{net} {bar}[/]{blame}"
        return f"[#ff5f5f]{net} {bar}[/]"


def fmt_rate(rate):
    if rate is None:
        return "—"
    r = int(rate) if rate == int(rate) else rate
    return f"×{r}"


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

class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("Y", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("N", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title, body):
        super().__init__()
        self.title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static(self.body, classes="dialog-body")
                yield Static("[Y/Enter] confirm   [N/Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = f"[b][#63f3ff]{self.title}[/][/]"
        # Override the title set above with the actual title
        self.query_one("#dialog-box").border_title = f"[b][#63f3ff]{self.title}[/][/]"
        self.query_one("#dialog-box").border_subtitle = self.body

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class NegativeInputScreen(ModalScreen[str | None]):
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static("Select a negative action to log.", classes="dialog-body")
                yield OptionList(id="negative-list")
                yield Static("[Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = "[b][#63f3ff]Log Negative[/][/]"
        option_list = self.query_one("#negative-list", OptionList)
        for name in NEGATIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#negative-list")
    def submit_negative(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    def key_escape(self):
        self.dismiss(None)


class PositiveInputScreen(ModalScreen[str | None]):
    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield Static("Select a positive action to log.", classes="dialog-body")
                yield OptionList(id="positive-list")
                yield Static("[Esc] cancel", classes="dialog-help")

    def on_mount(self):
        self.query_one("#dialog-box").border_title = "[b][#37d994]Log Positive[/][/]"
        option_list = self.query_one("#positive-list", OptionList)
        for name in POSITIVES:
            option_list.add_option(name)
        option_list.focus()

    @on(OptionList.OptionSelected, "#positive-list")
    def submit_positive(self, event: OptionList.OptionSelected):
        self.dismiss(str(event.option.prompt))

    def key_escape(self):
        self.dismiss(None)


# ──────────────────────────────────────────────
# MAIN TUI APP
# ──────────────────────────────────────────────

class TogglTUI(App):
    CSS = """
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
        height: 3;
        border: solid #2e3947;
        padding: 0 1;
    }

    #view-tabs {
        height: 1;
        color: #8d98a7;
    }

    .view-tab {
        width: auto;
        margin-right: 2;
        color: #8d98a7;
    }

    .view-tab.-active {
        color: #63f3ff;
        text-style: bold;
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
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    DataTable > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-rail {
        width: 34;
        min-width: 34;
        max-width: 34;
        border: none;
        padding: 0;
        display: block;
    }

    #spark-rail.-hidden {
        display: none;
    }

    #spark-weeks-table {
        height: auto;
        min-height: 5;
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-weeks-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-weeks-table > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-days-table {
        height: 1fr;
        border: solid #2e3947;
        background: #0b1016;
        color: #d7dde8;
    }

    #spark-days-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #spark-days-table > .datatable--cursor {
        background: #27323d;
        color: #f5f7fa;
    }

    #spark-catchup {
        height: auto;
        border: solid #2e3947;
        padding: 0 1;
    }

    #footer {
        height: auto;
        border-top: solid #2e3947;
        padding: 0 1;
    }

    #footer-main {
        color: #63f3ff;
    }

    #dialog {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #dialog-box {
        width: 60;
        height: auto;
        border: solid #2e3947;
        padding: 1 2;
        background: #0b1016;
    }

    .dialog-body {
        margin-bottom: 1;
    }

    .dialog-help {
        color: #8d98a7;
        margin-top: 1;
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

    Toast {
        background: #0b1016;
        color: #d7dde8;
        border: solid #2e3947;
        padding: 0 1;
        margin: 1 1 0 0;
        height: auto;
    }
    Toast.-information {
        border: solid #37d994;
    }
    Toast.-warning {
        border: solid #e2b714;
    }
    Toast.-error {
        border: solid #ff5f5f;
    }
    """

    BINDINGS = [
        Binding("left", "prev_view", "Prev View"),
        Binding("right", "next_view", "Next View"),
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("u", "sync_current_week", "Sync Week"),
        Binding("U", "sync_full", "Full Sync"),
        Binding("n", "add_negative", "Add Negative"),
        Binding("p", "add_positive", "Add Positive"),
        Binding("s", "toggle_sparkbar", "Sparkbar"),
        Binding("question_mark", "show_help", "Help"),
    ]

    VIEWS = ["Overview", "Day", "Week", "Negatives", "Positives", "Recovery", "Sync/Quota"]

    def __init__(self):
        super().__init__()
        self.active_view_index = 1
        self.selected_day = date.today().strftime("%Y-%m-%d")
        self.sparkbar_collapsed = False
        self.sparkbar_forced_open = True
        self._table_resize_timer = None
        self._data_cache: DataCache | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Container(id="chrome"):
                with Horizontal(id="view-tabs"):
                    for index, view in enumerate(self.VIEWS):
                        yield Static(view, classes="view-tab", id=f"view-tab-{index}")
            with Horizontal(id="main"):
                with Container(id="content"):
                    with Container(id="overview-view", classes="view -active"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="overview-table")
                    with Container(id="day-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="day-table")
                    with Container(id="week-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="week-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="week-category-table")
                    with Container(id="negatives-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="negatives-catalog-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="negatives-log-table")
                    with Container(id="positives-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="positives-catalog-table")
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="positives-log-table")
                    with Container(id="recovery-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="recovery-table")
                    with Container(id="sync-view", classes="view"):
                        yield DataTable(zebra_stripes=False, cursor_type="row", id="sync-table")
                with Vertical(id="spark-rail"):
                    yield DataTable(show_header=False, cursor_type="row", id="spark-weeks-table", zebra_stripes=False)
                    yield DataTable(show_header=False, cursor_type="row", id="spark-days-table", zebra_stripes=False)
                    yield Static(id="spark-catchup")
            with Vertical(id="footer"):
                yield Static(id="footer-main")

    def on_mount(self):
        self._setup_tables()
        load_runtime_settings()
        if needs_auto_update():
            self._do_auto_refresh()
        self.refresh_all_views()

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
        elif message:
            self.notify("Auto-refresh skipped", severity="warning")

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

        spark_weeks = self.query_one("#spark-weeks-table", DataTable)
        spark_weeks.add_columns("Label", "Net")

        spark_days = self.query_one("#spark-days-table", DataTable)
        spark_days.add_columns("Day", "Net")

    def refresh_all_views(self):
        self._data_cache = DataCache.load()
        self.update_tabs()
        self.update_status_line()
        self.refresh_spark_tables()
        for idx in self._VIEW_REFRESH_MAP:
            self._refresh_view_by_index(idx)
        self.update_view_visibility()
        self.update_sparkbar_visibility()
        self._schedule_resize()

    _VIEW_REFRESH_MAP = {
        0: "refresh_overview_view",
        1: "refresh_day_view",
        2: "refresh_week_view",
        3: "refresh_negatives_view",
        4: "refresh_positives_view",
        5: "refresh_recovery_view",
        6: "refresh_sync_view",
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
        for index, view in enumerate(self.VIEWS):
            tab = self.query_one(f"#view-tab-{index}", Static)
            tab.update(view)
            tab.set_class(index == self.active_view_index, "-active")

    def update_status_line(self):
        current_week = get_current_week()
        synced = get_last_updated_str()

        chrome = self.query_one("#chrome", Container)
        chrome.border_title = "[b][#63f3ff]Toggl Stats[/][/]"
        chrome.border_subtitle = f"  | [#8d98a7]Updated {synced}[/]"

        footer_main = Text()
        footer_main.append("Views ", style="bold #63f3ff")
        footer_main.append("<- ->", style="bold #63f3ff")
        footer_main.append(" switch  •  ", style="#8d98a7")
        footer_main.append("n", style="bold #63f3ff")
        footer_main.append(" negative  •  ", style="#8d98a7")
        footer_main.append("p", style="bold #63f3ff")
        footer_main.append(" positive  •  ", style="#8d98a7")
        footer_main.append("u", style="bold #63f3ff")
        footer_main.append(" sync  •  ", style="#8d98a7")
        footer_main.append("s", style="bold #63f3ff")
        footer_main.append(" sparkbar  •  ", style="#8d98a7")
        footer_main.append("q", style="bold #63f3ff")
        footer_main.append(" quit", style="#8d98a7")

        self.query_one("#footer-main", Static).update(footer_main)

    def update_view_visibility(self):
        view_ids = [
            "#overview-view", "#day-view", "#week-view",
            "#negatives-view", "#positives-view", "#recovery-view", "#sync-view",
        ]
        for index, view_id in enumerate(view_ids):
            widget = self.query_one(view_id, Container)
            widget.set_class(index == self.active_view_index, "-active")

    def focus_active_view(self):
        focus_targets = {
            0: "#overview-table", 1: "#day-table", 2: "#week-table",
            3: "#negatives-catalog-table", 4: "#positives-catalog-table",
            5: "#recovery-table", 6: "#sync-table",
        }
        selector = focus_targets.get(self.active_view_index)
        if selector:
            self.query_one(selector, DataTable).focus()

    def update_sparkbar_visibility(self):
        rail = self.query_one("#spark-rail", Vertical)
        auto_collapse = self.size.width < 120
        rail.set_class(
            self.sparkbar_collapsed or (auto_collapse and not self.sparkbar_forced_open),
            "-hidden",
        )

    # ── Spark tables ──

    def refresh_spark_tables(self):
        self._refresh_spark_weeks()
        self._refresh_spark_days()
        self._refresh_spark_catchup()

    def _refresh_spark_weeks(self):
        cache = self._data_cache
        table = self.query_one("#spark-weeks-table", DataTable)
        table.clear(columns=False)

        current_sunday = get_sunday_of_week(date.today())
        weeks_data = []

        for i in range(3, 0, -1):
            pw_sunday = current_sunday - timedelta(days=7 * i)
            pw = get_week_str(pw_sunday)
            pw_num = pw.split("W")[1]
            pw_label = f"W{int(pw_num)}"

            pw_data = cache.get_week_projects(pw)
            if pw_data:
                pw_results = calculate(pw_data)
                pw_earned = sum(r[3] for r in pw_results if r[3] is not None and r[3] > 0)
                pw_tracked_neg = sum(abs(r[3]) for r in pw_results if r[3] is not None and r[3] < 0)
            else:
                pw_earned = 0.0
                pw_tracked_neg = 0.0

            pw_tracked, pw_logged = cache.get_week_neg_breakdown(pw)
            pw_logged_pos = cache.get_week_pos_breakdown(pw)
            pw_net = round(pw_earned - pw_tracked_neg - pw_logged + pw_logged_pos, 1)
            weeks_data.append((pw_label, pw, pw_net, pw_tracked, pw_logged))

        max_abs = max((abs(w[2]) for w in weeks_data), default=1) or 1

        for label, wk, net, tracked, logged in weeks_data:
            net_cell = _spark_net_rich(net, max_abs,
                                       blame_tracked=tracked, blame_logged=logged)
            table.add_row(label, net_cell, key=wk)

        table.border_title = "[b][#63f3ff]Past 3 Weeks[/][/]"
        # Fix: border_title was set twice in original, keep the last one
        table.border_title = "[b][#63f3ff]Past 3 Weeks[/][/]"

    def _refresh_spark_days(self):
        cache = self._data_cache
        table = self.query_one("#spark-days-table", DataTable)
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
            tracked_neg = sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0)
            net = round(earned - tracked_neg - neg_cost + pos_bonus, 1)
            has_data = bool(projs or neg_entries or pos_entries)
            logged_neg = round(neg_cost, 1)
            day_entries.append((d, d_str, net, has_data, tracked_neg, logged_neg, earned, pos_bonus))

        max_abs = max(
            (abs(net) for _, _, net, has, _, _, _, _ in day_entries if has and abs(net) >= 0.05),
            default=1,
        ) or 1

        cursor_row = None
        for i, (d, d_str, net, has_data, tracked_neg, logged_neg, earned, pos_bonus) in enumerate(day_entries):
            if not has_data and d > date.today():
                continue

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
            with table.prevent(DataTable.RowHighlighted):
                table.move_cursor(row=cursor_row)

        tw_num = week_str.split("W")[1]
        tw_label = f"W{int(tw_num)}"

        tw_total_neg = round(sum(dd[4] + dd[5] for dd in day_entries if dd[3]), 1)
        tw_total_pos = round(sum(dd[6] + dd[7] for dd in day_entries if dd[3]), 1)
        neg_val = int(tw_total_neg) if tw_total_neg == int(tw_total_neg) else tw_total_neg
        pos_val = int(tw_total_pos) if tw_total_pos == int(tw_total_pos) else tw_total_pos
        
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
            pts_val = int(lifetime_pts) if lifetime_pts == int(lifetime_pts) else lifetime_pts
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
            catchup.border_title = f"[b][#ff5f5f]Catch Up :[/][/] [#ff5f5f]{deficit_val} pts[/]"
            catchup.border_subtitle = f"[#63f3ff]in {tl_raw}[/]"

    # ── View refresh methods ──

    def refresh_week_view(self):
        cache = self._data_cache
        week = get_current_week()
        dashboard = cache.get_week_dashboard_rows(week)
        report = cache.get_report_sections(week, "WEEK")
        table = self.query_one("#week-table", DataTable)
        table.clear(columns=False)
        week_rows = []
        for row in dashboard["rows"]:
            neg_text = "—" if row["negative_total"] == 0 else f"[#ff5f5f]-{row['negative_total']:.1f}[/]"
            pos_text = "—" if row["positive_total"] == 0 else f"[#37d994]+{row['positive_total']:.1f}[/]"
            hour_text = "—" if row["hours"] == 0 else f"{row['hours']:.1f}h"
            earned_text = "—" if row["hours"] == 0 and row["earned"] == 0 else format_signed_rich(row["earned"])
            week_rows.append((
                row["day"],
                row["date_short"],
                hour_text,
                earned_text,
                pos_text,
                neg_text,
                format_signed_rich(row["net"]),
                row["date"],
            ))
        for cells in week_rows:
            key = cells[7]
            table.add_row(*cells[:7], key=key)
        if dashboard["rows"]:
            default_date = self.selected_day if any(r["date"] == self.selected_day for r in dashboard["rows"]) else dashboard["rows"][0]["date"]
            self.selected_day = default_date
            row_index = next(i for i, row in enumerate(dashboard["rows"]) if row["date"] == default_date)
            with table.prevent(DataTable.RowHighlighted):
                table.move_cursor(row=row_index, column=0)
        category_table = self.query_one("#week-category-table", DataTable)
        category_table.clear(columns=False)
        cat_rows = []
        for section_name in ("positive", "negative", "unscored"):
            rows = report[section_name]
            if rows:
                cat_rows.append((f"[{section_name.upper()}]", "", "", ""))
            for name, hours, rate, pts in rows:
                cat_rows.append((name, f"{hours:.2f}h", fmt_rate(rate), fmt_pts_rich(pts)))
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
        table.border_subtitle = f"[#8d98a7]Week net: {format_signed_rich(summary['actual'])} pts[/]"
        category_table.border_title = "[b][#63f3ff]Category Totals[/][/]"

    def refresh_overview_view(self):
        cache = self._data_cache
        report = cache.get_report_sections("ALL_TIME", "ALL")
        current_week = get_current_week()
        week_total = cache.get_report_sections(current_week, "WEEK")["total_points"]
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
        table.border_subtitle = (
            f"[#8d98a7]Lifetime total {format_signed_rich(report['total_points'])} pts[/]"
        )

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
        dh = int(metrics['total_hours'])
        dm = int((metrics['total_hours'] - dh) * 60)
        table.border_title = f"[b][#63f3ff]Day ({self.selected_day})[/][/]   [#8d98a7]Tracked: {dh}hrs {dm:02d}min[/]"
        total_pos = round(metrics['earned'] + metrics['logged_positive'], 1)
        total_neg = round(metrics['tracked_negative'] + metrics['logged_negative'], 1)
        table.border_subtitle = (
            f"[#8d98a7]Pos [#37d994]+{total_pos:.1f}[/]   "
            f"Negs [#ff5f5f]-{total_neg:.1f}[/]   Net {format_signed_rich(metrics['net'])}[/]"
        )

    def refresh_negatives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#negatives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows([(name, fmt_pts_rich(-points)) for name, points in get_negative_catalog_rows()])
        recent = self.query_one("#negatives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_negative_log_rows()
        recent.add_rows([(row["date"], row["name"], fmt_pts_rich(-row["points"])) for row in recent_rows])
        total_recent = sum(row["points"] for row in recent_rows)
        catalog.border_title = "[b][#63f3ff]Catalog[/][/]"
        recent.border_title = "[b][#63f3ff]Recent Log[/][/]"
        recent.border_subtitle = f"[#8d98a7]Press n to log. Visible penalties: [#ff5f5f]-{total_recent:.0f}[/] pts[/]"

    def refresh_positives_view(self):
        cache = self._data_cache
        catalog = self.query_one("#positives-catalog-table", DataTable)
        catalog.clear(columns=False)
        catalog.add_rows([(name, fmt_pts_rich(points)) for name, points in get_positive_catalog_rows()])
        recent = self.query_one("#positives-log-table", DataTable)
        recent.clear(columns=False)
        recent_rows = cache.get_positive_log_rows()
        recent.add_rows([(row["date"], row["name"], fmt_pts_rich(row["points"])) for row in recent_rows])
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
            color = "[#37d994]" if rate >= 2 else ("[#63f3ff]" if rate >= 1 else "[#d7dde8]")
            rows.append((f"{color}{row['category']}[/]", f"{color}{fmt_rate(rate)}[/]", f"{color}{row['hours_needed']}[/]"))
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
        remaining = status["quota_remaining"] if status["quota_remaining"] is not None else "Unknown"
        limit = status["quota_limit"] if status["quota_limit"] is not None else "Unknown"
        rows = [
            ("Current week", status["current_week"]),
            ("Last updated", status["last_updated"]),
            ("Projects cache", "missing" if cache_age is None else f"{cache_age:.1f} days old"),
            ("Synced weeks", str(len(status["synced_weeks"]))),
            ("Synced days", str(len(status["synced_days"]))),
            ("Requests made", str(API_RUN_STATS["requests_made"])),
            ("Quota remaining", f"{remaining}/{limit}"),
        ]
        if status["quota_resets_in"] is not None:
            rows.append(("Quota resets in", _format_reset_window(status["quota_resets_in"])))
        table.add_rows(rows)
        table.border_title = "[b][#63f3ff]Sync Status[/][/]"
        table.border_subtitle = "[#8d98a7]u syncs current week. U refreshes projects and syncs 4 weeks.[/]"

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

    @on(Click, ".view-tab")
    def click_view_tab(self, event: Click):
        if event.widget.id and event.widget.id.startswith("view-tab-"):
            self.active_view_index = int(event.widget.id.rsplit("-", 1)[1])
            self._refresh_view_by_index(self.active_view_index)
            self.update_tabs()
            self.update_view_visibility()
            self.focus_active_view()
            self._schedule_resize()

    def action_next_view(self):
        self.active_view_index = (self.active_view_index + 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.focus_active_view()
        self._schedule_resize()

    def action_prev_view(self):
        self.active_view_index = (self.active_view_index - 1) % len(self.VIEWS)
        self._refresh_view_by_index(self.active_view_index)
        self.update_tabs()
        self.update_view_visibility()
        self.focus_active_view()
        self._schedule_resize()

    def action_refresh_data(self):
        load_runtime_settings()
        self.refresh_all_views()
        self.notify("Reloaded local data")

    def action_toggle_sparkbar(self):
        if self.size.width < 120:
            self.sparkbar_forced_open = not self.sparkbar_forced_open
            self.sparkbar_collapsed = False
        else:
            self.sparkbar_collapsed = not self.sparkbar_collapsed
            self.sparkbar_forced_open = False
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def action_show_help(self):
        self.notify("Left/right switch views, n add negative, u sync, U full sync, s toggle sparkbar, q quit")

    def action_sync_current_week(self):
        def after_confirm(confirmed):
            if confirmed:
                self.notify("Syncing current week...")
                self._do_sync_current_week()

        self.push_screen(ConfirmScreen("Sync current week", "Run a current-week sync now?"), after_confirm)

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

        self.push_screen(ConfirmScreen("Full sync", "Refresh projects and sync the last 4 weeks?"), after_confirm)

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
        self.update_sparkbar_visibility()
        self._schedule_resize()

    def _resize_tables(self):
        from rich.text import Text

        self.update_sparkbar_visibility()

        # ── Main content tables ────────────────────────────────────────────
        table_ids = [
            "#week-table", "#week-category-table", "#overview-table",
            "#day-table", "#negatives-catalog-table", "#negatives-log-table",
            "#positives-catalog-table", "#positives-log-table", "#recovery-table",
            "#sync-table"
        ]
        text_cols = {"Category", "Negative", "Positive", "Metric", "Value", "Cate"}

        rail = self.query_one("#spark-rail")
        rail_w = 34 if not rail.has_class("-hidden") else 0
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

            req_widths = {key: len(col.label.plain) for key, col in table.columns.items()}

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
                    table.columns[key].width = req_widths[key] + expand_extra + (1 if i < rem else 0)
                    table.columns[key].auto_width = False
            else:
                min_widths = {key: max(3, len(col.label.plain))
                              for key, col in table.columns.items()}
                total_min = sum(min_widths.values())

                if content_budget <= total_min:
                    base_w = content_budget // n_cols
                    rem = content_budget % n_cols
                    for i, key in enumerate(table.columns.keys()):
                        table.columns[key].width = max(1, base_w + (1 if i < rem else 0))
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

