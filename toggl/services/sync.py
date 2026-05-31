"""Sync metadata management — history tracking, auto-update checks.

These are the persistence and decision functions for sync timestamps,
independent of the CSV data layer.
"""

from __future__ import annotations

import json
import os

from typing import Any

from toggl.const import HISTORY_FILE


def _load_history() -> dict[str, Any]:
    """Load sync history from JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: dict) -> None:
    """Save sync history to JSON file (atomic write)."""
    from toggl.cache import _atomic_write

    _atomic_write(HISTORY_FILE, json.dumps(history, indent=4))
