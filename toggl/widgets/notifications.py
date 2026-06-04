"""Bottom status bar messages — replaces toast notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from textual.app import App

SeverityLevel = Literal["information", "warning", "error"]


def _app_root(app: App) -> App:
    return getattr(app, "app", app)


def status_message(
    app: App,
    message: str,
    *,
    severity: SeverityLevel = "information",
    timeout: float = 5.0,
) -> None:
    """Show a transient message in the bottom status bar."""
    root = _app_root(app)
    post_status = getattr(root, "post_status", None)
    if post_status is not None:
        post_status(message, severity=severity, timeout=timeout)
