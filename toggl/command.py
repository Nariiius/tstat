"""Command tab — trajectory analytics workspace.

CalendarWidget: month-grid calendar sidebar with heatmap coloring.
CommandTab: unified analytics layout.
  Top section: Graph panel (75%) + Calendar (25%)
  Bottom section: Category Summary (35%) + Daily Breakdown (65%)
"""

from __future__ import annotations

from datetime import date, timedelta

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Label


from toggl.state.period import PeriodController, PeriodMode
from toggl.widgets.calendar import CalendarWidget
from toggl.widgets.graph import GraphWidget
from toggl.widgets.tables import CategoryTable, DailyBreakdownTable


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

    BINDINGS = [
        Binding("left", "cmd_previous", "Previous", show=False),
        Binding("right", "cmd_next", "Next", show=False),
    ]

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(id="command-container", *args, **kwargs)
        self.period = PeriodController()
        self._current_graph_mode = "net"
        self.data_cache = None
        self.metrics = None

    # ── Compose ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── Top section: graph panel + calendar ──
        with Horizontal(id="cmd-top-section"):
            with Vertical(id="cmd-graph-panel"):
                yield from self._compose_graph_header()
                yield GraphWidget(id="cmd-graph")
            with Container(id="cmd-calendar-col"):
                yield CalendarWidget()

        # ── Bottom section: category + daily tables ──
        with Horizontal(id="cmd-bottom-section"):
            with Container(id="cmd-category-panel"):
                yield CategoryTable(zebra_stripes=False, cursor_type="row")
            with Container(id="cmd-daily-panel"):
                yield DailyBreakdownTable(zebra_stripes=False, cursor_type="row")

    def _compose_graph_header(self) -> ComposeResult:
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

    # ── Refresh ──────────────────────────────────────────────────────

    def refresh_all(self) -> None:
        """Single refresh entry point — graph, calendar, tables, stats, controls."""
        start, end = self.period.get_visible_range()
        base_start, base_end = self.period.get_base_range()

        cache = self.data_cache
        svc = self.metrics
        daily_data = svc.get_daily_data_for_range(start, end)
        base_daily_data = svc.get_daily_data_for_range(base_start, base_end)

        # ── Graph data (visible window, lifetime-scale Y values) ────
        baseline = svc.get_cumulative_before(start, self._current_graph_mode)
        dates, values, raw_values, avg = svc.get_graph_data(
            daily_data, self._current_graph_mode, baseline=baseline
        )
        x_labels = svc.graph_x_labels(dates, self.period.mode)
        graph = self.query_one("#cmd-graph", GraphWidget)
        graph.set_data(dates, values, avg=avg)
        graph.set_x_labels(x_labels)
        graph.set_mode(self._current_graph_mode)
        graph.refresh()

        # ── Calendar ────────────────────────────────────────────────
        net_map = {d["date"]: d["net"] for d in daily_data}
        cal = self.query_one(CalendarWidget)
        cal.set_day_net_values(net_map)
        cal.set_period_context(self.period.get_anchor_date(), self.period.mode)
        cal.rebuild()

        # ── Tables (delegated to widgets) ─────────────────────────
        cat_table = self.query_one(CategoryTable)
        cat_table.refresh_data(svc, self.period, base_start, base_end)
        daily_table = self.query_one(DailyBreakdownTable)
        daily_table.refresh_data(svc, self.period, daily_data)

        # ── Statistics ──────────────────────────────────────────────
        lifetime_net = (
            svc.get_lifetime_net() if self._current_graph_mode == "net" else None
        )
        self._update_stats(raw_values, values, avg, lifetime_net=lifetime_net)

        # ── Controls (rebuild scale buttons on mode change) ──────────
        self._update_controls()

    # ── Statistics ────────────────────────────────────────────────────

    def _range_high_low_avg(
        self, raw_values: list[float]
    ) -> tuple[float, float, float] | None:
        """Best / worst / mean daily values in the visible range."""
        if not raw_values:
            return None
        if self._current_graph_mode == "negative":
            nonzero = [v for v in raw_values if v != 0]
            if not nonzero:
                return None
            return max(nonzero), min(nonzero), sum(nonzero) / len(nonzero)
        return max(raw_values), min(raw_values), sum(raw_values) / len(raw_values)

    def _update_stats(
        self,
        raw_values: list[float],
        values: list[float],
        avg: float | None,
        *,
        lifetime_net: float | None = None,
    ) -> None:
        panel = self.query_one("#cmd-graph-panel")
        if not values:
            panel.border_subtitle = ""
            return

        range_stats = self._range_high_low_avg(raw_values)
        if range_stats is None:
            if not values:
                panel.border_subtitle = ""
                return
            b, w, avg_val = 0.0, 0.0, 0.0
        else:
            b, w, avg_val = range_stats
        t = lifetime_net if lifetime_net is not None else values[-1]

        if self._current_graph_mode == "net":
            high_str = f"+{int(b)}" if b >= 0 else str(int(b))
            low_str = f"+{int(w)}" if w >= 0 else str(int(w))
            avg_str = f"+{int(avg_val)}" if avg_val >= 0 else str(int(avg_val))
            t_color = "#37d994" if t > 0 else ("#ff5f5f" if t < 0 else "")
            t_markup = f"[{t_color}]{t:+.1f}[/]" if t_color else f"{t:+.1f}"
            text = (
                f"HIGH [bold #37d994]{high_str}[/]   LOW [bold #ff5f5f]{low_str}[/]"
                f"   AVG [bold #63f3ff]{avg_str}[/]   NET [bold]{t_markup}[/]"
            )
        elif self._current_graph_mode == "negative":
            high_str = f"-{int(b)}"
            low_str = f"-{int(w)}"
            avg_str = f"{avg_val:.1f}"
            t_markup = f"[#ff5f5f]{int(t)}[/]" if t < 0 else f"{int(t)}"
            text = (
                f"HIGH [bold #ff5f5f]{high_str}[/]   LOW [bold #37d994]{low_str}[/]"
                f"   AVG [bold #63f3ff]{avg_str}[/]   NET [bold]{t_markup}[/]"
            )
        else:
            high_str = f"+{int(b)}" if b >= 0 else str(int(b))
            low_str = f"+{int(w)}" if w >= 0 else str(int(w))
            avg_str = f"+{avg_val:.1f}" if avg_val >= 0 else f"{avg_val:.1f}"
            t_color = "#37d994" if t > 0 else ("#ff5f5f" if t < 0 else "")
            t_markup = f"[{t_color}]{t:+.0f}[/]" if t_color else f"{t:+.0f}"
            text = (
                f"HIGH [bold #37d994]{high_str}[/]   LOW [bold #ff5f5f]{low_str}[/]"
                f"   AVG [bold #63f3ff]{avg_str}[/]   NET [bold]{t_markup}[/]"
            )
        panel.border_subtitle = text

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

    def _update_controls(self) -> None:
        """Update the L1 labels, controls, and cycle buttons."""
        lbl = self.query_one("#cmd-period-label", Label)
        lbl.update(self.period.get_period_label())
        self._update_cycle_labels()

    def _update_cycle_labels(self) -> None:
        """Update cycle button labels based on the current state."""
        period_btn = self.query_one("#cmd-cycle-period", Button)
        period_btn.label = f"View: {PeriodMode.label(self.period.mode)} ↻"

        metric_btn = self.query_one("#cmd-cycle-metric", Button)
        metric_label = self.GRAPH_MODE_LABELS[self.GRAPH_MODES.index(self._current_graph_mode)]
        metric_btn.label = f"Metric: {metric_label} ↻"

        scale_btn = self.query_one("#cmd-cycle-scale", Button)
        scale_btn.label = f"Range: {self.period.scale_label} ↻"


    # ── Event handlers ───────────────────────────────────────────────

    def action_cmd_previous(self) -> None:
        self._on_prev()

    def action_cmd_next(self) -> None:
        self._on_next()

    @on(Button.Pressed, "#cmd-prev")
    def _on_prev(self) -> None:
        self.period.previous()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-next")
    def _on_next(self) -> None:
        self.period.next()
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-period")
    def _on_cycle_period(self, event: Button.Pressed) -> None:
        modes = self.PERIOD_MODES
        current_idx = modes.index(self.period.mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        self.period.mode = next_mode
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-metric")
    def _on_cycle_metric(self, event: Button.Pressed) -> None:
        modes = self.GRAPH_MODES
        current_idx = modes.index(self._current_graph_mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        self._current_graph_mode = next_mode
        self.refresh_all()

    @on(Button.Pressed, "#cmd-cycle-scale")
    def _on_cycle_scale(self, event: Button.Pressed) -> None:
        current_idx = self.period.scale_index
        max_idx = self.period.scale_count - 1
        if current_idx >= max_idx:
            self.period.scale_index = 0
        else:
            self.period.scale_index = current_idx + 1
        self.refresh_all()

    # ── Calendar message handlers ──────────────────────────────────────

    @on(CalendarWidget.CalendarNav)
    def _on_calendar_nav(self, event: CalendarWidget.CalendarNav) -> None:
        self.period.set_from_day(event.target)
        self.refresh_all()

    @on(CalendarWidget.CalendarDayClicked)
    def _on_calendar_day_clicked(self, event: CalendarWidget.CalendarDayClicked) -> None:
        cd = event.clicked_date
        if self.period.mode == PeriodMode.DAY:
            self.period.set_from_day(cd)
        elif self.period.mode == PeriodMode.WEEK:
            self.period.set_from_week(cd)
        else:
            self.period.set_from_month(cd)
        self.refresh_all()

