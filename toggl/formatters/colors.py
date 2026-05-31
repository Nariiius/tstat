"""Color helper functions for TUI display cells and calendar widgets."""

from datetime import date


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
