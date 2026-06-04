"""CalendarWidget — month-grid calendar sidebar with net-based heatmap.

Extracted from toggl/command.py (lines 40–233). No logic changes.
"""

from __future__ import annotations

from datetime import date, timedelta

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Click
from textual.message import Message
from textual.widgets import Button, Label, Static

from toggl.cache import get_week_str
from toggl.formatters import _label_for_day
from toggl.state.period import PeriodMode


def _get_anchor_week_dates(anchor: date) -> set[date]:
    sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    return {sunday + timedelta(days=i) for i in range(7)}


class CalendarWidget(Static):
    """Month-grid calendar sidebar with net-based heatmap coloring.

    Emits ``CalendarNav`` and ``CalendarDayClicked`` messages instead of
    calling parent widgets directly, making it independently instantiable
    and testable.
    """

    can_focus = True

    class CalendarNav(Message):
        """Posted when the user navigates to a different month."""

        def __init__(self, target: date) -> None:
            super().__init__()
            self.target = target

    class CalendarDayClicked(Message):
        """Posted when the user clicks a day cell in the grid."""

        def __init__(self, clicked_date: date) -> None:
            super().__init__()
            self.clicked_date = clicked_date

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

    def __init__(self) -> None:
        super().__init__(id="command-calendar")
        self._display_year = date.today().year
        self._display_month = date.today().month
        self._day_nets: dict[str, float] = {}
        self._anchor_date: date = date.today()
        self._period_mode: str = "week"

    def set_day_net_values(self, day_nets: dict[str, float]) -> None:
        self._day_nets = day_nets

    def set_period_context(self, anchor: date, mode: str) -> None:
        """Set the anchor date and period mode used for highlighting."""
        self._anchor_date = anchor
        self._period_mode = mode

    def compose(self) -> ComposeResult:
        day_names = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
        with Container(id="cal-nav"):
            yield Button("\u2190", id="cal-prev-month")
            yield Label("", id="cal-month-label")
            yield Button("\u2192", id="cal-next-month")
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

    def rebuild(self) -> None:
        anchor = self._anchor_date
        self._display_year = anchor.year
        self._display_month = anchor.month

        first_day = date(self._display_year, self._display_month, 1)
        grid_start = first_day - timedelta(days=(first_day.weekday() + 1) % 7)

        today = date.today()
        anchor_week = _get_anchor_week_dates(anchor) if self._period_mode in (PeriodMode.WEEK,) else None

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
                day_date, today, anchor, anchor_week, self._period_mode,
                self._display_month, self._display_year, net,
            )
            label.update(markup)

    @on(Button.Pressed, "#cal-prev-month")
    def _on_prev_month(self) -> None:
        if self._display_month == 1:
            self._display_month = 12
            self._display_year -= 1
        else:
            self._display_month -= 1
        target = date(self._display_year, self._display_month, 1)
        self.post_message(self.CalendarNav(target))

    @on(Button.Pressed, "#cal-next-month")
    def _on_next_month(self) -> None:
        if self._display_month == 12:
            self._display_month = 1
            self._display_year += 1
        else:
            self._display_month += 1
        target = date(self._display_year, self._display_month, 1)
        if target > date.today():
            return
        self.post_message(self.CalendarNav(target))

    @on(Click, "#cal-grid Label.cal-day")
    def _on_day_clicked(self, event: Click) -> None:
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

        self.post_message(self.CalendarDayClicked(clicked_date))

    def on_click(self, event: Click) -> None:
        """Focus the calendar when clicked anywhere."""
        self.focus()
