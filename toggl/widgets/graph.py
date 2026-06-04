"""GraphWidget — Textual widget wrapping plotext for trajectory charts.

Also exports ``build_sparkline()`` for rendering inline sparkline bars
in table cells.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

from toggl.widgets.icons import ICON, spark_char, fractional_bar

_GREEN = (55, 217, 148)
_RED = (255, 95, 95)
_CYAN = (45, 212, 191)
_PURPLE = (192, 132, 252)
_CANVAS = (11, 16, 22)
_BORDER = (25, 35, 45)
_TICK_DIM = (140, 150, 160)
_ZERO_LINE = (42, 50, 60)
_AVG_LINE = (75, 62, 27)
_FILL_ALPHA = (55, 217, 148, 38)  # Transparent green fill

_MODE_COLORS = {
    "net": _GREEN, "positive": _GREEN, "negative": _RED,
}


def build_sparkline(values: list[float], width: int = 10) -> str:
    """Build a Rich-markup sparkline string from a list of numeric values.

    Uses Unicode block characters (▁-█) to encode value intensity.
    Positive values are green, negative values are red.

    >>> build_sparkline([1, 3, 2, 5, 4])
    ''[#37d994]▂▅▃█▆[/]''
    """
    if not values:
        return ""

    min_val = min(values)
    max_val = max(values)

    # Downsample to target width
    n = len(values)
    if n > width:
        step = n / width
        sampled = []
        for i in range(width):
            start_idx = int(i * step)
            end_idx = int((i + 1) * step)
            chunk = values[start_idx:end_idx]
            if chunk:
                sampled.append(sum(chunk) / len(chunk))
        values = sampled

    chars = [spark_char(v, min_val, max_val) for v in values]

    # Color: if all non-negative, green; otherwise color individually
    if all(v >= 0 for v in values):
        return f"[#37d994]{''.join(chars)}[/]"
    if all(v <= 0 for v in values):
        return f"[#ff5f5f]{''.join(chars)}[/]"

    # Mixed: simple - green if trend positive, red if negative
    return f"[#63f3ff]{''.join(chars)}[/]"


def _format_date_label(iso_date: str) -> str:
    """Convert '2026-05-31' to short label '05/31'."""
    try:
        parts = iso_date.split("-")
        return f"{parts[1]}/{parts[2]}"
    except (IndexError, ValueError):
        return iso_date


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _nice_yticks(lo: float, hi: float, count: int = 5) -> tuple[float, float, list[float]]:
    """Return (ymin, ymax, ticks) for nicely-rounded, evenly-spaced y-tick values spanning [lo, hi]."""
    if lo == hi:
        if lo == 0:
            lo, hi = -1.0, 1.0
        else:
            lo = lo - abs(lo) * 0.1 - 1.0
            hi = hi + abs(hi) * 0.1 + 1.0

    span = hi - lo
    import math
    raw_step = span / (count - 1)

    log10_step = math.log10(raw_step)
    power = math.floor(log10_step)
    fraction = raw_step / (10 ** power)

    if fraction < 1.5:
        nice_fraction = 1.0
    elif fraction < 3.0:
        nice_fraction = 2.0
    elif fraction < 7.0:
        nice_fraction = 5.0
    else:
        nice_fraction = 10.0

    nice_step = nice_fraction * (10 ** power)

    ymin = math.floor(lo / nice_step) * nice_step
    ymax = math.ceil(hi / nice_step) * nice_step

    if nice_step <= 0 or ymin >= ymax:
        ymin = lo
        ymax = hi
        nice_step = span / (count - 1)
        ticks = [round(lo + i * nice_step, 1) for i in range(count)]
        return ymin, ymax, ticks

    ticks = []
    t = ymin
    while t <= ymax + nice_step * 0.01:
        val = round(t, 2 if nice_step < 1 else 0)
        if not ticks or val != ticks[-1]:
            ticks.append(val)
        t += nice_step
        if len(ticks) > 15:
            break

    if len(ticks) < 3:
        ticks = [round(ymin, 1), round((ymin + ymax) / 2, 1), round(ymax, 1)]

    return ymin, ymax, ticks


class GraphWidget(Widget):
    """Plotext-rendered trajectory chart with gradient fill and sparkline support."""

    can_focus = True

    DEFAULT_CSS = """
    GraphWidget { width: 1fr; height: 1fr; }
    """

    _MAX_XTICKS = 8

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._dates: list[str] = []
        self._values: list[float] = []
        self._x_labels: list[str] | None = None
        self._mode: str = "net"
        self._avg: float | None = None
        self._fill_gradient: bool = True

    def set_data(self, dates: list[str], values: list[float], avg: float | None = None) -> None:
        self._dates = dates
        self._values = values
        self._avg = avg

    def set_x_labels(self, labels: list[str] | None) -> None:
        """Optional per-point x-axis labels (e.g. ``Wk 23``); defaults to short dates."""
        self._x_labels = labels

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def render(self) -> RenderResult:
        import plotext as plt

        if not self._dates or not self._values:
            return Text("[dim]No data available for selected period.[/]")

        plt.clear_data()
        plt.clear_figure()

        w = max(10, self.size.width)
        h = max(5, self.size.height)
        plt.plotsize(w, h)

        plt.theme("dark")
        plt.canvas_color(_CANVAS)
        plt.axes_color(_CANVAS)
        plt.ticks_color(_TICK_DIM)
        plt.frame(False)
        plt.grid(True)
        plt.ticks_style("normal")

        # ── Dynamic Y scaling with nice rounded ticks ──────────────
        if self._mode == "net":
            lo = min(self._values)
            hi = max(self._values)
            span = hi - lo
            pad = span * 0.15 if span > 0 else 1.0
            ymin, ymax, ticks = _nice_yticks(lo - pad, hi + pad)
        else:
            nonzero = [v for v in self._values if v != 0]
            if nonzero:
                lo = min(nonzero)
                hi = max(nonzero)

                med = _median(nonzero)
                max_abs = max(abs(lo), abs(hi))
                if med != 0 and max_abs > 3 * abs(med):
                    cap = 3 * abs(med)
                    lo = max(lo, -cap) if lo >= 0 else min(lo, cap)
                    hi = min(hi, cap) if hi >= 0 else max(hi, -cap)

                pad = (hi - lo) * 0.15 or max_abs * 0.1

                if lo >= 0:
                    ymin = 0.0
                    ymax = hi + pad
                else:
                    ymin = lo - pad
                    ymax = 0.0

                ymin, ymax, ticks = _nice_yticks(ymin, ymax)
            else:
                ymin, ymax = -1.0, 1.0
                ticks = [0.0]

        plt.ylim(ymin, ymax)

        # ── X-axis: numeric indices + manual labels ───────────────
        n = len(self._dates)
        x_indices = list(range(n))

        if self._mode == "net":
            line_color = _RED if self._values[-1] < 0 else _GREEN
        else:
            line_color = _MODE_COLORS.get(self._mode, _GREEN)

        # ── Gradient fill under the line ────────────────────────────
        if self._fill_gradient and n > 1:
            # Create a zero-baseline array for fill
            baseline = 0.0 if ymin <= 0 <= ymax else ymin
            fill_vals = [max(baseline, v) if v >= 0 else min(baseline, v) for v in self._values]
            # Use a dimmed, translucent version of the line color
            fill_color = tuple(int(c * 0.25) for c in line_color)
            try:
                plt.fill_between(x_indices, self._values, fill_vals, color=fill_color)
            except Exception:
                pass  # fill_between may not be available in all plotext versions

        plt.plot(x_indices, self._values, color=line_color, marker="braille")

        plt.xlim(0, n - 1)

        # Spread x-tick labels to avoid overlap
        step = max(1, n // self._MAX_XTICKS)
        xtick_positions = x_indices[::step]
        if self._x_labels and len(self._x_labels) == n:
            xtick_labels = []
            prev = None
            for i in xtick_positions:
                label = self._x_labels[i]
                xtick_labels.append("" if label == prev else label)
                prev = label
        else:
            xtick_labels = [_format_date_label(self._dates[i]) for i in xtick_positions]
        plt.xticks(xtick_positions, xtick_labels)

        # ── Zero line ─────────────────────────────────────────────
        if ymin <= 0 <= ymax:
            plt.hline(0, color=_ZERO_LINE)

        # ── Average line ──────────────────────────────────────────
        if self._avg is not None and ymin <= self._avg <= ymax:
            plt.hline(self._avg, color=_AVG_LINE)

        # ── Clean Y-axis ticks ─────────────────────────────────────
        plt.yticks(ticks)

        ansi_str = plt.build()
        if ansi_str.endswith("\n"):
            ansi_str = ansi_str[:-1]
        return Text.from_ansi(ansi_str, no_wrap=True)

    def on_click(self, event: Any) -> None:
        """Focus the graph when clicked."""
        self.focus()
