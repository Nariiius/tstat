"""Stats tables widget — category summary and daily breakdown.

Extracted from ``CommandTab`` to make the tab a thinner UI coordinator.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from rich.text import Text as RichText
from textual.widgets import DataTable

from toggl.cache import DataCache, get_week_str
from toggl.formatters import format_signed_rich, build_category_rows
from toggl.services.metrics import MetricsService
from toggl.state.period import PeriodController


class CategoryTable(DataTable):
    """Category summary table showing project breakdown."""

    def on_mount(self) -> None:
        self.add_columns("Category", "Hours", "Rate", "Points")
        self.styles.min_height = 1
        self.show_cursor = True

    def refresh_data(self, cache: DataCache, period: PeriodController, start: date, end: date) -> None:
        self.clear(columns=False)
        agg = cache.get_range_aggregate(start, end)

        mode = period.mode
        if mode == "day":
            suffix = start.strftime("%a %-d %b")
        elif mode == "week":
            wk = get_week_str(start)
            suffix = f"W{int(wk.split('W')[1])} {start.year}"
        else:
            suffix = start.strftime("%b %Y")

        self.border_title = f"[b][#63f3ff]{suffix}[/][/]"

        svc = MetricsService(cache)
        period_nets = svc.compute_period_nets(start, end, mode)
        subtitle = period_nets.get("subtitle", "Insights coming soon")
        self.border_subtitle = f"[#8d98a7]{subtitle}[/]"

        rows = build_category_rows(agg)
        self.add_rows(rows)


class DailyBreakdownTable(DataTable):
    """Daily/weekly/monthly breakdown table."""

    def on_mount(self) -> None:
        self.add_columns("Date", "Positive", "Negative", "Net")
        self.styles.min_height = 1
        self.show_cursor = True

    def refresh_data(self, cache: DataCache, period: PeriodController, daily_data: list[dict[str, Any]]) -> None:
        self.clear(columns=False)

        title_map = {"day": "Daily", "week": "Weekly", "month": "Monthly"}
        title_word = title_map.get(period.mode, "Daily")
        self.border_title = f"[b][#63f3ff]{title_word} Breakdown[/][/]"

        svc = MetricsService(cache)
        aggregated = svc.get_daily_breakdown(daily_data, period.mode)

        for i, item in enumerate(aggregated):
            positive = item["positive"]
            negative = item["negative"]
            net = item["net"]
            has_data = item["has_data"]
            is_today = item["contains_today"]
            label = item["label"]

            if is_today:
                date_cell = f"[bold #e2b714]{label} \u25c0[/]"
            elif not has_data:
                date_cell = f"[dim]{label}[/]"
            else:
                date_cell = label

            pos_text = "\u2014" if positive == 0 else f"[#37d994]+{positive:.1f}[/]"
            neg_text = "\u2014" if negative == 0 else f"[#ff5f5f]-{negative:.1f}[/]"

            self.add_row(
                RichText.from_markup(date_cell),
                RichText.from_markup(pos_text),
                RichText.from_markup(neg_text),
                format_signed_rich(net),
                key=str(i),
            )
