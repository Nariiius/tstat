"""Playbook + Discoveries formatters and Insights tab widget.

Actionable daily insights with trend analysis.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.binding import Binding
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Static, Label

from toggl.services.insights_bundle import InsightsBundle
from toggl.services.playbook import Playbook, PlaybookStep
from toggl.services.discovery import Discovery
from toggl.services.coach import CoachFinding
from toggl.services.week_brief import WeekBrief, WeekAction
from toggl.widgets.icons import ICON, SEG_GAP, dot_sep
from toggl.widgets.loading import LoadingWidget, PulseText

_STAGE_LABELS = {
    "playbook": "Analyzing activity data and generating playbook...",
    "coach": "Running coach analyzers to find patterns...",
}

# ──────────────────────────────────────────────
# Progress, status, and visual helpers
# ──────────────────────────────────────────────

CLR_GREEN = "#37d994"
CLR_AMBER = "#ff9e3a"
CLR_RED = "#ff5f5f"
CLR_ACCENT = "#63f3ff"
CLR_DIM = "#8d98a7"
CLR_MUTED = "#4a5565"
CLR_FOCUS = "#e2b714"
CLR_MIST = "#1e2a36"
CLR_TRACK = "#7a9ec2"  # TODAY empty bar + need (colour 2)


def _confidence_bar(
    ratio: float,
    width: int = 12,
    *,
    bar_color: str | None = None,
) -> str:
    """Horizontal bar with fractional fill and percentage (discoveries, coach, etc.)."""
    ratio = max(0.0, min(1.0, ratio))
    if bar_color is None:
        if ratio >= 0.85:
            bar_color = CLR_GREEN
        elif ratio >= 0.75:
            bar_color = CLR_AMBER
        else:
            bar_color = CLR_DIM
    filled = max(0, min(width, int(round(ratio * width))))
    bar_fill = ICON["bar_filled"] * filled
    bar_empty = ICON["bar_empty"] * (width - filled)
    pct = int(ratio * 100)
    return (
        f"[bold {bar_color}]{bar_fill}[/]"
        f"[{CLR_MUTED}]{bar_empty}[/] "
        f"[{bar_color}]{pct}%[/]"
    )


def _status_badge(goal: str) -> str:
    """Coloured status badge for the current goal / verdict."""
    bullet = ICON["dot_fisheye"]
    badges = {
        "on_track": f"[bold {CLR_GREEN}]{bullet} ON TRACK[/]",
        "hit_today_target": f"[bold {CLR_AMBER}]{bullet} CLOSE GAP[/]",
        "fix_week": f"[bold {CLR_RED}]{bullet} RECOVER WEEK[/]",
        "start_tracking": f"[{CLR_DIM}]{bullet} SETUP[/]",
    }
    return badges.get(goal, f"[{CLR_DIM}]{bullet} {goal}[/]")


def _section_sep() -> str:
    """Visual section separator."""
    return f"[{CLR_DIM}]{ICON['sep_thin']}[/]"



def _confidence_tag(confidence: float) -> str:
    """Short confidence indicator tag."""
    if confidence >= 0.8:
        return f"[{CLR_GREEN}]high[/]"
    elif confidence >= 0.6:
        return f"[{CLR_AMBER}]med[/]"
    return f"[{CLR_DIM}]low[/]"


def _fmt_pts(value: float) -> str:
    """Formatted signed point value."""
    if value >= 0:
        return f"+{value:.1f}"
    return f"{value:.1f}"


# ──────────────────────────────────────────────
# Section headers
# ──────────────────────────────────────────────


def _section_title(title: str, *, subtitle: str | None = None) -> str:
    """Section header in accent colour with optional subtitle."""
    if subtitle:
        return f"[bold {CLR_ACCENT}]{title}[/]  [{CLR_DIM}]{subtitle}[/]"
    return f"[bold {CLR_ACCENT}]{title}[/]"


# ──────────────────────────────────────────────
# Verdict block (always shown at the top)
# ──────────────────────────────────────────────


def _format_verdict_summary_line(pb: Playbook) -> str:
    """One-line context summary (compact overview)."""
    ctx = pb.context
    bits: list[str] = []
    if "today_net" in ctx:
        bits.append(f"today {_fmt_pts(ctx['today_net'])}")
    if "daily_target" in ctx:
        bits.append(f"target {_fmt_pts(ctx['daily_target'])}")
    if ctx.get("gap", 0) > 0:
        bits.append(f"gap {_fmt_pts(ctx['gap'])}")
    if "days_left" in ctx:
        bits.append(f"{ctx['days_left']}d left this week")
    if ctx.get("week_delta", 0) != 0:
        bits.append(f"week {_fmt_pts(ctx['week_delta'])} vs pace")
    return dot_sep(pad="  ").join(bits)


def _format_verdict(pb: Playbook, *, include_summary: bool = False) -> str:
    """Verdict for scroll content (overview) or border (insights)."""
    badge = _status_badge(pb.goal)
    headline = pb.headline
    lines: list[str] = [f"  {badge}  {headline}"]
    if include_summary:
        summary = _format_verdict_summary_line(pb)
        if summary:
            lines.append(f"  [{CLR_DIM}]{summary}[/]")
    return "\n".join(lines)


_BORDER_GOAL_LABELS = {
    "on_track": ("ON TRACK", CLR_GREEN),
    "hit_today_target": ("CLOSE GAP", CLR_AMBER),
    "fix_week": ("RECOVER WEEK", CLR_RED),
    "start_tracking": ("SETUP", CLR_DIM),
}


def _format_verdict_border(pb: Playbook) -> str:
    """Status for top border on the Today sub-view."""
    label, color = _BORDER_GOAL_LABELS.get(pb.goal, (pb.goal, CLR_DIM))
    bullet = ICON["dot_fisheye"]
    return f"[bold {color}]{bullet} {label}[/]"


def _format_week_verdict_border(pb: Playbook) -> str:
    """Status for top border on the Week sub-view (pace-based, not daily goal)."""
    delta = float(pb.context.get("week_delta", 0))
    if delta >= 0.5:
        label, color = "ON PACE", CLR_GREEN
    elif delta < -0.5:
        label, color = "RECOVER", CLR_RED
    else:
        label, color = "CLOSE", CLR_AMBER
    bullet = ICON["dot_fisheye"]
    return f"[bold {color}]{bullet} {label}[/]"


def _pace_border_chips(pb: Playbook) -> dict[str, str]:
    """PACE segments keyed by label (TODAY, GAP, TIME, WEEK)."""
    ctx = pb.context
    target = float(ctx.get("daily_target") or 0)
    today_net = float(ctx.get("today_net", 0))
    gap = float(ctx.get("gap") or 0)
    days_left = int(ctx.get("days_left") or 0)
    week_delta = float(ctx.get("week_delta") or 0)
    chips: dict[str, str] = {}

    if target > 0:
        ratio = max(0.0, min(today_net / target, 1.0))
        color = (
            CLR_GREEN if today_net >= target * 0.8
            else CLR_AMBER if today_net >= 0
            else CLR_RED
        )
        chips["TODAY"] = (
            f"[bold {color}]TODAY[/] {_confidence_bar(ratio, width=6, bar_color=color)}"
            f" [{color}]{_fmt_pts(today_net)}[/][{CLR_DIM}]/{_fmt_pts(target)}[/]"
        )

    if days_left >= 0:
        ratio = min(days_left / 7.0, 1.0)
        chips["TIME"] = (
            f"[bold {CLR_ACCENT}]TIME[/] "
            f"{_confidence_bar(ratio, width=6, bar_color=CLR_ACCENT)}"
            f" [{CLR_ACCENT}]{days_left}d left[/]"
        )

    if week_delta != 0:
        scale = max(abs(week_delta), target * 3, 20.0)
        ratio = min(abs(week_delta) / scale, 1.0)
        color = CLR_GREEN if week_delta >= 0 else CLR_RED
        chips["WEEK"] = (
            f"[bold {color}]WEEK[/] {_confidence_bar(ratio, width=6, bar_color=color)}"
            f" [{color}]{_fmt_pts(week_delta)}[/] [{CLR_DIM}]vs pace[/]"
        )

    return chips


def _format_pace_border_line(
    pb: Playbook,
    *labels: str,
    chip_gap: str = SEG_GAP,
) -> str:
    """Join selected PACE chips for a border row."""
    chips = _pace_border_chips(pb)
    parts = [chips[label] for label in labels if label in chips]
    return chip_gap.join(parts)


def _today_border_bar(
    ratio: float,
    width: int,
    *,
    fill_color: str,
    track_color: str,
) -> str:
    """Progress bar for border: fill + % in *fill_color*, empty track in *track_color*."""
    ratio = max(0.0, min(1.0, ratio))
    filled = max(0, min(width, int(round(ratio * width))))
    bar_fill = ICON["bar_filled"] * filled
    bar_empty = ICON["bar_empty"] * (width - filled)
    pct = int(ratio * 100)
    return (
        f"[bold {fill_color}]{bar_fill}[/]"
        f"[{track_color}]{bar_empty}[/] "
        f"[{fill_color}]{pct}%[/]"
    )


def _format_today_gap_combined(pb: Playbook) -> str:
    """TODAY chip: colour-1 progress, green target, colour-2 remainder + need."""
    ctx = pb.context
    target = float(ctx.get("daily_target") or 0)
    today_net = float(ctx.get("today_net", 0))
    gap = float(ctx.get("gap") or 0)
    if target <= 0:
        return ""

    progress = max(0.0, min(today_net / target, 1.0))
    if today_net >= target:
        fill_color = CLR_GREEN
    elif today_net >= target * 0.8:
        fill_color = CLR_AMBER
    elif today_net >= 0:
        fill_color = CLR_AMBER
    else:
        fill_color = CLR_RED
    track_color = CLR_TRACK

    bar = _today_border_bar(
        progress, 10, fill_color=fill_color, track_color=track_color,
    )
    stats = (
        f" [{fill_color}]{_fmt_pts(today_net)}[/]"
        f"[{CLR_GREEN}]/{_fmt_pts(target)}[/]"
    )
    if gap > 0:
        stats += f" [{track_color}]· Need {_fmt_pts(gap)}[/]"
    elif today_net >= target:
        stats += f" [{CLR_GREEN}]· met[/]"

    return f"[bold {fill_color}]TODAY[/] {bar}{stats}"


def _format_week_combined(pb: Playbook) -> str:
    """Week pace bar for border: WEEK label + bar (verdict is separate, e.g. RECOVER)."""
    ctx = pb.context
    expected = float(ctx.get("week_expected") or 0)
    actual = float(ctx.get("week_actual", 0))
    delta = float(ctx.get("week_delta", 0))
    need = round(-delta, 1) if delta < -0.01 else 0.0
    if expected <= 0:
        return ""

    progress = max(0.0, min(actual / expected, 1.0))
    if delta >= 0.5:
        fill_color = CLR_GREEN
    elif delta >= -0.5:
        fill_color = CLR_AMBER
    else:
        fill_color = CLR_RED
    track_color = CLR_TRACK

    bar = _today_border_bar(
        progress, 10, fill_color=fill_color, track_color=track_color,
    )
    stats = (
        f" [{fill_color}]{_fmt_pts(actual)}[/]"
        f"[{CLR_GREEN}]/{_fmt_pts(expected)}[/]"
    )
    if need > 0:
        stats += f" [{track_color}]· Need {_fmt_pts(need)}[/]"
    elif delta >= 0:
        stats += f" [{CLR_GREEN}]· met[/]"

    return f"[bold {fill_color}]WEEK[/] {bar}{stats}"


def _border_verdict_for_subview(pb: Playbook, subview_index: int) -> str:
    view = INSIGHT_VIEWS[subview_index]
    if view == "week":
        return _format_week_verdict_border(pb)
    return _format_verdict_border(pb)


def _border_pace_for_subview(pb: Playbook, subview_index: int) -> str:
    view = INSIGHT_VIEWS[subview_index]
    if view == "today":
        return _format_today_gap_combined(pb)
    if view == "week":
        return _format_week_combined(pb)
    return ""


def _format_insights_border_title(pb: Playbook, *, subview_index: int = 0) -> str:
    """Top border: sub-views | sub-view verdict | TODAY or WEEK progress."""
    title = _format_insights_subview_nav(subview_index)
    if INSIGHT_VIEWS[subview_index] == "patterns":
        return title
    title = (
        f"{title}"
        f"[{CLR_DIM}] | [/]"
        f"{_border_verdict_for_subview(pb, subview_index)}"
    )
    pace = _border_pace_for_subview(pb, subview_index)
    if pace:
        title = f"{title}[{CLR_DIM}] | [/]{pace}"
    return title


def _format_insights_border_subtitle_full(
    pb: Playbook, *, subview_index: int = 0,
) -> str:
    """Bottom border: TIME (and WEEK chip on Today view only)."""
    if INSIGHT_VIEWS[subview_index] == "patterns":
        return ""
    view = INSIGHT_VIEWS[subview_index]
    if view == "today":
        return _format_pace_border_line(pb, "TIME", "WEEK", chip_gap=SEG_GAP * 4)
    return _format_pace_border_line(pb, "TIME", chip_gap=SEG_GAP * 4)


def _format_insights_border_subtitle(pb: Playbook) -> str:
    """Bottom border: TIME + WEEK (remaining PACE)."""
    return _format_pace_border_line(
        pb, "TIME", "WEEK", chip_gap=SEG_GAP * 4,
    )


def _format_pace_border_subtitle(pb: Playbook) -> str:
    """Backward-compatible alias for tests."""
    return _format_insights_border_subtitle(pb)


# ──────────────────────────────────────────────
# Playbook formatter
# ──────────────────────────────────────────────


def _format_playbook_block(
    pb: Playbook, *, include_math: bool, compact: bool = False,
    max_steps: int | None = None,
) -> str:
    """Render the playbook section.

    *compact* mode (used in Overview) omits progress bars and extra detail.
    *max_steps* caps how many steps to display (None = all).
    """
    lines: list[str] = []

    # ── Focus line (most important) ──
    if pb.focus_line and not compact:
        lines.append(f"  [{CLR_FOCUS}]{ICON['focus_pointer']}[/] {pb.focus_line}")
        lines.append("")

    # ── Today's steps ──
    steps = pb.steps[:max_steps] if max_steps is not None else pb.steps
    if steps:
        for i, step in enumerate(steps, 1):
            pts_str = f"[{CLR_GREEN}]{_fmt_pts(step.points)}[/]"
            nums = ICON["num_circled"]
            num = nums[i-1] if i <= len(nums) else f"{i}."
            label = f"[bold]{step.label}[/]"
            amt = f" {step.amount}" if step.amount and step.amount != ICON["multiply"] + "1" else ""
            step_line = f"  {num} {label}{amt}  {pts_str}"
            if not compact and step.points > 0:
                gap = float(pb.context.get("gap") or pb.context.get("daily_target") or 0)
                if gap > 0:
                    step_line += f"  {_confidence_bar(min(step.points / gap, 1.0), width=8)}"
            lines.append(step_line)
            if step.reason and not compact:
                lines.append(f"    [{CLR_DIM}]{step.reason}[/]")

        # ── Alternatives (also consider) ──
        if pb.alternatives and not compact:
            alt_names = ", ".join(a.label for a in pb.alternatives[:3])
            lines.append(f"  [{CLR_MUTED}]Also consider:[/] {alt_names}")

        lines.append("")

    # ── Lookback (yesterday + patterns) ──
    if pb.lookback and not compact:
        for lb in pb.lookback:
            lines.append(f"  [{CLR_DIM}]{lb}[/]")
        lines.append("")

    # ── Expected gain ──
    if pb.gap_note:
        lines.append(f"  [{CLR_DIM}]{pb.gap_note}[/]")
        lines.append("")

    # ── Done today ──
    if pb.done_today:
        done = ", ".join(pb.done_today)
        lines.append(f"  [{CLR_DIM}]{ICON['check']} Done today:[/] {done}")

    # ── Blocked today ──
    if pb.blocked_today:
        for name, reason in pb.blocked_today:
            lines.append(f"  [{CLR_DIM}]{ICON['blocked']} {name}:[/] {reason}")

    if pb.done_today or pb.blocked_today:
        lines.append("")

    # ── Low control ──
    if pb.low_control:
        for name, reason in pb.low_control:
            lines.append(f"  [{CLR_MUTED}]{ICON['low_control']} {name}:[/] {reason}")
        lines.append("")

    return "\n".join(lines) if lines else "[dim]No steps right now.[/]\n"


# ──────────────────────────────────────────────
# Public API — format functions called by TUI
# ──────────────────────────────────────────────


def format_overview_playbook(
    bundle: InsightsBundle | None,
) -> str:
    """Compact playbook for the Overview dashboard pane.

    Shows verdict + best 3 steps.
    Omits progress bars and lookback to fit the Overview's smaller space.
    """
    if bundle is None or not bundle.playbook.headline:
        return "[dim]Playbook will appear after data loads.[/]"

    pb = bundle.playbook

    parts: list[str] = []
    parts.append(_format_verdict(pb, include_summary=True))
    parts.append("\n")
    parts.append(_format_playbook_block(pb, include_math=False, compact=True, max_steps=6))

    return "".join(parts).strip()


INSIGHT_VIEWS: tuple[str, ...] = ("today", "week", "patterns")
INSIGHT_VIEW_LABELS: tuple[str, ...] = ("Today", "Week", "Patterns")


def format_insights_today(bundle: InsightsBundle | None) -> str:
    """Today's playbook — steps, reasons, lookback (no section dividers)."""
    if bundle is None:
        return "[dim]No insights yet.[/]"
    pb = bundle.playbook
    body = _format_playbook_block(pb, include_math=True, compact=False, max_steps=6)
    return body.strip() or "[dim]No steps right now.[/]"


