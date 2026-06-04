"""LoadingWidget — animated spinner and pulsing text for loading states.

Provides ``LoadingWidget`` (animated braille spinner + label) and
``PulseText`` (breathing opacity text animation).

Usage:
    from toggl.widgets.loading import LoadingWidget, PulseText

    # In a compose method:
    yield LoadingWidget("Computing playbook...")
    yield PulseText("Analyzing activity data...")
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Label

from toggl.widgets.icons import ICON


class LoadingWidget(Horizontal):
    """Animated braille spinner with an optional label.

    The spinner cycles through all 10 braille frames every 100ms.
    Set ``label`` to show text beside the spinner.
    """

    DEFAULT_CSS = """
    LoadingWidget {
        height: auto;
        width: auto;
        align: center middle;
        padding: 1 0;
    }

    LoadingWidget > #loading-spinner {
        color: #63f3ff;
        text-style: bold;
        width: auto;
        min-width: 2;
    }

    LoadingWidget > #loading-label {
        color: #8d98a7;
        width: auto;
        margin-left: 1;
    }
    """

    def __init__(
        self,
        label: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._label_text = label
        self._spin_index = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Label(ICON["spinner_frames"][0], id="loading-spinner")
        if self._label_text:
            yield Label(self._label_text, id="loading-label")

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._advance_spinner)

    def _advance_spinner(self) -> None:
        frames = ICON["spinner_frames"]
        self._spin_index = (self._spin_index + 1) % len(frames)
        try:
            self.query_one("#loading-spinner", Label).update(frames[self._spin_index])
        except Exception:
            pass

    def set_label(self, text: str) -> None:
        """Update the optional label text."""
        self._label_text = text
        try:
            lbl = self.query_one("#loading-label", Label)
            lbl.update(text)
            lbl.display = bool(text)
        except Exception:
            pass

    def stop(self) -> None:
        """Stop the spinner animation."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


class PulseText(Label):
    """A Label whose text breathes (pulses opacity) while visible.

    Use for showing progress-stage text during computation.
    """

    DEFAULT_CSS = """
    PulseText {
        color: #8d98a7;
        width: auto;
        height: auto;
    }
    """

    def __init__(
        self,
        text: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(text, id=id, classes=classes)
        self._direction = -1  # Start fading out

    def on_mount(self) -> None:
        self.set_interval(0.8, self._pulse)

    def _pulse(self) -> None:
        target = 0.4 if self._direction < 0 else 1.0
        self._direction *= -1
        try:
            self.styles.animate("opacity", value=target, duration=0.7, easing="in_out_cubic")
        except Exception:
            pass


class ProgressIndicator(Label):
    """A progress bar label that can be updated with percentage.

    Shows a Unicode block-based progress bar with percentage label.
    Call ``set_progress(0.0-1.0)`` to update.
    """

    DEFAULT_CSS = """
    ProgressIndicator {
        color: #63f3ff;
        width: auto;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        width: int = 20,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self._bar_width = width
        self._progress = 0.0

    def set_progress(self, ratio: float) -> None:
        """Update the progress bar to *ratio* (0.0-1.0)."""
        self._progress = max(0.0, min(1.0, ratio))
        filled = int(self._progress * self._bar_width)
        empty = self._bar_width - filled
        pct = int(self._progress * 100)
        bar = (
            f"[bold #63f3ff]{ICON['bar_filled'] * filled}[/]"
            f"[#4a5565]{ICON['bar_empty'] * empty}[/]"
            f"  [#63f3ff]{pct:>3}%[/]"
        )
        self.update(bar)

    @property
    def progress(self) -> float:
        return self._progress
