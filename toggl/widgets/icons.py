"""Central icon/glyph registry for TUI visual elements.

All Unicode characters used across the TUI are defined here with semantic
names and ASCII fallbacks for environments that can't render them.

Usage:
    from toggl.widgets.icons import ICON

    label = ICON["check"]
    nav_prev = ICON["nav_prev"]
"""

from __future__ import annotations

# ──────────────────────────────────────────────
# Icon registry — single source of truth
# ──────────────────────────────────────────────

ICON = {
    # ── Status badges ────────────────────
    "status_on_track": "\u25c9",
    "status_close_gap": "\u25c9",
    "status_recover": "\u25c9",
    "status_setup": "\u25c9",

    # ── Action indicators ────────────────
    "check": "\u2713",
    "blocked": "\u25f7",
    "low_control": "\u25cb",
    "focus_pointer": "\u25b8",
    "bullet": "\u2022",
    "star": "\u2605",
    "warning": "\u26a0",
    "neglect": "\u2205",
    "diamond": "\u25c8",

    # ── Trajectory / trend ───────────────
    "trajectory_up": "\u2197",
    "trajectory_down": "\u2198",
    "frequency_drop": "\u2198",
    "on_a_roll": "\u2197",
    "gap_reminder": "\u23f1",

    # ── Navigation ───────────────────────
    "nav_prev": "\u25c0",
    "nav_next": "\u25b6",
    "nav_back": "\u2190",
    "nav_forward": "\u2192",
    "nav_back_wide": "\u27f5",
    "nav_forward_wide": "\u27f6",
    "nav_page_back": "\u25c1",
    "nav_page_forward": "\u25b7",

    # ── Sync & time ─────────────────────
    "sync": "\u27f3",
    "hourglass": "\u23f3",
    "clock": "\u23f1",

    # ── Progress / bars ──────────────────
    "bar_filled": "\u2501",
    "bar_empty": "\u2500",
    "bar_block": "\u2588",
    "bar_fractional": ["\u258f", "\u258e", "\u258d", "\u258c", "\u258b", "\u258a", "\u2589"],

    # ── Braille spinners ────────────────
    "spinner_frames": [
        "\u280b", "\u2819", "\u2839", "\u2838", "\u283c",
        "\u2834", "\u2826", "\u2827", "\u2807", "\u280f",
    ],

    # ── Direction arrows (sync spin) ─────
    "spin_frames": ["\u25f7", "\u25f6", "\u25f5", "\u25f4"],

    # ── Table / tree drawing ─────────────
    "tree_branch": "\u251c",
    "tree_last": "\u2514",
    "tree_connector": "\u2502",
    "tree_horiz": "\u2500",

    # ── Separators ───────────────────────
    "sep_thin": "\u2500" * 22,
    "sep_thick": "\u2550" * 22,
    "sep_medium": "\u2501" * 22,

    # ── Sparkline levels ────────────────
    "spark_chars": [
        "\u2581", "\u2582", "\u2583", "\u2584",
        "\u2585", "\u2586", "\u2587", "\u2588",
    ],

    # ── Intensity blocks (calendar heatmap) ─
    "intensity_none": "\u00b7",
    "intensity_low": "\u2591",
    "intensity_med": "\u2592",
    "intensity_high": "\u2593",
    "intensity_max": "\u2588",

    # ── Symbols ─────────────────────────
    "multiply": "\u00d7",
    "em_dash": "\u2014",
    "plus": "+",
    "minus": "\u2212",
    "section": "\u00a7",

    # ── Circled numbers 1-9 ─────────────
    "num_circled": [
        "\u2460", "\u2461", "\u2462", "\u2463", "\u2464",
        "\u2465", "\u2466", "\u2467", "\u2468",
    ],

    # ── Section category icons ───────────
    "cat_positive": "\u2726",
    "cat_negative": "\u25bc",
    "cat_unscored": "\u25c7",
    "cat_logged_pos": "\u2b06",
    "cat_logged_neg": "\u2b07",

    # ── Week brief ──────────────────────
    "focus": "\u25ce",
    "protect": "\u25c8",
    "skip": "\u2297",

    # ── Loading ──────────────────────────
    "loading_dots": [
        "\u280b", "\u2819", "\u2839", "\u2838", "\u283c",
        "\u2834", "\u2826", "\u2827", "\u2807", "\u280f",
    ],
}