def format_insights_week(bundle: InsightsBundle | None) -> str:
    """Week brief — Focus / Protect / Skip (view title is in the border)."""
    if bundle is None:
        return "[dim]No insights yet.[/]"
    wb = bundle.week_brief
    if not (wb.headline or wb.focus or wb.protect or wb.skip):
        return "[dim]No week plan for this period yet.[/]"
    return format_week_brief(wb, show_title=False, show_headline=False).strip()


def format_insights_patterns(bundle: InsightsBundle | None) -> str:
    """Discoveries + coach findings (no horizontal rule dividers)."""
    if bundle is None:
        return "[dim]No insights yet.[/]"
    if not bundle.discoveries and not bundle.coach_findings:
        return "[dim]No patterns surfaced yet.[/]"
    parts: list[str] = []
    if bundle.discoveries:
        parts.append(format_discoveries(bundle.discoveries))
    if bundle.coach_findings:
        if parts:
            parts.append("")
        parts.append(format_coach_findings(bundle.coach_findings))
    return "\n".join(parts).strip()


def format_insights_tab(
    bundle: InsightsBundle | None,
) -> str:
    """All insight sub-views joined (used by tests and legacy callers)."""
    if bundle is None:
        return "[dim]No insights yet.[/]"
    chunks = [
        format_insights_today(bundle),
        format_insights_week(bundle),
        format_insights_patterns(bundle),
    ]
    return "\n\n".join(c for c in chunks if c and not c.startswith("[dim]No"))


