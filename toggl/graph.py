"""GraphWidget — Textual widget wrapping plotext for trajectory charts.

Adapted from the Bagels PlotextPlot pattern.
Uses plotext's module-level API since TStat has a single graph widget per app.

plotext v5+ treats all string X values as dates by default (format: %d/%m/%Y).
We convert dates from ISO (%Y-%m-%d) to the plotext-native format.
"""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

# ── Color palette (RGB tuples for plotext) ─────────────────────
_GREEN = (55, 217, 148)
_RED = (255, 95, 95)
_CYAN = (45, 212, 191)
_PURPLE = (192, 132, 252)
_GOLD = (226, 183, 20)
_CANVAS = (11, 16, 22)
_TICK_DIM = (50, 60, 75)
_ZERO_LINE = (215, 221, 232)     # bright, eye-catching
_GRID = (30, 40, 50)             # very dim
_BORDER = (25, 35, 45)            # subtle border

_MODE_COLORS = {
    "trajectory": _GREEN,
    "positive": _GREEN,
    "negative": _RED,
    "logged_pos": _CYAN,
    "logged_neg": _PURPLE,
}


def _iso_to_plotext(iso_dates: list[str]) -> list[str]:
    """Convert ISO dates ('2026-05-31') to plotext-native format ('31/05/2026')."""
    result = []
    for d in iso_dates:
        try:
            parts = d.split("-")
            result.append(f"{parts[2]}/{parts[1]}/{parts[0]}")
        except (IndexError, ValueError):
            result.append(d)
    return result


class GraphWidget(Widget):
    """Plotext-rendered trajectory chart.

    Stateless rendering: receives dates, values, and configuration via
    set_data / set_mode, then builds the plot on every render() call.
    """

    DEFAULT_CSS = """
    GraphWidget {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dates: list[str] = []       # ISO format (YYYY-MM-DD)
        self._values: list[float] = []
        self._mode: str = "trajectory"
        self._best_idx: int | None = None
        self._worst_idx: int | None = None

    # ── Mutators (called by CommandTab before refresh) ──────────────

    def set_data(self, dates: list[str], values: list[float]):
        """Set X (ISO dates) and Y data arrays."""
        self._dates = dates
        self._values = values
        self._best_idx = None
        self._worst_idx = None
        if values:
            nonzero = [(i, v) for i, v in enumerate(values) if v != 0]
            if nonzero:
                best = max(nonzero, key=lambda x: x[1])
                worst = min(nonzero, key=lambda x: x[1])
                self._best_idx = best[0]
                self._worst_idx = worst[0]

    def set_mode(self, mode: str):
        """Set graph mode: 'trajectory' | 'positive' | 'negative' | 'logged_pos' | 'logged_neg'."""
        self._mode = mode

    # ── Render ──────────────────────────────────────────────────────

    def render(self) -> RenderResult:
        import plotext as plt

        if not self._dates or not self._values:
            return Text("[dim]No data available for selected period.[/]")

        plt.clear_data()
        plt.clear_figure()

        w = max(10, self.size.width - 2)
        h = max(5, self.size.height - 2)
        plt.plotsize(w, h)

        # Dark canvas matching TStat (#0b1016)
        plt.theme("dark")
        plt.canvas_color(_CANVAS)
        plt.axes_color(_BORDER)     # subtle, not a heavy frame
        plt.ticks_color(_TICK_DIM)

        # Remove the heavy Plotext frame — keep only the textual widget border
        plt.frame(False)

        # Subtle grid, dim
        plt.grid(True)
        plt.ticks_style("dim")

        # Convert dates to plotext-native format (%d/%m/%Y)
        pt_dates = _iso_to_plotext(self._dates)

        # Set how the dates should appear on the X axis
        if len(pt_dates) > 60:
            plt.date_form(output_form="%m/%y")
        elif len(pt_dates) > 14:
            plt.date_form(output_form="%m/%d")
        else:
            plt.date_form(output_form="%m/%d")

        # ── Y axis scaling: use 5th/95th percentile to clip outliers ──
        if self._values:
            sorted_vals = sorted(self._values)
            n = len(sorted_vals)
            p5 = sorted_vals[max(0, int(n * 0.05))]
            p95 = sorted_vals[min(n - 1, int(n * 0.95))]

            if self._mode == "trajectory":
                # Symmetric around zero with percentile-based bound
                bound = max(abs(p5), abs(p95)) or 1
                bound *= 1.15
                plt.ylim(-bound, bound)
            else:
                lo = min(0, p5) * 1.1
                hi = p95 * 1.15 or 1
                plt.ylim(lo, hi)
        else:
            plt.ylim(-1, 1)

        # ── Plot data ─────────────────────────────────────────────────
        line_color = _MODE_COLORS.get(self._mode, _GREEN)

        if self._mode in ("trajectory", "positive", "negative", "logged_pos", "logged_neg"):
            plt.plot(pt_dates, self._values, color=line_color, marker="braille", filly=False)

        # ── Bright zero line dominating the chart ────────────────────
        plt.hline(0, color=_ZERO_LINE)

        # ── Today marker: subtle dot on the data point, not a giant line ──
        pt_today = date.today().strftime("%d/%m/%Y")
        if pt_today in pt_dates:
            idx = pt_dates.index(pt_today)
            plt.scatter(
                [pt_today],
                [self._values[idx]],
                marker="star",
                color=_GOLD,
            )

        # ── Best / worst markers ─────────────────────────────────────
        if self._best_idx is not None and self._best_idx < len(pt_dates):
            plt.scatter(
                [pt_dates[self._best_idx]],
                [self._values[self._best_idx]],
                marker="star",
                color=_GREEN,
            )
        if self._worst_idx is not None and self._worst_idx < len(pt_dates):
            plt.scatter(
                [pt_dates[self._worst_idx]],
                [self._values[self._worst_idx]],
                marker="star",
                color=_RED,
            )

        return Text.from_ansi(plt.build())