# ──────────────────────────────────────────────
# ASCII fallbacks for non-Unicode environments
# ──────────────────────────────────────────────

ICON_ASCII = {
    "status_on_track": "[OK]",
    "status_close_gap": "[~]",
    "status_recover": "[!!]",
    "status_setup": "[--]",
    "check": "[x]",
    "blocked": "[B]",
    "low_control": "( )",
    "focus_pointer": ">",
    "bullet": "*",
    "star": "*",
    "warning": "!",
    "neglect": "(/)",
    "diamond": "<>",
    "trajectory_up": "/",
    "trajectory_down": "\\",
    "frequency_drop": "v",
    "on_a_roll": "^",
    "gap_reminder": "(t)",
    "nav_prev": "<",
    "nav_next": ">",
    "nav_back": "<-",
    "nav_forward": "->",
    "nav_back_wide": "<<",
    "nav_forward_wide": ">>",
    "nav_page_back": "<<",
    "nav_page_forward": ">>",
    "sync": "(sync)",
    "hourglass": "(...)",
    "clock": "(t)",
    "bar_filled": "=",
    "bar_empty": "-",
    "bar_block": "#",
    "tree_branch": "|-",
    "tree_last": "`-",
    "tree_connector": "|",
    "tree_horiz": "-",
    "sep_thin": "-" * 22,
    "sep_thick": "=" * 22,
    "sep_medium": "-" * 22,
    "multiply": "x",
    "em_dash": "--",
    "plus": "+",
    "minus": "-",
    "section": "S",
    "cat_positive": "+",
    "cat_negative": "-",
    "cat_unscored": "o",
    "cat_logged_pos": "+",
    "cat_logged_neg": "-",
    "focus": "(f)",
    "protect": "(p)",
    "skip": "(x)",
}


def icon(key: str) -> str:
    """Return the Unicode icon for *key*, falling back to ASCII if needed.

    Set the ``TUI_ASCII_ONLY`` environment variable to ``1``, ``true``,
    or ``yes`` to use ASCII fallbacks everywhere.
    """
    import os
    if os.environ.get("TUI_ASCII_ONLY", "").lower() in ("1", "true", "yes"):
        return ICON_ASCII.get(key, ICON.get(key, key))
    return ICON.get(key, key)


def spinner_frame(index: int) -> str:
    """Return a single braille spinner frame by index (wraps around)."""
    frames = ICON["spinner_frames"]
    return frames[index % len(frames)]


def spark_char(value: float, min_val: float, max_val: float) -> str:
    """Map a numeric value to a sparkline character (▁ through █).

    Returns one of ▁▂▃▄▅▆▇█ based on where *value* falls between
    *min_val* and *max_val*.
    """
    chars = ICON["spark_chars"]
    if max_val <= min_val:
        return chars[0]
    ratio = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    idx = min(len(chars) - 1, int(ratio * (len(chars) - 1) + 0.5))
    return chars[idx]


def fractional_bar(ratio: float) -> str:
    """Return a fractional block character for *ratio* (0.0-1.0).

    Uses ▏▎▍▌▋▊▉ for fractional portions and █ for full blocks.
    """
    fracs = ICON["bar_fractional"]
    if ratio >= 1.0:
        return "\u2588"
    if ratio <= 0.0:
        return ""
    idx = min(len(fracs) - 1, int(ratio * len(fracs)))
    return fracs[idx]


def intensity_block(ratio: float) -> str:
    """Map 0.0-1.0 to ·░▒▓█ intensity characters."""
    if ratio <= 0.05:
        return "\u00b7"
    if ratio <= 0.25:
        return "\u2591"
    if ratio <= 0.50:
        return "\u2592"
    if ratio <= 0.75:
        return "\u2593"
    return "\u2588"
