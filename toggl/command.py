"""Command tab — trajectory analytics view.

CalendarWidget: month-grid calendar sidebar (adapted from Bagels' DateMode).
  - Day cells are colored green/red based on net daily points.
CommandTab: main container with top bar, graph, calendar, and mode selector.
  - Trajectory mode renders cumulative daily net (running total).
  - Category breakdown table below the graph (aggregated across visible range).
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


# ── Color helpers for calendar cells ────────────────────────────────

def _net_color(value: float) -> str:
    """Return a Rich color tag for a net value."""
    if value > 0:
        return "#37d994"
    if value < 0:
        return "#ff5f5f"
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
    """Return Rich markup for a calendar day cell."""
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
    """Return all dates in the calendar week containing *anchor*."""
    monday = anchor - timedelta(days=anchor.weekday())
    return {monday + timedelta(days=i) for i in range(7)}


# ── CalendarWidget ───────────────────────────────────────────────────


class CalendarWidget(Static):
    """Month-grid calendar sidebar.

    - Day cells colored green/red based on daily net points.
    - Click navigates graph (Day→day, Week→containing week).
    """

    DEFAULT_CSS = """
    CalendarWidget {
        width: 24;
        min-width: 20;
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
        anchor_week = _get_anchor_week_dates(anchor) if pc.mode == PeriodMode.WEEK else None

        self.query_one("#cal-month-label", Label).update(
            first_day.strftime("%B %Y")
        )

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
        else:
            pc.set_from_week(clicked_date)
        self._command.refresh_all()


# ── CommandTab ────────────────────────────────────────────────────────


class CommandTab(Container):
    """Main Command tab container.

    Layout:
      Top bar: nav arrows + period label + Day/Week toggle + zoom
      Summary: Net / Best / Worst / Avg
      Main area:
        Left: Graph (fills space) + Category breakdown table (below)
        Right: Calendar (24 cols)
      Bottom bar: graph mode selector
    """

    DEFAULT_CSS = """
    CommandTab {
        height: 1fr;
    }

    /* ── Top bar ───────────────────────────────────────── */
    #cmd-top-bar {
        height: auto;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
    }
    #cmd-top-bar > Button {
        background: transparent;
        border: none;
        min-width: 5;
        color: #8d98a7;
    }
    #cmd-top-bar > Button:hover {
        color: #63f3ff;
        background: #1e2a36;
    }
    #cmd-period-label {
        width: 1fr;
        text-align: center;
        color: #63f3ff;
        text-style: bold;
    }
    #cmd-scale-label {
        min-width: 5;
        text-align: center;
        color: #e2b714;
        text-style: bold;
    }

    /* ── Summary ───────────────────────────────────────── */
    #cmd-summary {
        height: auto;
        text-align: center;
        color: #8d98a7;
        margin: 0 1;
    }

    /* ── Main area ─────────────────────────────────────── */
    #cmd-main {
        height: 1fr;
    }
    #cmd-left-stack {
        width: 1fr;
        height: 1fr;
    }

    /* Graph wrapper — provides the border around the plot */
    #cmd-graph-wrapper {
        height: 1fr;
        border: round #3d4f63;
    }
    #cmd-graph-wrapper:focus,
    #cmd-graph-wrapper:focus-within {
        border: round #63f3ff;
    }

    /* ── Category table (below graph) ──────────────────── */
    #cmd-category-table {
        height: auto;
        max-height: 12;
        border: round #3d4f63;
        background: #0b1016;
    }
    #cmd-category-table:focus,
    #cmd-category-table:focus-within {
        border: round #63f3ff;
    }
    #cmd-category-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }
    #cmd-category-table > .datatable--cursor {
        background: #1e2a36;
        color: #d7dde8;
    }

    /* ── Daily breakdown table ──────────────────────────── */
    #cmd-daily-table {
        height: auto;
        max-height: 10;
        border: round #3d4f63;
        background: #0b1016;
    }
    #cmd-daily-table:focus,
    #cmd-daily-table:focus-within {
        border: round #63f3ff;
    }
    #cmd-daily-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }
    #cmd-daily-table > .datatable--cursor {
        background: #1e2a36;
        color: #d7dde8;
    }

    /* ── Bottom bar ────────────────────────────────────── */
    #cmd-bottom-bar {
        height: auto;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
    }
    #cmd-bottom-bar > Label {
        color: #3d4f63;
    }
    .mode-btn {
        background: transparent;
        border: none;
        padding: 0 1;
        color: #8d98a7;
        min-width: 10;
    }
    .mode-btn:hover {
        color: #d7dde8;
        background: #1e2a36;
    }
    .mode-btn.selected {
        color: #63f3ff;
        text-style: bold;
    }
    """

    GRAPH_MODES = ["trajectory", "positive", "negative", "logged_pos", "logged_neg"]
    MODE_LABELS = ["Trajectory", "Positive", "Negative", "Logged Pos", "Logged Neg"]

    def __init__(self, *args, **kwargs):
        super().__init__(id="command-container", *args, **kwargs)
        self.period = PeriodController()
        self._current_graph_mode = "trajectory"

    def compose(self) -> ComposeResult:
        # ── Top bar ──
        with Horizontal(id="cmd-top-bar"):
            yield Button("<<<", id="cmd-prev")
            yield Label("...", id="cmd-period-label")
            yield Button(">>>", id="cmd-next")
            yield Button("Day", id="cmd-mode-toggle")
            yield Button("+", id="cmd-zoom-in")
            yield Label("7d", id="cmd-scale-label")
            yield Button("-", id="cmd-zoom-out")

        # ── Summary label ──
        yield Label("", id="cmd-summary")

        # ── Main area: left stack (graph + table) | calendar ──
        with Horizontal(id="cmd-main"):
            with Container(id="cmd-left-stack"):
                with Container(id="cmd-graph-wrapper"):
                    yield GraphWidget(id="cmd-graph")
                yield DataTable(
                    zebra_stripes=False,
                    cursor_type="row",
                    id="cmd-category-table",
                )
                yield DataTable(
                    zebra_stripes=False,
                    cursor_type="row",
                    id="cmd-daily-table",
                )
            yield CalendarWidget(self)

        # ── Bottom bar ──
        with Horizontal(id="cmd-bottom-bar"):
            for mode, label in zip(self.GRAPH_MODES, self.MODE_LABELS):
                cls = "mode-btn selected" if mode == self._current_graph_mode else "mode-btn"
                yield Button(label, id=f"mode-{mode}", classes=cls)
                if mode != self.GRAPH_MODES[-1]:
                    yield Label("|")

    def on_mount(self):
        # Category table
        table = self.query_one("#cmd-category-table", DataTable)
        table.add_columns("Category", "Hours", "Rate", "Points")
        table.styles.min_height = 1
        table.show_cursor = True
        # Daily breakdown table
        daily = self.query_one("#cmd-daily-table", DataTable)
        daily.add_columns("Day", "Date", "Hours", "Earned", "Pos", "Negs", "Net")
        daily.styles.min_height = 1
        daily.show_cursor = True
        self.refresh_all()

    # ── Refresh ──────────────────────────────────────────────────────

    def refresh_all(self):
        """Refresh the graph, calendar, category table, controls, and summary."""
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
        graph.set_data(dates, values)
        graph.set_mode(self._current_graph_mode)
        graph.refresh()

        # ── Calendar ────────────────────────────────────────────────
        net_map = {d["date"]: d["net"] for d in daily_data}
        cal = self.query_one(CalendarWidget)
        cal.set_day_net_values(net_map)
        cal.rebuild()

        # ── Category breakdown table ────────────────────────────────
        self._refresh_category_table(cache, start, end)

        # ── Daily breakdown table ───────────────────────────────────
        self._refresh_daily_table(daily_data)

        # ── Summary ─────────────────────────────────────────────────
        self._update_summary(raw_values)

        # ── Controls ────────────────────────────────────────────────
        self._update_controls()

    def _refresh_category_table(self, cache, start, end):
        """Populate the category breakdown table below the graph."""
        import toggl.tui as _tui  # lazy import to avoid circular dep

        agg = cache.get_range_aggregate(start, end)
        table = self.query_one("#cmd-category-table", DataTable)
        table.clear(columns=False)

        rows = []
        for section_name in ("positive", "negative", "unscored"):
            section_rows = agg[section_name]
            section_key = section_name.upper()
            section_color = _tui.SECTION_COLORS.get(section_key, "")
            if section_rows:
                rows.append(
                    (_tui._fmt_section_header(f"• {section_key}"),
                     Text(""), Text(""), Text(""))
                )
            rows.extend(
                _tui._render_category_section(
                    section_rows, _tui._fmt_project_tree, _tui._fmt_tree_cells,
                    section_color=section_color,
                )
            )

        if agg["positive_results"]:
            rows.append((_tui._fmt_section_header("• LOGGED POSITIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(agg["positive_results"]):
                is_last = (i == len(agg["positive_results"]) - 1)
                prefix = "└ " if is_last else "├ "
                rows.append((
                    Text.assemble(
                        (prefix, _tui.SECTION_COLORS["LOGGED POSITIVE"]),
                        (name, ""),
                    ),
                    Text(f"×{count}"),
                    _tui.fmt_pts_rich(per_event),
                    _tui.fmt_pts_rich(total),
                ))

        if agg["negative_results"]:
            rows.append((_tui._fmt_section_header("• LOGGED NEGATIVE"), Text(""), Text(""), Text("")))
            for i, (name, count, per_event, total) in enumerate(agg["negative_results"]):
                is_last = (i == len(agg["negative_results"]) - 1)
                prefix = "└ " if is_last else "├ "
                rows.append((
                    Text.assemble(
                        (prefix, _tui.SECTION_COLORS["LOGGED NEGATIVE"]),
                        (name, ""),
                    ),
                    Text(f"×{count}"),
                    _tui.fmt_pts_rich(per_event),
                    _tui.fmt_pts_rich(total),
                ))

        table.add_rows(rows)

    def _refresh_daily_table(self, daily_data):
        """Populate the daily breakdown table (like Week view's per-day table)."""
        import toggl.tui as _tui

        table = self.query_one("#cmd-daily-table", DataTable)
        table.clear(columns=False)

        for day in daily_data:
            d_str = day["date"]
            try:
                d = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            day_name = d.strftime("%a")
            date_short = d.strftime("%d %b")
            hours = day["total_hours"]
            earned = day["earned"]
            pos_total = day["positive"]
            neg_total = day["negative"]
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
            earned_text = "—" if earned == 0 and not has_data else _tui.format_signed_rich(earned)
            pos_text = "—" if pos_total == 0 else f"[#37d994]+{pos_total:.1f}[/]"
            neg_text = "—" if neg_total == 0 else f"[#ff5f5f]-{neg_total:.1f}[/]"

            from rich.text import Text as RichText
            table.add_row(
                RichText.from_markup(day_cell),
                date_short,
                hour_text,
                RichText.from_markup(earned_text) if isinstance(earned_text, str) else earned_text,
                RichText.from_markup(pos_text),
                RichText.from_markup(neg_text),
                RichText.from_markup(_tui.format_signed_rich(net)),
                key=d_str,
            )

    def _update_summary(self, raw_values):
        nonzero = [v for v in raw_values if v != 0]
        if nonzero:
            total = round(sum(raw_values), 1)
            best = max(nonzero)
            worst = min(nonzero)
            avg = round(sum(nonzero) / len(nonzero), 1)

            def _fs(v: float) -> str:
                return f"+{v}" if v > 0 else str(v)

            self.query_one("#cmd-summary", Label).update(
                f"[#8d98a7]Net:[/] [#37d994]{_fs(total)}[/]  "
                f"[#8d98a7]Best:[/] [#37d994]+{best:.0f}[/]  "
                f"[#8d98a7]Worst:[/] [#ff5f5f]{worst:.0f}[/]  "
                f"[#8d98a7]Avg:[/] {_fs(avg)}"
            )
        else:
            self.query_one("#cmd-summary", Label).update("[dim]No data in range[/]")

    def _update_controls(self):
        self.query_one("#cmd-period-label", Label).update(
            self.period.get_period_label()
        )
        self.query_one("#cmd-scale-label", Label).update(
            self.period.scale_label
        )
        mode_btn = self.query_one("#cmd-mode-toggle", Button)
        mode_btn.label = "Day" if self.period.mode == PeriodMode.DAY else "Week"

    # ── Event handlers ───────────────────────────────────────────────

    @on(Button.Pressed, "#cmd-prev")
    def _on_prev(self):
        self.period.previous()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-next")
    def _on_next(self):
        self.period.next()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-zoom-in")
    def _on_zoom_in(self):
        self.period.zoom_in()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-zoom-out")
    def _on_zoom_out(self):
        self.period.zoom_out()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-mode-toggle")
    def _on_mode_toggle(self):
        new_mode = PeriodMode.WEEK if self.period.mode == PeriodMode.DAY else PeriodMode.DAY
        self.period.mode = new_mode
        self.refresh_all()

    @on(Button.Pressed, ".mode-btn")
    def _on_graph_mode(self, event: Button.Pressed):
        btn_id = event.button.id
        mode = btn_id.replace("mode-", "", 1)
        if mode not in self.GRAPH_MODES:
            return
        self._current_graph_mode = mode
        for btn in self.query(".mode-btn"):
            btn.remove_class("selected")
        event.button.add_class("selected")
        self.refresh_all()
