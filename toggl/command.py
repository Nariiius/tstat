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

from toggl.cache import get_week_str
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
    anchor: date,
    anchor_week_set: set[date] | None,
    mode: str,
    display_month: int,
    display_year: int,
    net: float,
) -> str:
    """Return Rich markup for a calendar day cell with heatmap coloring."""
    bg = _net_color(net)
    label = f"{d.day:>2}"
    if bg:
        label = f"[{bg}]{label}[/]"

    # Determine if 'd' is in the "current real-world period"
    is_current_period = False
    if mode == "day":
        is_current_period = (d == today)
    elif mode == "week":
        is_current_period = (d.isocalendar()[:2] == today.isocalendar()[:2])
    elif mode == "month":
        is_current_period = (d.month == today.month and d.year == today.year)

    # 1. Base style for selected anchors (reverted to original behavior)
    style = ""
    if d == anchor and d == today:
        style = "bold #e2b714"
    elif d == today:
        style = "bold #e2b714"
    elif d == anchor:
        style = "bold #63f3ff"
    elif anchor_week_set and d in anchor_week_set:
        style = "#63f3ff"
    elif d.month != display_month or d.year != display_year:
        style = "dim #4a5568"

    # 2. Add the background highlight if it's the real-world current period
    if is_current_period:
        if style:
            style += " on #1e2a36"
        else:
            style = "on #1e2a36"

    # 3. Apply the fallback background for today-anchor if not handled
    if d == anchor and d == today and not is_current_period:
        style += " on #1e2a36"

    if style:
        label = f"[{style}]{label}[/]"
        
    return label

def _get_anchor_week_dates(anchor: date) -> set[date]:
    sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    return {sunday + timedelta(days=i) for i in range(7)}


# ── CalendarWidget ───────────────────────────────────────────────────


