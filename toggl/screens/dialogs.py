"""Modal dialog screens for TogglTrack TUI.

Extracted from ``tui.py`` to enable independent testing and reduce file size.
"""

from __future__ import annotations

from datetime import date

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static

from toggl.config import NEGATIVES, POSITIVES
from toggl.widgets.date_stepper import DateStepper


def _parse_option_name(prompt: str) -> str:
    """Extract the activity name from a formatted option prompt.

    Prompts look like ``\"Exercise  (+3 pts)\"`` or ``\"Procrastination  (-5 pts)\"``.
    Returns the name portion before the points annotation.
    """
    idx = prompt.rfind("  (")
    if idx > 0:
        return prompt[:idx]
    return prompt


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
        background: #0b1016 60%;
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
        color: #d7dde8;
    }

    #dialog-box:focus,
    #dialog-box:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    .dialog-body {
        margin-bottom: 1;
        color: #d7dde8;
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

    def __init__(self, title: str) -> None:
        super().__init__()
        self._dialog_title = title

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            with Container(id="dialog-box"):
                yield from self.body()

    def body(self) -> ComposeResult:
        """Override to yield dialog content inside #dialog-box."""
        return

    def on_mount(self) -> None:
        self.query_one("#dialog-box").border_title = (
            f"[b][#63f3ff]{self._dialog_title}[/][/]"
        )

    def action_cancel(self) -> None:
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

    def __init__(self, title: str, body: str) -> None:
        self._body_text = body
        super().__init__(title)

    def body(self) -> ComposeResult:
        yield Static(self._body_text, classes="dialog-body")
        with Horizontal(id="dialog-buttons"):
            yield Static("[Y/Enter] confirm", id="btn-confirm", classes="dialog-help")
            yield Static("  " "[N/Esc] cancel", id="btn-cancel", classes="dialog-help")

    @on(Click, "#btn-confirm")
    def on_confirm_click(self) -> None:
        self.dismiss(True)

    @on(Click, "#btn-cancel")
    def on_cancel_click(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class NegativeInputScreen(BaseDialog):
    """Pick a negative action to log with optional date selection."""

    DEFAULT_CSS = """
    NegativeInputScreen #dialog-box {
        min-width: 60;
        max-width: 80;
    }

    NegativeInputScreen DateStepper {
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("Log Negative")

    def body(self) -> ComposeResult:
        yield Static("Adjust date if needed, then select an action.", classes="dialog-body")
        yield DateStepper(id="negative-date-stepper")
        yield OptionList(id="negative-list")
        yield Static("[Esc] cancel", id="btn-cancel", classes="dialog-help")

    def on_mount(self) -> None:
        super().on_mount()
        option_list = self.query_one("#negative-list", OptionList)
        for name, pts in NEGATIVES.items():
            if pts == int(pts):
                option_list.add_option(f"{name}  ({int(pts):+d} pts)")
            else:
                option_list.add_option(f"{name}  ({pts:+.1f} pts)")
        option_list.focus()

    @on(OptionList.OptionSelected, "#negative-list")
    def submit_negative(self, event: OptionList.OptionSelected) -> None:
        stepper = self.query_one("#negative-date-stepper", DateStepper)
        name = _parse_option_name(str(event.option.prompt))
        self.dismiss({
            "name": name,
            "date": stepper.selected_date.strftime("%Y-%m-%d"),
        })

    @on(Click, "#btn-cancel")
    def on_cancel_click(self) -> None:
        self.dismiss(None)


class PositiveInputScreen(BaseDialog):
    """Pick a positive action to log with optional date selection."""

    DEFAULT_CSS = """
    PositiveInputScreen #dialog-box {
        min-width: 60;
        max-width: 80;
    }

    PositiveInputScreen DateStepper {
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("Log Positive")

    def body(self) -> ComposeResult:
        yield Static("Adjust date if needed, then select an action.", classes="dialog-body")
        yield DateStepper(id="positive-date-stepper")
        yield OptionList(id="positive-list")
        yield Static("[Esc] cancel", id="btn-cancel", classes="dialog-help")

    def on_mount(self) -> None:
        super().on_mount()
        option_list = self.query_one("#positive-list", OptionList)
        for name, pts in POSITIVES.items():
            if pts == int(pts):
                option_list.add_option(f"{name}  (+{int(pts)} pts)")
            else:
                option_list.add_option(f"{name}  (+{pts:.1f} pts)")
        option_list.focus()

    @on(OptionList.OptionSelected, "#positive-list")
    def submit_positive(self, event: OptionList.OptionSelected) -> None:
        stepper = self.query_one("#positive-date-stepper", DateStepper)
        name = _parse_option_name(str(event.option.prompt))
        self.dismiss({
            "name": name,
            "date": stepper.selected_date.strftime("%Y-%m-%d"),
        })

    @on(Click, "#btn-cancel")
    def on_cancel_click(self) -> None:
        self.dismiss(None)