def _format_insights_subview_nav(active_index: int) -> str:
    """Inline sub-view labels for the border (no rule dividers)."""
    parts: list[str] = []
    for i, label in enumerate(INSIGHT_VIEW_LABELS):
        if i == active_index:
            parts.append(f"[bold {CLR_ACCENT}]{label}[/]")
        else:
            parts.append(f"[{CLR_DIM}]{label}[/]")
    return dot_sep(pad=" ").join(parts)


def _insights_content_for_view(
    bundle: InsightsBundle | None, view: str,
) -> str:
    formatters: dict[str, Callable[[InsightsBundle | None], str]] = {
        "today": format_insights_today,
        "week": format_insights_week,
        "patterns": format_insights_patterns,
    }
    return formatters.get(view, format_insights_today)(bundle)


def format_week_brief(
    wb: WeekBrief,
    *,
    show_title: bool = True,
    show_headline: bool = True,
) -> str:
    """Render the Week Brief (Focus / Protect / Skip) as Rich markup."""
    if not wb.headline and not (wb.focus or wb.protect or wb.skip):
        return ""

    lines: list[str] = []
    if show_title:
        lines.append(f"[bold {CLR_ACCENT}]THIS WEEK[/]  [{CLR_DIM}]{wb.headline}[/]")
    elif show_headline and wb.headline:
        lines.append(f"[{CLR_DIM}]{wb.headline}[/]")
    if lines:
        lines.append("")

    def _action_lines(actions: list[WeekAction], label: str, color: str) -> list[str]:
        out: list[str] = []
        if not actions:
            return out
        out.append(f"[bold {color}]{label}[/]")
        for a in actions:
            out.append(f"  [{CLR_DIM}]{ICON['bullet']}[/] {a.imperative}")
            if a.evidence:
                out.append(f"    [{CLR_MUTED}]{a.evidence}[/]")
        out.append("")
        return out

    lines.extend(_action_lines(wb.focus, f"  {ICON['focus']} FOCUS", CLR_GREEN))
    lines.extend(_action_lines(wb.protect, f"  {ICON['protect']} PROTECT", CLR_AMBER))
    lines.extend(_action_lines(wb.skip, f"  {ICON['skip']} SKIP", CLR_RED))

    return "\n".join(lines).rstrip()


