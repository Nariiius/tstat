"""Playbook + Discoveries formatters and Insights tab widget.

Actionable daily insights with trend analysis.
"""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from toggl.services.insights_bundle import InsightsBundle
from toggl.services.playbook import Playbook, PlaybookStep
from toggl.services.discovery import Discovery

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


def _progress_bar(
    current: float, target: float, width: int = 12
) -> str:
    """Render a horizontal progress bar in Rich markup.

    Returns empty string when target is zero or negative.
    Colors shift from red → amber → green as progress increases.
    """
    if target <= 0:
        return ""
    ratio = min(abs(current) / abs(target), 1.0)
    filled = int(ratio * width)
    bar_fill = "━" * filled
    bar_empty = "─" * (width - filled)
    pct = int(ratio * 100)
    if ratio >= 0.8:
        color = CLR_GREEN
    elif ratio >= 0.5:
        color = CLR_AMBER
    else:
        color = CLR_RED
    return f"[{color}]{bar_fill}[/][{CLR_MUTED}]{bar_empty}[/] [{color}]{pct}%[/]"


def _status_badge(goal: str) -> str:
    """Coloured status badge for the current goal / verdict."""
    badges = {
        "on_track": f"[bold {CLR_GREEN}]◉ ON TRACK[/]",
        "hit_today_target": f"[bold {CLR_AMBER}]◉ CLOSE GAP[/]",
        "fix_week": f"[bold {CLR_RED}]◉ RECOVER WEEK[/]",
        "start_tracking": f"[{CLR_DIM}]◉ SETUP[/]",
    }
    return badges.get(goal, f"[{CLR_DIM}]◉ {goal}[/]")


def _section_sep() -> str:
    """Visual section separator."""
    return f"[{CLR_DIM}]──────────────────────[/]"


def _format_loading(base: str, progress_stage: str = "") -> str:
    """Render loading message with optional per-stage progress."""
    lines = [f"[{CLR_DIM}][bold]⏳[/] {base}[/]"]
    if progress_stage == "playbook":
        lines.append(f"[{CLR_DIM}]  ⠋ Analyzing activity data and generating playbook...[/]")
    elif progress_stage == "coach":
        lines.append(f"[{CLR_DIM}]  ⠋ Running coach analyzers to find patterns...[/]")
    return "\n".join(lines)


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


def _format_verdict(pb: Playbook) -> str:
    """Top-of-screen verdict: status + headline + context summary."""
    badge = _status_badge(pb.goal)
    headline = pb.headline
    lines: list[str] = []

    lines.append(f"  {badge}  {headline}")

    # Add a one-line context summary from available data
    ctx = pb.context
    context_bits: list[str] = []
    if "today_net" in ctx:
        context_bits.append(f"today {_fmt_pts(ctx['today_net'])}")
    if "daily_target" in ctx:
        context_bits.append(f"target {_fmt_pts(ctx['daily_target'])}")
    if "gap" in ctx and ctx["gap"] > 0:
        context_bits.append(f"gap {_fmt_pts(ctx['gap'])}")
    if "days_left" in ctx:
        context_bits.append(f"{ctx['days_left']}d left this week")
    if "week_delta" in ctx and ctx["week_delta"] != 0:
        context_bits.append(f"week {_fmt_pts(ctx['week_delta'])} vs pace")

    if context_bits:
        lines.append(f"  [{CLR_DIM}]{'  ·  '.join(context_bits)}[/]")

    return "\n".join(lines)


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
        lines.append(f"  [{CLR_FOCUS}]▸[/] {pb.focus_line}")
        lines.append("")

    # ── Today's steps ──
    steps = pb.steps[:max_steps] if max_steps is not None else pb.steps
    if steps:
        for i, step in enumerate(steps, 1):
            pts_str = f"[{CLR_GREEN}]{_fmt_pts(step.points)}[/]"
            nums = "①②③④⑤"
            num = nums[i-1] if i <= len(nums) else f"{i}."
            label = f"[bold]{step.label}[/]"
            amt = f" {step.amount}" if step.amount and step.amount != "×1" else ""
            step_line = f"  {num} {label}{amt}  {pts_str}"
            if not compact and step.points > 0:
                target = float(pb.context.get("gap", pb.context.get("daily_target", 0)) or 1)
                step_line += f"  {_progress_bar(step.points, target, width=6)}"
            lines.append(step_line)

        lines.append("")

    # ── Expected gain ──
    if pb.gap_note:
        lines.append(f"  [{CLR_DIM}]{pb.gap_note}[/]")
        lines.append("")

    # ── Done today ──
    if pb.done_today:
        done = ", ".join(pb.done_today)
        lines.append(f"  [{CLR_DIM}]✓ Done today:[/] {done}")

    # ── Blocked today ──
    if pb.blocked_today:
        for name, reason in pb.blocked_today:
            lines.append(f"  [{CLR_DIM}]◷ {name}:[/] {reason}")

    if pb.done_today or pb.blocked_today:
        lines.append("")

    # ── Low control ──
    if pb.low_control:
        for name, reason in pb.low_control:
            lines.append(f"  [{CLR_MUTED}]○ {name}:[/] {reason}")
        lines.append("")

    return "\n".join(lines) if lines else "[dim]No steps right now.[/]\n"


