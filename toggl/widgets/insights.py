"""Playbook + Coach formatters and Insights tab widget."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from toggl.services.insights_bundle import InsightsBundle
from toggl.services.playbook import Playbook, PlaybookStep


def format_overview_playbook(
    bundle: InsightsBundle | None,
    *,
    is_loading: bool = False,
) -> str:
    if is_loading:
        return "[dim]Computing playbook...[/]"
    if bundle is None or not bundle.playbook.headline:
        return "[dim]Playbook will appear after data loads.[/]"
    return _format_playbook_block(bundle.playbook, include_math=False)


def format_insights_tab(
    bundle: InsightsBundle | None,
    *,
    is_loading: bool = False,
) -> str:
    if is_loading:
        return "[dim]Computing insights...[/]"
    if bundle is None:
        return "[dim]No insights yet.[/]"

    parts: list[str] = []
    parts.append(_format_playbook_block(bundle.playbook, include_math=True))

    if bundle.coach.findings:
        parts.append("\n")
        parts.append(_section_title("Coach", subtitle="from your recent days"))
        for finding in bundle.coach.findings:
            parts.append(f"\n  · {finding.text}")

    return "".join(parts).strip()


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


def _section_title(title: str, *, subtitle: str | None = None) -> str:
    if subtitle:
        return f"[b][#63f3ff]{title}[/][/] [dim]({subtitle})[/]"
    return f"[b][#63f3ff]{title}[/][/]"


def _format_playbook_block(pb: Playbook, *, include_math: bool) -> str:
    lines: list[str] = []
    lines.append(_section_title("Playbook"))
    lines.append("")

    if pb.lookback:
        lines.append("[#8d98a7][b]Recent[/][/]")
        for line in pb.lookback:
            lines.append(f"  {line}")
        lines.append("")

    if pb.focus_line:
        lines.append(f"[#e2b714][b]Focus[/][/]  {pb.focus_line}")
        lines.append("")

    lines.append("[#8d98a7][b]Today[/][/]")
    lines.append(f"  {pb.headline}")

    if pb.steps:
        lines.append("")
        lines.append("[#8d98a7][b]Steps[/][/]")
        for i, step in enumerate(pb.steps, 1):
            verb = "Log" if step.action == "log" else "Track"
            lines.append(
                f"  {i}. {verb} [bold]{step.label}[/] {step.amount}  "
                f"[#37d994]{_fmt_pts(step.points)}[/]"
            )
            if include_math and step.reason:
                lines.append(f"     [dim]{step.reason}[/]")

    if pb.done_today:
        done = ", ".join(pb.done_today)
        lines.append("")
        lines.append(f"[dim]Done today:[/] {done}")

    if pb.gap_note:
        if include_math:
            lines.append(f"[dim]{pb.gap_note}[/]")
        else:
            short = pb.gap_note.split("—")[0].strip()
            if short:
                lines.append(f"[dim]{short}[/]")

    return "\n".join(lines) if lines else "[dim]No steps right now.[/]\n"


def _fmt_pts(value: float) -> str:
    if value >= 0:
        return f"+{value:.1f}"
    return f"{value:.1f}"


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
    ) -> None:
        subtitle = ""
        if bundle and bundle.playbook.context.get("today_net") is not None:
            net = bundle.playbook.context["today_net"]
            subtitle = f"[#8d98a7]Today {_fmt_pts(net)}[/]"
        self.set_markup(
            format_insights_tab(bundle, is_loading=is_loading),
            border_title="[b][#63f3ff]Insights[/][/]",
            border_subtitle=subtitle,
        )