def format_discoveries(discoveries: list[Discovery]) -> str:
    """Render discoveries as Rich markup."""
    if not discoveries:
        return ""

    CLR_HEADER = "#63f3ff"
    CLR_RED    = "#ff5f5f"
    CLR_GREEN  = "#37d994"
    CLR_AMBER  = "#ff9e3a"
    CLR_DIM    = "#8d98a7"
    CLR_MUTED  = "#4a5565"

    KIND_META = {
        "failure_mode":       (f"{ICON['warning']} FAILURE",       CLR_RED),
        "positive_driver":    (f"{ICON['star']} POSITIVE DRIVER", CLR_GREEN),
        "neglect":            (f"{ICON['neglect']} NEGLECT",        CLR_AMBER),
        "trajectory_change":  (f"{ICON['trajectory_up']} TRAJECTORY",      CLR_AMBER),
        "best_period_gap":    (f"{ICON['diamond']} BEST PERIOD",     CLR_AMBER),
    }

    lines = []

    for i, d in enumerate(discoveries, 1):
        label, color = KIND_META.get(d.kind, (ICON["dot"], CLR_DIM))
        conf_color = (
            CLR_GREEN if d.confidence >= 0.85
            else CLR_AMBER if d.confidence >= 0.75
            else CLR_DIM
        )

        lines.append(
            f"[bold {color}]{label}[/]  {_confidence_bar(d.confidence, bar_color=conf_color)}"
        )
        lines.append(f"[bold white]{d.title.upper()}[/]")
        lines.append(f"[{CLR_DIM}]{d.summary}[/]")
        lines.append(f"[{CLR_MUTED}]{d.evidence}[/]")

        if i < len(discoveries):
            lines.append("")

    return "\n".join(lines)


