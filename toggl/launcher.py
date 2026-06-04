"""Terminal startup progress shown before the TUI alternate screen."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from toggl.const import BOLD, RED, RESET


def launch() -> None:
    """Show a Rich progress bar while loading, then start the TUI."""
    console = Console(stderr=True)

    # Pre-flight config safety check (before any TUI machinery starts)
    from toggl.services.backup import config_safety_check

    config_err = config_safety_check()
    if config_err:
        print(f"\n  {RED}{BOLD}Config error:{RESET} {config_err}", file=sys.stderr)
        sys.exit(1)

    try:
        with Progress(
            TextColumn("[bold #d7dde8]{task.description}"),
            BarColumn(
                bar_width=40,
                complete_style="#63f3ff",
                finished_style="#37d994",
                pulse_style="#63f3ff",
            ),
            TextColumn("[#63f3ff]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            expand=False,
        ) as progress:
            task = progress.add_task("Starting application...", total=100)

            progress.update(task, advance=15, description="Loading configuration...")
            from toggl.config import load_runtime_settings

            load_runtime_settings()

            progress.update(task, advance=25, description="Loading application...")
            from toggl.cache import DataCache
            from toggl.tui import TogglTUI

            progress.update(task, advance=35, description="Reading local data...")
            cache = DataCache.load()

            progress.update(task, completed=100, description="Starting TUI...")

        TogglTUI(preloaded_cache=cache).run()

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        from toggl.api import TogglAPIError, TogglRateLimitError

        if isinstance(exc, TogglRateLimitError):
            print(f"\n  {RED}{BOLD}{exc}{RESET}", file=sys.stderr)
            sys.exit(1)
        if isinstance(exc, TogglAPIError):
            print(f"\n  {RED}{exc}{RESET}", file=sys.stderr)
            sys.exit(1)
        raise
