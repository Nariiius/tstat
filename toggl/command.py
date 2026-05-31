"""Command tab — trajectory analytics workspace.

CalendarWidget: month-grid calendar sidebar with heatmap coloring.
CommandTab: unified analytics layout.
  Top section: Graph panel (75%) + Calendar (25%)
  Bottom section: Category Summary (35%) + Daily Breakdown (65%)
"""

from __future__ import annotations

from datetime import date, timedelta

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click
from textual.widgets import Button, DataTable, Label, Static

from toggl.graph import GraphWidget
from toggl.period import PeriodController, PeriodMode


# ── Color helpers ────────────────────────────────────────────────────

def _net_color(value: float) -> str:
    """Return a Rich color tag for a net value — bold thresholds."""
    if value >= 10:
        return "#2ecc71"     # bright green (excellent)
    if value > 0:
        return "#37d994"     # green (positive)
    if value <= -10:
        return "#ff4444"     # bright red (very negative)
    if value < 0:
        return "#ff5f5f"     # red (negative)
    return ""


def _label_for_day(
    d: date,
    today: date,
    anchor: date | None,
    anchor_week_set: set[date] | None,
    display_month: int,
    display_year: int,
    net: float,
) -> str:
    """Return Rich markup for a calendar day cell with heatmap coloring."""
    bg = _net_color(net)
    label = f"{d.day:>2}"
    if bg:
        label = f"[{bg}]{label}[/]"

    if d == anchor and d == today:
        label = f"[bold #e2b714 on #1e2a36]{label}[/]"
    elif d == today:
        label = f"[bold #e2b714]{label}[/]"
    elif d == anchor:
        label = f"[bold #63f3ff]{label}[/]"
    elif anchor_week_set and d in anchor_week_set:
        label = f"[#63f3ff]{label}[/]"
    elif d.month != display_month or d.year != display_year:
        label = f"[dim #4a5568]{label}[/]"
    return label


def _get_anchor_week_dates(anchor: date) -> set[date]:
    monday = anchor - timedelta(days=anchor.weekday())
    return {monday + timedelta(days=i) for i in range(7)}


# ── CalendarWidget ───────────────────────────────────────────────────