def format_coach_findings(findings: list[CoachFinding]) -> str:
    """Render coach (personal baseline analysis) findings as Rich markup."""
    if not findings:
        return ""

    KIND_META = {
        "frequency_drop":    (f"{ICON['frequency_drop']} FREQUENCY DROP",  CLR_RED),
        "frequency_surge":   (f"{ICON['on_a_roll']} ON A ROLL",       CLR_GREEN),
        "streak_gap":        (f"{ICON['gap_reminder']} GAP REMINDER",    CLR_AMBER),
        "negative_cluster":  (f"{ICON['warning']} PATTERN",         CLR_RED),
        "positive_lift":     (f"{ICON['star']} POSITIVE LIFT",   CLR_GREEN),
    }

    lines = []

    for i, f in enumerate(findings, 1):
        label, color = KIND_META.get(f.kind, (ICON["low_control"], CLR_DIM))
        conf_color = (
            CLR_GREEN if f.confidence >= 0.85
            else CLR_AMBER if f.confidence >= 0.75
            else CLR_DIM
        )

        lines.append(
            f"[bold {color}]{label}[/]  {_confidence_bar(f.confidence, bar_color=conf_color)}"
        )
        lines.append(f"[bold white]{f.title.upper()}[/]")
        lines.append(f"[{CLR_DIM}]{f.summary}[/]")

        if i < len(findings):
            lines.append("")

    return "\n".join(lines)