class CalendarWidget(Static):
    """Month-grid calendar sidebar with net-based heatmap coloring."""

    can_focus = True

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
    .cal-row > .cal-dotw {
        width: 3;
        text-align: center;
        color: #8d98a7;
        text-style: bold;
    }
    .cal-day {
        color: #d7dde8;
    }
    .cal-row > .cal-week-num {
        width: 2;
        text-align: right;
        margin-right: 1;
        color: #3d4f63;
        text-style: bold;
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
        day_names = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
        with Container(id="cal-nav"):
            yield Button("<<", id="cal-prev-month")
            yield Label("", id="cal-month-label")
            yield Button(">>", id="cal-next-month")
        with Container(id="cal-grid"):
            with Horizontal(classes="cal-row"):
                yield Label("", classes="cal-week-num")
                for dn in day_names:
                    yield Label(dn, classes="cal-dotw")
            for row_idx in range(6):
                with Horizontal(classes="cal-row"):
                    yield Label("", id=f"cal-week-{row_idx}", classes="cal-week-num")
                    for col_idx in range(7):
                        cell_idx = row_idx * 7 + col_idx
                        yield Label("", id=f"cal-day-{cell_idx}", classes="cal-day")

    def rebuild(self):
        pc = self._command.period
        anchor = pc.get_anchor_date()
        self._display_year = anchor.year
        self._display_month = anchor.month

        first_day = date(self._display_year, self._display_month, 1)
        grid_start = first_day - timedelta(days=(first_day.weekday() + 1) % 7)

        today = date.today()
        anchor_week = _get_anchor_week_dates(anchor) if pc.mode in (PeriodMode.WEEK,) else None

        self.query_one("#cal-month-label", Label).update(first_day.strftime("%B %Y"))

        for row_idx in range(6):
            row_start_date = grid_start + timedelta(days=row_idx * 7)
            week_num = int(get_week_str(row_start_date).split("W")[1])
            self.query_one(f"#cal-week-{row_idx}", Label).update(str(week_num))

        for i in range(42):
            label = self.query_one(f"#cal-day-{i}", Label)
            day_date = grid_start + timedelta(days=i)
            d_str = day_date.strftime("%Y-%m-%d")
            net = self._day_nets.get(d_str, 0.0)
            markup = _label_for_day(
                day_date, today, anchor, anchor_week, pc.mode,
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
        grid_start = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
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

    def on_click(self, event) -> None:
        """Focus the calendar when clicked anywhere."""
        self.focus()


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
        height: 1fr;
        min-height: 10;
        max-height: 16;
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
        width: 27;
        min-width: 27;
        height: 1fr;
    }

    /* ── Graph header (L1.controls) ── */
    #cmd-graph-header {
        height: 1;
        padding: 0 1;
    }
    #cmd-l1-controls {
        height: 1;
        layout: horizontal;
        align: center middle;
    }
    .nav-btn {
        background: #0b1016;
        border: none;
        min-width: 5;
        height: 1;
        color: #8d98a7;
    }
    .nav-btn:hover {
        color: #63f3ff;
        background: #1e2a36;
        border: none;
    }
    #cmd-period-label {
        width: 1fr;
        text-align: center;
        color: #63f3ff;
        text-style: bold;
    }
    .cycle-btn {
        background: #0b1016;
        border: none;
        padding: 0;
        min-width: 4;
        height: 1;
        color: #63f3ff;
        text-style: bold;
    }
    .cycle-btn:hover {
        color: #63f3ff;
        background: #1e2a36;
        border: none;
    }
    .cmd-period-sep {
        color: #3d4f63;
        margin: 0;
    }

    /* ── Graph area ───────────────────────────────────── */
    #cmd-graph-area {
        height: 1fr;
    }

    /* ── Bottom section: two tables ────────────────────── */
    #cmd-bottom-section {
        height: 2fr;
        min-height: 10;
    }
    #cmd-category-panel {
        width: 55%;
        height: 1fr;
    }
    #cmd-daily-panel {
        width: 45%;
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

    GRAPH_MODES = ["net", "positive", "negative"]
    GRAPH_MODE_LABELS = ["Net", "Pos", "Neg"]

    PERIOD_MODES = [PeriodMode.DAY, PeriodMode.WEEK, PeriodMode.MONTH]

    def __init__(self, *args, **kwargs):
        super().__init__(id="command-container", *args, **kwargs)
        self.period = PeriodController()
        self._current_graph_mode = "net"

    # ── Compose ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── Top section: graph panel + calendar ──
        with Horizontal(id="cmd-top-section"):
            with Vertical(id="cmd-graph-panel"):
                yield from self._compose_graph_header()
                yield GraphWidget(id="cmd-graph")
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
        """Yield graph panel header (L1.controls)."""
        with Container(id="cmd-graph-header"):
            # Row 1: L1.controls
            with Horizontal(id="cmd-l1-controls"):
                yield Button("<<<", id="cmd-prev", classes="nav-btn")
                yield Label("...", id="cmd-period-label")
                yield Button(">>>", id="cmd-next", classes="nav-btn")
                yield Label("|", classes="cmd-period-sep")
                yield Button("View: Day ↻", id="cmd-cycle-period", classes="cycle-btn")
                yield Label("|", classes="cmd-period-sep")
                yield Button("Range: 7d ↻", id="cmd-cycle-scale", classes="cycle-btn")
                yield Label("|", classes="cmd-period-sep")
                yield Button("Metric: Net ↻", id="cmd-cycle-metric", classes="cycle-btn")

    # ── Mount ────────────────────────────────────────────────────────

    def on_mount(self):
        cat = self.query_one("#cmd-category-table", DataTable)
        cat.add_columns("Category", "Hours", "Rate", "Points")
        cat.styles.min_height = 1
        cat.show_cursor = True

        daily = self.query_one("#cmd-daily-table", DataTable)
        daily.add_columns("Date", "Positive", "Negative", "Net")
        daily.styles.min_height = 1
        daily.show_cursor = True

        self.refresh_all()

    # ── Refresh ──────────────────────────────────────────────────────

    def refresh_all(self):
        """Single refresh entry point — graph, calendar, tables, stats, controls."""
        start, end = self.period.get_visible_range()
        base_start, base_end = self.period.get_base_range()

        from toggl.cache import DataCache
        cache = DataCache.load()
        daily_data = cache.get_daily_data_for_range(start, end)
        base_daily_data = cache.get_daily_data_for_range(base_start, base_end)

        # ── Graph data ──────────────────────────────────────────────
        mode_field_map = {
            "net": "net",
            "positive": "positive",
            "negative": "negative",
        }
        field = mode_field_map[self._current_graph_mode]
        dates = [d["date"] for d in daily_data]
        raw_values = [d[field] for d in daily_data]

        if self._current_graph_mode == "net":
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

        # ── Category table (aggregated over base range) ──────────
        self._refresh_category_table(cache, base_start, base_end)

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

        mode = self.period.mode
        if mode == "day":
            suffix = start.strftime("%a %-d %b")
        elif mode == "week":
            wk = get_week_str(start)
            suffix = f"W{int(wk.split('W')[1])} {start.year}"
        else:
            suffix = start.strftime("%b %Y")

        table.border_title = f"[b][#63f3ff]{suffix}[/][/]"

        def _fmt(val):
            if val > 0: return f"[#37d994]+{val:.1f}[/]"
            elif val < 0: return f"[#ff5f5f]{val:.1f}[/]"
            else: return "[dim]0.0[/]"

        def _compute_net(start_d, end_d):
            total = 0.0
            for d in cache.get_daily_data_for_range(start_d, end_d):
                if d["has_data"]:
                    total += d["net"]
            return total

        from datetime import timedelta, date
        if mode == "day":
            daily_net = _compute_net(start, start)
            monday = start - timedelta(days=start.weekday())
            sunday = monday + timedelta(days=6)
            weekly_net = _compute_net(monday, sunday)
            subtitle = f"Daily Net: {_fmt(daily_net)}   Weekly Net: {_fmt(weekly_net)}"
        elif mode == "week":
            weekly_net = _compute_net(start, end)
            first_day = date(start.year, start.month, 1)
            next_month = first_day.replace(day=28) + timedelta(days=4)
            last_day = next_month - timedelta(days=next_month.day)
            monthly_net = _compute_net(first_day, last_day)
            subtitle = f"Weekly Net: {_fmt(weekly_net)}   Monthly Net: {_fmt(monthly_net)}"
        else:
            subtitle = "Insights coming soon"

        table.border_subtitle = f"[#8d98a7]{subtitle}[/]"

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
        from datetime import date, timedelta

        table = self.query_one("#cmd-daily-table", DataTable)
        table.clear(columns=False)
        
        title_map = {"day": "Daily", "week": "Weekly", "month": "Monthly"}
        title_word = title_map.get(self.period.mode, "Daily")
        table.border_title = f"[b][#63f3ff]{title_word} Breakdown[/][/]"

        aggregated = []
        if self.period.mode == "week":
            current_group = None
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except:
                    continue
                sunday = d - timedelta(days=(d.weekday() + 1) % 7)
                if current_group is None or current_group["start_date"] != sunday:
                    wk_num = int(get_week_str(sunday).split("W")[1])
                    current_group = {
                        "start_date": sunday,
                        "label": f"Wk {wk_num}",
                        "positive": 0.0,
                        "negative": 0.0,
                        "net": 0.0,
                        "has_data": False,
                        "contains_today": False,
                    }
                    aggregated.append(current_group)
                
                current_group["positive"] += day["positive"]
                current_group["negative"] += day["negative"]
                current_group["net"] += day["net"]
                if day["has_data"]: current_group["has_data"] = True
                if d == date.today(): current_group["contains_today"] = True

        elif self.period.mode == "month":
            current_group = None
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except:
                    continue
                month_key = (d.year, d.month)
                if current_group is None or current_group["month_key"] != month_key:
                    current_group = {
                        "month_key": month_key,
                        "label": d.strftime('%b %Y'),
                        "positive": 0.0,
                        "negative": 0.0,
                        "net": 0.0,
                        "has_data": False,
                        "contains_today": False,
                    }
                    aggregated.append(current_group)
                
                current_group["positive"] += day["positive"]
                current_group["negative"] += day["negative"]
                current_group["net"] += day["net"]
                if day["has_data"]: current_group["has_data"] = True
                if d == date.today(): current_group["contains_today"] = True

        else:
            for day in daily_data:
                try:
                    d = date.fromisoformat(day["date"])
                except:
                    continue
                aggregated.append({
                    "label": f"{d.strftime('%a')} {d.strftime('%d %b')}",
                    "positive": day["positive"],
                    "negative": day["negative"],
                    "net": day["net"],
                    "has_data": day["has_data"],
                    "contains_today": d == date.today(),
                })

        aggregated.reverse()

        for i, item in enumerate(aggregated):
            positive = item["positive"]
            negative = item["negative"]
            net = item["net"]
            has_data = item["has_data"]
            is_today = item["contains_today"]
            label = item["label"]

            if is_today:
                date_cell = f"[bold #e2b714]{label} ◀[/]"
            elif not has_data:
                date_cell = f"[dim]{label}[/]"
            else:
                date_cell = label

            pos_text = "—" if positive == 0 else f"[#37d994]+{positive:.1f}[/]"
            neg_text = "—" if negative == 0 else f"[#ff5f5f]-{negative:.1f}[/]"

            table.add_row(
                RichText.from_markup(date_cell),
                RichText.from_markup(pos_text),
                RichText.from_markup(neg_text),
                _tui.format_signed_rich(net),
                key=str(i),
            )

    # ── Statistics ────────────────────────────────────────────────────

    def _update_stats(self, raw_values):
        nonzero = [v for v in raw_values if v != 0]
        panel = self.query_one("#cmd-graph-panel")
        if nonzero:
            t, b, w = round(sum(raw_values), 1), max(nonzero), min(nonzero)
            high_str = f"+{int(b)}" if b >= 0 else str(int(b))
            low_str = f"+{int(w)}" if w >= 0 else str(int(w))
            
            t_color = "#37d994" if t > 0 else ("#ff5f5f" if t < 0 else "")
            t_markup = f"[{t_color}]{t:+.0f}[/]" if t_color else f"{t:+.0f}"
            
            text = f"HIGH [bold #37d994]{high_str}[/]   LOW [bold #ff5f5f]{low_str}[/]   NET [bold]{t_markup}[/]"
            panel.border_subtitle = text
        else:
            panel.border_subtitle = ""

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
        """Update the L1 labels, controls, and cycle buttons."""
        lbl = self.query_one("#cmd-period-label", Label)
        lbl.update(self.period.get_period_label())
        self._update_cycle_labels()

    def _update_cycle_labels(self):
        """Update cycle button labels based on the current state."""
        from toggl.period import PeriodMode
        period_btn = self.query_one("#cmd-cycle-period", Button)
        period_btn.label = f"View: {PeriodMode.label(self.period.mode)} ↻"

        metric_btn = self.query_one("#cmd-cycle-metric", Button)
        metric_label = self.GRAPH_MODE_LABELS[self.GRAPH_MODES.index(self._current_graph_mode)]
        metric_btn.label = f"Metric: {metric_label} ↻"

        scale_btn = self.query_one("#cmd-cycle-scale", Button)
        scale_btn.label = f"Range: {self.period.scale_label} ↻"


    # ── Event handlers ───────────────────────────────────────────────

    @on(Button.Pressed, "#cmd-prev")
    def _on_prev(self):
        self.period.previous()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-next")
    def _on_next(self):
        self.period.next()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-period")
    def _on_cycle_period(self, event: Button.Pressed):
        modes = self.PERIOD_MODES
        current_idx = modes.index(self.period.mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        self.period.mode = next_mode
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-metric")
    def _on_cycle_metric(self, event: Button.Pressed):
        modes = self.GRAPH_MODES
        current_idx = modes.index(self._current_graph_mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        self._current_graph_mode = next_mode
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-scale")
    def _on_cycle_scale(self, event: Button.Pressed):
        current_idx = self.period.scale_index
        max_idx = self.period.scale_count - 1
        if current_idx >= max_idx:
            self.period.scale_index = 0
        else:
            self.period.scale_index = current_idx + 1
        self.refresh_all()