class CalendarWidget(Static):
    """Month-grid calendar sidebar with net-based heatmap coloring."""

    DEFAULT_CSS = """
    CalendarWidget {
        width: 1fr;
        height: 1fr;
        border: round #3d4f63;
        background: #0b1016;
        padding: 0 1;
    }
    CalendarWidget:focus-within {
        border: round #63f3ff;
    }
    #cal-nav {
        height: auto;
        layout: horizontal;
        align: center middle;
        padding: 0;
    }
    #cal-nav > Button {
        background: transparent;
        border: none;
        min-width: 5;
        color: #8d98a7;
    }
    #cal-nav > Button:hover {
        color: #63f3ff;
    }
    #cal-month-label {
        width: 1fr;
        text-align: center;
        color: #63f3ff;
        text-style: bold;
    }
    #cal-grid {
        height: auto;
        layout: vertical;
    }
    .cal-row {
        height: auto;
        layout: horizontal;
    }
    .cal-row > Label {
        width: 3;
        text-align: center;
        padding: 0;
    }
    .cal-dotw {
        color: #8d98a7;
        text-style: bold;
    }
    .cal-day {
        color: #d7dde8;
    }
    """

    def __init__(self, command_tab: "CommandTab"):
        super().__init__(id="command-calendar")
        self._command = command_tab
        self._display_year = date.today().year
        self._display_month = date.today().month
        self._day_nets: dict[str, float] = {}

    def set_day_net_values(self, day_nets: dict[str, float]):
        self._day_nets = day_nets

    def compose(self) -> ComposeResult:
        day_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        with Container(id="cal-nav"):
            yield Button("<<", id="cal-prev-month")
            yield Label("", id="cal-month-label")
            yield Button(">>", id="cal-next-month")
        with Container(id="cal-grid"):
            with Horizontal(classes="cal-row"):
                for dn in day_names:
                    yield Label(dn, classes="cal-dotw")
            for row_idx in range(6):
                with Horizontal(classes="cal-row"):
                    for col_idx in range(7):
                        cell_idx = row_idx * 7 + col_idx
                        yield Label("", id=f"cal-day-{cell_idx}", classes="cal-day")

    def rebuild(self):
        pc = self._command.period
        anchor = pc.get_anchor_date()
        self._display_year = anchor.year
        self._display_month = anchor.month

        first_day = date(self._display_year, self._display_month, 1)
        grid_start = first_day - timedelta(days=first_day.weekday())

        today = date.today()
        anchor_week = _get_anchor_week_dates(anchor) if pc.mode in (PeriodMode.WEEK,) else None

        self.query_one("#cal-month-label", Label).update(first_day.strftime("%B %Y"))

        for i in range(42):
            label = self.query_one(f"#cal-day-{i}", Label)
            day_date = grid_start + timedelta(days=i)
            d_str = day_date.strftime("%Y-%m-%d")
            net = self._day_nets.get(d_str, 0.0)
            markup = _label_for_day(
                day_date, today, anchor, anchor_week,
                self._display_month, self._display_year, net,
            )
            label.update(markup)

    @on(Button.Pressed, "#cal-prev-month")
    def _on_prev_month(self):
        if self._display_month == 1:
            self._display_month = 12
            self._display_year -= 1
        else:
            self._display_month -= 1
        target = date(self._display_year, self._display_month, 1)
        self._command.period.set_from_day(target)
        self._command.refresh_all()

    @on(Button.Pressed, "#cal-next-month")
    def _on_next_month(self):
        if self._display_month == 12:
            self._display_month = 1
            self._display_year += 1
        else:
            self._display_month += 1
        target = date(self._display_year, self._display_month, 1)
        if target > date.today():
            return
        self._command.period.set_from_day(target)
        self._command.refresh_all()

    @on(Click, "#cal-grid Label.cal-day")
    def _on_day_clicked(self, event: Click):
        label = event.control
        if label is None or label.id is None or not label.id.startswith("cal-day-"):
            return
        try:
            cell_idx = int(label.id.replace("cal-day-", "", 1))
        except (ValueError, AttributeError):
            return

        first_day = date(self._display_year, self._display_month, 1)
        grid_start = first_day - timedelta(days=first_day.weekday())
        clicked_date = grid_start + timedelta(days=cell_idx)

        if clicked_date > date.today():
            return

        pc = self._command.period
        if pc.mode == PeriodMode.DAY:
            pc.set_from_day(clicked_date)
        elif pc.mode == PeriodMode.WEEK:
            pc.set_from_week(clicked_date)
        else:
            pc.set_from_month(clicked_date)
        self._command.refresh_all()


# ── CommandTab ────────────────────────────────────────────────────────