def format_command_playbook_line(bundle: InsightsBundle | None) -> str | None:
    """One-line playbook for Command month subtitle."""
    if bundle is None:
        return None
    pb = bundle.playbook
    if not pb.steps:
        return pb.headline[:80] if pb.headline else None
    step_bits = []
    for s in pb.steps[:3]:
        if s.action == "log":
            step_bits.append(f"Log {s.label}")
        else:
            step_bits.append(f"{s.amount} {s.label}")
    joined = ", ".join(step_bits)
    line = f"{pb.headline} — {joined}"
    return line[:120] + ("…" if len(line) > 120 else "")


# ──────────────────────────────────────────────
# TUI widgets
# ──────────────────────────────────────────────


class PlaybookScrollPane(VerticalScroll):
    """Bordered, vertically scrollable playbook/coach text.

    Shows an animated spinner + pulsing stage text while loading,
    then switches to static Rich markup content once data arrives.
    """

    DEFAULT_CSS = """
    PlaybookScrollPane {
        height: 1fr;
        min-height: 8;
        border: round #3d4f63;
        padding: 0 1;
        background: #0b1016;
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #3d4f63;
        scrollbar-background: #0b1016;
    }
    PlaybookScrollPane:focus {
        border: round #63f3ff;
    }
    PlaybookScrollPane > Static {
        width: 1fr;
        height: auto;
        padding: 0 0 1 0;
        background: transparent;
        border: none;
    }
    PlaybookScrollPane > #playbook-loading-area {
        align: center middle;
        width: 1fr;
        height: auto;
        padding: 2 0;
    }
    """

    def compose(self):
        yield Static("", id="playbook-scroll-content", markup=True, expand=True)
        with Vertical(id="playbook-loading-area"):
            yield LoadingWidget("Computing...")
            yield PulseText("")

    def set_loading(self, base: str, stage: str = "") -> None:
        """Show the animated spinner and pulsing stage text.

        *base* is shown beside the spinner; *stage* appears as
        pulsing text below it (mapped via ``_STAGE_LABELS``).
        """
        content = self.query_one("#playbook-scroll-content", Static)
        content.display = False
        stage_text = _STAGE_LABELS.get(stage, stage)
        try:
            self.query_one("#playbook-loading-area").display = True
            self.query_one("#loading-label", Label).update(base)
            self.query_one("#loading-label", Label).display = bool(base)
            stage_label = self.query_one(PulseText)
            stage_label.update(stage_text)
            stage_label.display = bool(stage_text)
        except Exception:
            pass

    def _hide_loading(self) -> None:
        """Hide animated widgets and show the static content area."""
        try:
            self.query_one("#playbook-loading-area").display = False
        except Exception:
            pass

    def on_mount(self) -> None:
        self.can_focus = True
        self.scroll_home(animate=False)
        self._hide_loading()

    def set_markup(
        self,
        content: str,
        *,
        border_title: str = "",
        border_subtitle: str = "",
    ) -> None:
        self._hide_loading()
        content_widget = self.query_one("#playbook-scroll-content", Static)
        content_widget.display = True
        content_widget.update(content)
        self.border_title = border_title
        self.border_subtitle = border_subtitle
        self.scroll_home(animate=False)


