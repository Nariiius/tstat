"""GraphWidget — Textual widget wrapping plotext for trajectory charts."""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

_GREEN = (55, 217, 148)
_RED = (255, 95, 95)
_CYAN = (45, 212, 191)
_PURPLE = (192, 132, 252)
_CANVAS = (11, 16, 22)
_BORDER = (25, 35, 45)
_TICK_DIM = (50, 60, 75)
_ZERO_LINE = (215, 221, 232)
_AVG_LINE = (61, 79, 99)

_MODE_COLORS = {
    "trajectory": _GREEN, "positive": _GREEN, "negative": _RED,
    "logged_pos": _CYAN, "logged_neg": _PURPLE,
}


def _iso_to_plotext(iso_dates: list[str]) -> list[str]:
    result = []
    for d in iso_dates:
        try:
            parts = d.split("-")
            result.append(f"{parts[2]}/{parts[1]}/{parts[0]}")
        except (IndexError, ValueError):
            result.append(d)
    return result


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


class GraphWidget(Widget):
    """Plotext-rendered trajectory chart."""

    DEFAULT_CSS = """
    GraphWidget { width: 1fr; height: 1fr; }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dates: list[str] = []
        self._values: list[float] = []
        self._mode: str = "trajectory"
        self._avg: float | None = None

    def set_data(self, dates: list[str], values: list[float], avg: float | None = None):
        self._dates = dates
        self._values = values
        self._avg = avg

    def set_mode(self, mode: str):
        self._mode = mode

    def render(self) -> RenderResult:
        import plotext as plt

        if not self._dates or not self._values:
            return Text("[dim]No data available for selected period.[/]")

        plt.clear_data()
        plt.clear_figure()

        w = max(10, self.size.width - 2)
        h = max(5, self.size.height - 2)
        plt.plotsize(w, h)

        plt.theme("dark")
        plt.canvas_color(_CANVAS)
        plt.axes_color(_BORDER)
        plt.ticks_color(_TICK_DIM)
        plt.frame(False)
        plt.grid(True)
        plt.ticks_style("dim")

        pt_dates = _iso_to_plotext(self._dates)

        if len(pt_dates) > 60:
            plt.date_form(output_form="%m/%y")
        else:
            plt.date_form(output_form="%m/%d")

        # ── Dynamic Y scaling with outlier clipping ────────────────
        nonzero = [v for v in self._values if v != 0]
        if nonzero:
            lo = min(nonzero)
            hi = max(nonzero)
            span = hi - lo or 1
            med = _median(nonzero)
            max_abs = max(abs(lo), abs(hi))

            # Cap extreme outliers: one terrible day shouldn't flatten everything
            if med != 0 and max_abs > 3 * abs(med):
                cap = 3 * abs(med)
                lo = max(lo, -cap)
                hi = min(hi, cap)

            pad = (hi - lo) * 0.15 or max_abs * 0.1
            if self._mode == "trajectory":
                bound = max(abs(lo - pad), abs(hi + pad), 1)
                plt.ylim(-bound, bound)
            else:
                plt.ylim(min(0, lo - pad), hi + pad)
        else:
            plt.ylim(-1, 1)

        # ── Plot ───────────────────────────────────────────────────
        line_color = _MODE_COLORS.get(self._mode, _GREEN)
        plt.plot(pt_dates, self._values, color=line_color, marker="braille")

        # ── Zero line (bright) ─────────────────────────────────────
        plt.hline(0, color=_ZERO_LINE)

        # ── Average line (dim grey) ────────────────────────────────
        if self._avg is not None:
            plt.hline(self._avg, color=_AVG_LINE)

        # ── 3 Y-axis labels only: max / 0 / min ────────────────────
        if self._mode == "trajectory":
            plt.yticks([lo, 0, hi])
        else:
            plt.yticks([lo, hi])

        # No markers — clean graph

        return Text.from_ansi(plt.build())