class CommandTab(Container):
    """Command tab — unified analytics workspace.

    Layout:
      ┌───────────────────────────────────┬──────────────┐
      │ Graph Panel (75%)                 │ Calendar     │
      │  <<< Today >>>                    │ (25%)        │
      │  Day Week Month   7d 30d 90d 365d │              │
      │  Net: x  Best: x  Worst: x  Avg:x │              │
      │  ┌─ Graph ────────────────────────┤              │
      │  └────────────────────────────────┤              │
      │  Traj Pos Neg Log+ Log-            │              │
      ├───────────────────────────────────┴──────────────┤
      │ Category Summary (35%)  │ Daily Breakdown (65%)  │
      └─────────────────────────────────┴────────────────┘
    """

    DEFAULT_CSS = """
    CommandTab {
        layout: vertical;
        height: 1fr;
    }

    /* ── Top section: graph + calendar ────────────────── */
    #cmd-top-section {
        height: 3fr;
    }
    #cmd-graph-panel {
        width: 1fr;
        height: 1fr;
        border: round #3d4f63;
    }
    #cmd-graph-panel:focus-within {
        border: round #63f3ff;
    }
    #cmd-calendar-col {
        width: 25;
        min-width: 23;
        height: 1fr;
    }

    /* ── Graph header (2 rows: nav + period modes) ───── */
    #cmd-graph-header {
        height: auto;
        padding: 0 1;
    }
    #cmd-nav-row {
        height: auto;
        layout: horizontal;
        align: center middle;
    }
    #cmd-nav-row > Button {
        background: transparent;
        border: none;
        min-width: 5;
        color: #8d98a7;
    }
    #cmd-nav-row > Button:hover {
        color: #63f3ff;
        background: #1e2a36;
    }
    #cmd-period-label {
        width: 1fr;
        text-align: center;
        color: #63f3ff;
        text-style: bold;
    }

    #cmd-control-row {
        height: auto;
        layout: horizontal;
        align: center middle;
    }
    .period-mode-btn {
        background: transparent;
        border: none;
        padding: 0 1;
        min-width: 4;
        color: #8d98a7;
    }
    .period-mode-btn:hover {
        color: #63f3ff;
        background: #1e2a36;
    }
    .period-mode-btn.selected {
        color: #63f3ff;
    }
    #cmd-period-sep {
        color: #3d4f63;
        margin: 0 1;
    }

    #cmd-stats-row {
        height: auto;
        padding: 0 2;
        color: #8d98a7;
    }
    #cmd-stats-row > Label {
        width: 1fr;
        text-align: center;
    }
    #cmd-stats-net {
        color: #d7dde8;
        text-style: bold;
    }

    /* ── Graph area ───────────────────────────────────── */
    #cmd-graph-area {
        height: 1fr;
    }

    /* ── Graph footer (mode selector + scale) ────────── */
    #cmd-graph-footer {
        height: auto;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
    }
    #cmd-graph-footer > Label {
        color: #3d4f63;
    }
    .graph-mode-btn {
        background: transparent;
        border: none;
        padding: 0 1;
        color: #8d98a7;
        min-width: 4;
        height: 1;
    }
    .graph-mode-btn:hover {
        color: #d7dde8;
        background: #1e2a36;
    }
    .graph-mode-btn.selected {
        color: #0b1016;
        background: #63f3ff;
        text-style: bold;
    }
    .scale-btn {
        background: transparent;
        border: none;
        padding: 0 1;
        min-width: 4;
        height: 1;
        color: #8d98a7;
    }
    .scale-btn:hover {
        color: #d7dde8;
        background: #1e2a36;
    }
    .scale-btn.selected {
        color: #0b1016;
        background: #63f3ff;
        text-style: bold;
    }
    .scale-btn.hidden {
        display: none;
    }

    /* ── Bottom section: two tables ────────────────────── */
    #cmd-bottom-section {
        height: 1fr;
        min-height: 4;
    }
    #cmd-category-panel {
        width: 35%;
        height: 1fr;
    }
    #cmd-daily-panel {
        width: 1fr;
        height: 1fr;
    }
    #cmd-category-table, #cmd-daily-table {
        height: 1fr;
        border: round #3d4f63;
        background: #0b1016;
    }
    #cmd-category-table:focus-within, #cmd-daily-table:focus-within {
        border: round #63f3ff;
    }
    #cmd-category-table > .datatable--header,
    #cmd-daily-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }
    #cmd-category-table > .datatable--cursor,
    #cmd-daily-table > .datatable--cursor {
        background: #1e2a36;
        color: #d7dde8;
    }
    """

    GRAPH_MODES = ["trajectory", "positive", "negative", "logged_pos", "logged_neg"]
    GRAPH_MODE_LABELS = ["Net", "Pos", "Neg", "Log+", "Log-"]

    PERIOD_MODES = [PeriodMode.DAY, PeriodMode.WEEK, PeriodMode.MONTH]

    def __init__(self, *args, **kwargs):
        super().__init__(id="command-container", *args, **kwargs)
        self.period = PeriodController()
        self._current_graph_mode = "trajectory"

    # ── Compose ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── Top section: graph panel + calendar ──
        with Horizontal(id="cmd-top-section"):
            with Vertical(id="cmd-graph-panel"):
                yield from self._compose_graph_header()
                yield GraphWidget(id="cmd-graph")
                yield from self._compose_graph_footer()
            with Container(id="cmd-calendar-col"):
                yield CalendarWidget(self)

        # ── Bottom section: category + daily tables ──
        with Horizontal(id="cmd-bottom-section"):
            with Container(id="cmd-category-panel"):
                yield DataTable(
                    zebra_stripes=False, cursor_type="row",
                    id="cmd-category-table",
                )
            with Container(id="cmd-daily-panel"):
                yield DataTable(
                    zebra_stripes=False, cursor_type="row",
                    id="cmd-daily-table",
                )

    def _compose_graph_header(self):
        """Yield graph panel header (2 rows: nav + period modes)."""
        with Container(id="cmd-graph-header"):
            # Row 1: navigation
            with Horizontal(id="cmd-nav-row"):
                yield Button("<<<", id="cmd-prev")
                yield Label("...", id="cmd-period-label")
                yield Button(">>>", id="cmd-next")
            # Row 2: period modes
            with Horizontal(id="cmd-control-row"):
                for mode in self.PERIOD_MODES:
                    cls = "period-mode-btn selected" if mode == self.period.mode else "period-mode-btn"
                    yield Button(PeriodMode.label(mode), id=f"cmd-period-{mode}", classes=cls)
            # Row 3: statistics (stacked, NET prominent)
            with Vertical(id="cmd-stats-row"):
                yield Label("", id="cmd-stats-best")
                yield Label("", id="cmd-stats-net")
                yield Label("", id="cmd-stats-worst")
                yield Label("", id="cmd-stats-avg")

    def _compose_graph_footer(self):
        """Yield graph panel footer (mode selector + scale)."""
        with Horizontal(id="cmd-graph-footer"):
            for mode, label in zip(self.GRAPH_MODES, self.GRAPH_MODE_LABELS):
                cls = "graph-mode-btn selected" if mode == self._current_graph_mode else "graph-mode-btn"
                yield Button(label, id=f"cmd-gmode-{mode}", classes=cls)
                if mode != self.GRAPH_MODES[-1]:
                    yield Label("|")
            yield Label("|")
            for scale_val in [7, 30, 90, 365, 4, 13, 26, 52, 3, 6, 12]:
                yield Button(str(scale_val), id=f"cmd-scale-{scale_val}", classes="scale-btn hidden")

    # ── Mount ────────────────────────────────────────────────────────

    def on_mount(self):
        cat = self.query_one("#cmd-category-table", DataTable)
        cat.add_columns("Category", "Hours", "Rate", "Points")
        cat.styles.min_height = 1
        cat.show_cursor = True

        daily = self.query_one("#cmd-daily-table", DataTable)
        daily.add_columns("Day", "Date", "Hours", "Positive", "Negative", "Net")
        daily.styles.min_height = 1
        daily.show_cursor = True

        self.refresh_all()

    # ── Refresh ──────────────────────────────────────────────────────

    def refresh_all(self):
        """Single refresh entry point — graph, calendar, tables, stats, controls."""
        start, end = self.period.get_visible_range()

        from toggl.cache import DataCache
        cache = DataCache.load()
        daily_data = cache.get_daily_data_for_range(start, end)

        # ── Graph data ──────────────────────────────────────────────
        mode_field_map = {
            "trajectory": "net",
            "positive": "positive",
            "negative": "negative",
            "logged_pos": "logged_pos",
            "logged_neg": "logged_neg",
        }
        field = mode_field_map[self._current_graph_mode]
        dates = [d["date"] for d in daily_data]
        raw_values = [d[field] for d in daily_data]

        if self._current_graph_mode == "trajectory":
            values = []
            cum = 0.0
            for v in raw_values:
                cum += v
                values.append(round(cum, 1))
        else:
            values = raw_values

        graph = self.query_one("#cmd-graph", GraphWidget)
        nonzero = [v for v in raw_values if v != 0]
        avg = round(sum(nonzero) / len(nonzero), 1) if nonzero else None
        graph.set_data(dates, values, avg=avg)
        graph.set_mode(self._current_graph_mode)
        graph.refresh()

        # ── Calendar ────────────────────────────────────────────────
        net_map = {d["date"]: d["net"] for d in daily_data}
        cal = self.query_one(CalendarWidget)
        cal.set_day_net_values(net_map)
        cal.rebuild()

        # ── Category table (aggregated over visible range) ──────────
        self._refresh_category_table(cache, start, end)

        # ── Daily breakdown table ───────────────────────────────────
        self._refresh_daily_table(daily_data)

        # ── Statistics ──────────────────────────────────────────────
        self._update_stats(raw_values)

        # ── Controls (rebuild scale buttons on mode change) ──────────
        self._update_controls()

    # ── Category table ───────────────────────────────────────────────

    def _refresh_category_table(self, cache, start, end):
        import toggl.tui as _tui

        agg = cache.get_range_aggregate(start, end)
        table = self.query_one("#cmd-category-table", DataTable)
        table.clear(columns=False)
        table.border_title = "[b][#63f3ff]Category Summary[/][/]"

        rows = []
        for section_name in ("positive", "negative", "unscored"):
            section_rows = agg[section_name]
            if section_rows:
                rows.append((_tui._fmt_section_header(f"• {section_name.upper()}"),
                             Text(""), Text(""), Text("")))
            rows.extend(
                _tui._render_category_section(
                    section_rows, _tui._fmt_project_tree, _tui._fmt_tree_cells,
                    section_color=_tui.SECTION_COLORS.get(section_name.upper(), ""),
                )
            )

        if agg["positive_results"]:
            rows.append((_tui._fmt_section_header("• LOGGED POSITIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(agg["positive_results"]):
                prefix = "└ " if i == len(agg["positive_results"]) - 1 else "├ "
                rows.append((
                    Text.assemble((prefix, _tui.SECTION_COLORS["LOGGED POSITIVE"]), (name, "")),
                    Text(f"×{count}"), _tui.fmt_pts_rich(per_event), _tui.fmt_pts_rich(total),
                ))

        if agg["negative_results"]:
            rows.append((_tui._fmt_section_header("• LOGGED NEGATIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(agg["negative_results"]):
                prefix = "└ " if i == len(agg["negative_results"]) - 1 else "├ "
                rows.append((
                    Text.assemble((prefix, _tui.SECTION_COLORS["LOGGED NEGATIVE"]), (name, "")),
                    Text(f"×{count}"), _tui.fmt_pts_rich(per_event), _tui.fmt_pts_rich(total),
                ))

        table.add_rows(rows)

    # ── Daily breakdown table ────────────────────────────────────────

    def _refresh_daily_table(self, daily_data):
        import toggl.tui as _tui
        from rich.text import Text as RichText

        table = self.query_one("#cmd-daily-table", DataTable)
        table.clear(columns=False)
        table.border_title = "[b][#63f3ff]Daily Breakdown[/][/]"

        for day in daily_data:
            d_str = day["date"]
            try:
                d = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            day_name = d.strftime("%a")
            date_short = d.strftime("%d %b")
            hours = day["total_hours"]
            positive = day["positive"]
            negative = day["negative"]
            net = day["net"]
            has_data = day["has_data"]
            is_today = d == date.today()

            if is_today:
                day_cell = f"[bold #e2b714]{day_name} ◀[/]"
            elif not has_data:
                day_cell = f"[dim]{day_name}[/]"
            else:
                day_cell = day_name

            hour_text = "—" if hours == 0 else f"{hours:.1f}h"
            pos_text = "—" if positive == 0 else f"[#37d994]+{positive:.1f}[/]"
            neg_text = "—" if negative == 0 else f"[#ff5f5f]-{negative:.1f}[/]"

            table.add_row(
                RichText.from_markup(day_cell),
                date_short,
                hour_text,
                RichText.from_markup(pos_text),
                RichText.from_markup(neg_text),
                _tui.format_signed_rich(net),
                key=d_str,
            )

    # ── Statistics ────────────────────────────────────────────────────

    def _update_stats(self, raw_values):
        nonzero = [v for v in raw_values if v != 0]
        if nonzero:
            t, b, w, a = round(sum(raw_values), 1), max(nonzero), min(nonzero), round(sum(nonzero) / len(nonzero), 1)
            for lid, text in [("#cmd-stats-best", f"[#8d98a7]BEST[/] [#37d994]+{int(b)}[/]"),
                               ("#cmd-stats-net",  f"[#d7dde8]NET  {t:+.0f}[/]"),
                               ("#cmd-stats-worst", f"[#8d98a7]WORST[/] [#ff5f5f]{int(w)}[/]"),
                               ("#cmd-stats-avg",  f"[#8d98a7]AVG[/] {a:+.0f}")]:
                self.query_one(lid, Label).update(text)
        else:
            for lid in ("#cmd-stats-best", "#cmd-stats-net", "#cmd-stats-worst", "#cmd-stats-avg"):
                try: self.query_one(lid, Label).update("")
                except Exception: pass

        # Graph panel title shows date range
        start, end = self.period.get_visible_range()
        if start == end:
            date_title = start.strftime("%d %b %Y")
        elif end - start > timedelta(days=180):
            date_title = f"{start.strftime('%b %Y')} → {end.strftime('%b %Y')}"
        else:
            date_title = f"{start.strftime('%d %b')} → {end.strftime('%d %b')}"
        self.query_one("#cmd-graph-panel").border_title = f"[b][#63f3ff]{date_title}[/][/]"

    # ── Controls ─────────────────────────────────────────────────────

    def _update_controls(self):
        self.query_one("#cmd-period-label", Label).update(self.period.get_period_label())
        self._show_scale_buttons()
        self._highlight_selected_buttons()

    def _show_scale_buttons(self):
        """Show only scale buttons valid for the current mode, hide the rest.
        Also updates button labels to match current mode's scale labels."""
        active_scales = set(self.period.scales)
        for btn in self.query(".scale-btn"):
            try:
                scale_val = int(btn.id.replace("cmd-scale-", ""))
            except (ValueError, AttributeError):
                continue
            if scale_val in active_scales:
                btn.remove_class("hidden")
                # Update label to show proper scale label for current mode
                btn.label = PeriodController._SCALE_LABELS.get(
                    self.period.mode, {}).get(scale_val, str(scale_val))
            else:
                btn.add_class("hidden")

    def _highlight_selected_buttons(self):
        """Set .selected class on active period mode and scale buttons."""
        for btn in self.query(".period-mode-btn"):
            btn.set_class(btn.id == f"cmd-period-{self.period.mode}", "selected")
        for btn in self.query(".scale-btn"):
            try:
                scale_val = int(btn.id.replace("cmd-scale-", ""))
                btn.set_class(scale_val == self.period.scale, "selected")
            except (ValueError, AttributeError):
                pass

    # ── Event handlers ───────────────────────────────────────────────

    @on(Button.Pressed, "#cmd-prev")
    def _on_prev(self):
        self.period.previous()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-next")
    def _on_next(self):
        self.period.next()
        self.refresh_all()

    @on(Button.Pressed, ".period-mode-btn")
    def _on_period_mode(self, event: Button.Pressed):
        mode = event.button.id.replace("cmd-period-", "")
        self.period.mode = mode
        self.refresh_all()

    @on(Button.Pressed, ".scale-btn")
    def _on_scale(self, event: Button.Pressed):
        try:
            scale_val = int(event.button.id.replace("cmd-scale-", ""))
            self.period.set_scale(scale_val)
            self.refresh_all()
        except (ValueError, AttributeError):
            pass

    @on(Button.Pressed, ".graph-mode-btn")
    def _on_graph_mode(self, event: Button.Pressed):
        mode = event.button.id.replace("cmd-gmode-", "")
        if mode not in self.GRAPH_MODES:
            return
        self._current_graph_mode = mode
        for btn in self.query(".graph-mode-btn"):
            btn.set_class(btn.id == f"cmd-gmode-{mode}", "selected")
        self.refresh_all()
