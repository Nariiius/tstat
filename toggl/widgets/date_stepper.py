"""DateStepper — reusable left/right date navigation widget.

A horizontal strip with ◀ and ▶ buttons flanking a date label.
Arrow keys (left/right) step the date by ±1 day.
"""

from __future__ import annotations

from datetime import date, timedelta

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Label


class DateStepper(Horizontal):
    """A compact date picker: ◀ | YYYY-MM-DD | ▶.

    Attributes:
        selected_date: The currently displayed / selected date.
        max_date: Upper bound for navigation (inclusive). Defaults to today.
    """

    selected_date: reactive[date] = reactive(date.today, init=False)
    max_date: reactive[date] = reactive(date.today, init=False)

    BINDINGS = [
        Binding("left", "step_back", "Back", show=False),
        Binding("right", "step_forward", "Forward", show=False),
    ]

    DEFAULT_CSS = """
    DateStepper {
        height: auto;
        width: auto;
        align: center middle;
    }

    DateStepper .stepper-btn {
        background: transparent;
        border: none;
        min-width: 3;
        height: 1;
        color: #63f3ff;
        text-style: bold;
    }

    DateStepper .stepper-btn:hover {
        color: #d7dde8;
        background: #1e2a36;
        border: none;
    }

    DateStepper #stepper-date-label {
        min-width: 12;
        text-align: center;
        color: #63f3ff;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *args,
        initial_date: date | None = None,
        max_date: date | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._initial_date = initial_date or date.today()
        self._max_date = max_date or date.today()
        # Set reactives eagerly so they are available before on_mount
        self.max_date = self._max_date
        self.selected_date = self._initial_date

    def compose(self) -> ComposeResult:
        yield Button("\u25c0", id="stepper-prev", classes="stepper-btn")
        yield Label(self._format_date(self._initial_date), id="stepper-date-label")
        yield Button("\u25b6", id="stepper-next", classes="stepper-btn")

    def on_mount(self) -> None:
        # Re-clamp in case max_date changed between __init__ and mount
        if self.selected_date > self._max_date:
            self.selected_date = self._max_date

    # ── reactive watchers ──────────────────────────────────────────

    def watch_selected_date(self, value: date) -> None:
        """Update the label whenever selected_date changes."""
        try:
            label = self.query_one("#stepper-date-label", Label)
            label.update(self._format_date(value))
        except Exception:
            pass  # Widget not mounted yet

    def watch_max_date(self, value: date) -> None:
        """Clamp selected_date if it now exceeds max_date."""
        if self.selected_date > value:
            self.selected_date = value

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _format_date(d: date) -> str:
        return d.strftime("%Y-%m-%d")

    def _step(self, delta: int) -> None:
        """Step the date by *delta* days, clamped to max_date."""
        candidate = self.selected_date + timedelta(days=delta)
        if candidate > self.max_date:
            return
        self.selected_date = candidate

    # ── actions ────────────────────────────────────────────────────

    def action_step_back(self) -> None:
        self._step(-1)

    def action_step_forward(self) -> None:
        self._step(1)

    # ── button handlers ────────────────────────────────────────────

    @on(Button.Pressed, "#stepper-prev")
    def _on_prev(self) -> None:
        self._step(-1)

    @on(Button.Pressed, "#stepper-next")
    def _on_next(self) -> None:
        self._step(1)