# ──────────────────────────────────────────────
# Public API — format functions called by TUI
# ──────────────────────────────────────────────


def format_overview_playbook(
    bundle: InsightsBundle | None,
    *,
    is_loading: bool = False,
    progress_stage: str = "",
) -> str:
    """Compact playbook for the Overview dashboard pane.

    Shows verdict + best 3 steps.
    Omits progress bars and lookback to fit the Overview's smaller space.
    """
    if is_loading:
        return _format_loading("Computing playbook...", progress_stage)
    if bundle is None or not bundle.playbook.headline:
        return "[dim]Playbook will appear after data loads.[/]"

    pb = bundle.playbook

    parts: list[str] = []
    parts.append(_format_verdict(pb))
    parts.append("\n")
    parts.append(_format_playbook_block(pb, include_math=False, compact=True, max_steps=6))

    return "".join(parts).strip()


def format_insights_tab(
    bundle: InsightsBundle | None,
    *,
    is_loading: bool = False,
    progress_stage: str = "",
) -> str:
    """Full detailed insights for the Insights tab.

    Layout: Verdict → Playbook → Discoveries
    Playbook shows 3 highest-leverage actions with pace improvement.
    Discoveries shows trend analysis (drift, growth, best period, failure modes).
    """
    if is_loading:
        return _format_loading("Computing insights...", progress_stage)
    if bundle is None:
        return "[dim]No insights yet.[/]"

    pb = bundle.playbook
    parts: list[str] = []

    # ── 1. Verdict ──
    parts.append(_format_verdict(pb))
    parts.append("\n")
    parts.append(_section_sep())

    # ── 2. Playbook ──
    parts.append("\n")
    parts.append(_format_playbook_block(pb, include_math=True, compact=False, max_steps=6))

    # ── 3. Discoveries ──
    if bundle.discoveries:
        parts.append(_section_sep())
        parts.append("\n\n")
        parts.append(format_discoveries(bundle.discoveries))
        parts.append("\n")

    return "".join(parts).strip()


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
        "drift":    ("\u2193 DRIFT",      CLR_RED),
        "growth":   ("\u2191 GROWTH",     CLR_GREEN),
        "best_gap": ("\u25c8 BEST PERIOD", CLR_AMBER),
        "failure":  ("\u26a0 PATTERN",    CLR_RED),
    }

    lines = [f"[bold {CLR_HEADER}]DISCOVERIES[/]\n"]

    for i, d in enumerate(discoveries, 1):
        label, color = KIND_META.get(d.kind, ("\u25c9", CLR_DIM))

        filled = int(d.confidence * 10)
        bar    = "\u2501" * filled + "\u2500" * (10 - filled)
        conf_color = (
            CLR_GREEN if d.confidence >= 0.85
            else CLR_AMBER if d.confidence >= 0.75
            else CLR_DIM
        )

        lines.append(
            f"[bold {color}]{label}[/]  [{conf_color}]{bar}[/] {d.confidence:.0%}"
        )
        lines.append(f"[bold white]{d.title.upper()}[/]")
        lines.append(f"[{CLR_DIM}]{d.summary}[/]")
        lines.append(f"[{CLR_MUTED}]{d.evidence}[/]")

        if i < len(discoveries):
            sep = "\u2500" * 36
            lines.append(f"\n[{CLR_MUTED}]{sep}[/]\n")

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
    """Bordered, vertically scrollable playbook/coach text."""

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
    """

    def compose(self):
        yield Static("", id="playbook-scroll-content", markup=True, expand=True)

    def on_mount(self) -> None:
        self.can_focus = True
        self.scroll_home(animate=False)

    def set_markup(
        self,
        content: str,
        *,
        border_title: str = "",
        border_subtitle: str = "",
    ) -> None:
        self.query_one("#playbook-scroll-content", Static).update(content)
        self.border_title = border_title
        self.border_subtitle = border_subtitle
        self.scroll_home(animate=False)


class DetailedInsightsWidget(PlaybookScrollPane):
    """Scrollable playbook + coach for the Insights tab."""

    def set_bundle(
        self,
        bundle: InsightsBundle | None,
        *,
        is_loading: bool = False,
        progress_stage: str = "",
    ) -> None:
        subtitle = ""
        if bundle and bundle.playbook.context.get("today_net") is not None:
            net = bundle.playbook.context["today_net"]
            subtitle = f"[{CLR_DIM}]Today {_fmt_pts(net)}[/]"
        self.set_markup(
            format_insights_tab(
                bundle,
                is_loading=is_loading,
                progress_stage=progress_stage,
            ),
            border_title=f"[bold {CLR_ACCENT}]Insights[/]",
            border_subtitle=subtitle,
        )