class DetailedInsightsWidget(PlaybookScrollPane):
    """Insights tab — Today / Week / Patterns (←/→ in border)."""

    BINDINGS = [
        Binding("left", "insights_prev", "Prev view", show=False),
        Binding("right", "insights_next", "Next view", show=False),
    ]

    DEFAULT_CSS = """
    DetailedInsightsWidget {
        border-title-align: left;
        border-subtitle-align: right;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._view_index = 0
        self._bundle: InsightsBundle | None = None

    def action_insights_prev(self) -> None:
        self._set_view((self._view_index - 1) % len(INSIGHT_VIEWS))

    def action_insights_next(self) -> None:
        self._set_view((self._view_index + 1) % len(INSIGHT_VIEWS))

    def _set_view(self, index: int) -> None:
        self._view_index = index
        if self._bundle is not None:
            self._show_bundle(self._bundle)

    def _show_bundle(self, bundle: InsightsBundle) -> None:
        pb = bundle.playbook
        view = INSIGHT_VIEWS[self._view_index]
        self.set_markup(
            _insights_content_for_view(bundle, view),
            border_title=_format_insights_border_title(
                pb, subview_index=self._view_index,
            ),
            border_subtitle=_format_insights_border_subtitle_full(
                pb, subview_index=self._view_index,
            ),
        )

    def set_bundle(
        self,
        bundle: InsightsBundle | None,
        *,
        is_loading: bool = False,
        progress_stage: str = "",
    ) -> None:
        self._bundle = bundle
        if is_loading:
            self.set_loading("Computing insights...", progress_stage)
            self.border_title = _format_insights_subview_nav(self._view_index)
            self.border_subtitle = ""
            return

        if bundle is None:
            self.set_markup(
                "[dim]No insights yet.[/]",
                border_title="",
                border_subtitle="",
            )
            return

        self._show_bundle(bundle)
