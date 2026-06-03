"""Insights formatting and scroll pane behavior."""

from __future__ import annotations

import pytest
from rich.text import Text
from toggl.cache import DataCache
from toggl.activity_rules import ActivityRules
from toggl.config import Config
from toggl.services.insights_bundle import InsightsBundleService
from toggl.services.metrics import MetricsService
from toggl.widgets.insights import (
    PlaybookScrollPane,
    format_insights_tab,
    format_overview_playbook,
)


def _bundle_svc(tmp_data_dir, sample_daily_csv, sample_config):
    cache = DataCache.load()
    import toggl.config as cfg_mod
    metrics = MetricsService(
        cache,
        cfg_mod.POINTS,
        cfg_mod.NEGATIVES,
        cfg_mod.POSITIVES,
        [],
        lambda: 13.0,
    )
    cfg = Config(
        cfg_mod.POINTS,
        cfg_mod.NEGATIVES,
        cfg_mod.POSITIVES,
        13.0,
        cfg_mod.RATE_COLORS,
        cfg_mod.CATEGORY_REGISTRY,
        [],
        cfg_mod.ACTIVITY_RULES,
    )
    return InsightsBundleService(metrics, cache, cfg, lambda: 13.0)


def test_insights_tab_markup_parses(tmp_data_dir, sample_daily_csv, sample_config):
    bundle = _bundle_svc(tmp_data_dir, sample_daily_csv, sample_config).compute()
    markup = format_insights_tab(bundle)
    Text.from_markup(markup)
    assert "completed" in markup.lower() and "pace" in markup.lower()


def test_overview_playbook_markup_parses(tmp_data_dir, sample_daily_csv, sample_config):
    bundle = _bundle_svc(tmp_data_dir, sample_daily_csv, sample_config).compute()
    markup = format_overview_playbook(bundle)
    Text.from_markup(markup)
    assert "completed" in markup.lower() and "pace" in markup.lower()


def test_playbook_scroll_pane_scrolls_when_short():
    """Tall content in a short pane must expose vertical scroll range."""
    import asyncio

    from textual.app import App, ComposeResult

    class ScrollApp(App):
        CSS = """
        Screen { align: center middle; }
        #pane { width: 40; height: 8; }
        """

        def compose(self) -> ComposeResult:
            yield PlaybookScrollPane(id="pane")

        def on_mount(self) -> None:
            pane = self.query_one("#pane", PlaybookScrollPane)
            pane.set_markup("\n".join(f"Line {i}" for i in range(40)))

    async def _run() -> int:
        app = ScrollApp()
        async with app.run_test(size=(50, 12)) as pilot:
            pane = pilot.app.query_one("#pane", PlaybookScrollPane)
            await pilot.pause()
            return pane.max_scroll_y

    assert asyncio.run(_run()) > 0
